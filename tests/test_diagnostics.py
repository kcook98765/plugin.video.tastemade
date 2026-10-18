"""Sanitized diagnostics and current-policy characterization; offline only."""
import json
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import test_hardening as fixtures
import diagnostics
import service

MARKER = 'SYNTHETIC_SENSITIVE_SENTINEL'


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.lines = []
        diagnostics.configure(self.lines.append)
        self.addCleanup(diagnostics.configure)

    def assert_private(self):
        self.assertNotIn(MARKER, '\n'.join(self.lines))
        self.assertTrue(all(len(line) < 200 for line in self.lines))
        self.assertTrue(all('https://' not in line and '?' not in line for line in self.lines))

    def test_exception_strings_payloads_and_urls_not_formatted(self):
        error = HTTPError('https://fixture.invalid/?auth=' + MARKER, 403, MARKER, {'Authorization': MARKER}, None)
        line = diagnostics.report('resolve.stream', error)
        self.assertIn('http_status=403 exception=HTTPError', line)
        self.assert_private()

    def test_unknown_stage_category_class_and_status_are_fixed(self):
        error = type(MARKER, (Exception,), {'category': MARKER, 'status': MARKER})(MARKER)
        line = diagnostics.report(MARKER, error)
        self.assertEqual(line, 'Tastemade diagnostic stage=unknown category=unexpected http_status=none exception=OtherError')
        self.assert_private()

    def test_bad_metadata_and_unprintable_exception_do_not_interrupt(self):
        class Hostile(Exception):
            def __str__(self):
                raise AssertionError('Do not format exceptions')
            @property
            def category(self):
                raise ValueError(MARKER)
            @property
            def status(self):
                raise ValueError(MARKER)
        diagnostics.report('directory.page', Hostile())
        self.assert_private()

    def test_http_status_bounds(self):
        for status in [None, True, 99, 600, '403', MARKER, 0, -1]:
            with self.subTest(status_type=type(status).__name__):
                self.assertIn('http_status=none', diagnostics.report('request.http', ValueError(MARKER), status=status))
        for status in [100, 401, 403, 429, 500, 599]:
            self.assertIn('http_status=' + str(status), diagnostics.report('request.http', ValueError(MARKER), status=status))
        self.assert_private()

    def test_logger_failure_does_not_mask_original_error(self):
        diagnostics.configure(MagicMock(side_effect=RuntimeError(MARKER)))
        with self.assertRaises(KeyError):
            with diagnostics.diagnostic_stage('catalog.page'):
                raise KeyError(MARKER)

    def test_path_and_action_identifiers_never_enter_stage(self):
        self.assertEqual(diagnostics.request_stage('/media/episodes/' + MARKER + '/stream'), 'resolve.stream')
        self.assertEqual(diagnostics.request_stage('/pages/' + MARKER), 'catalog.page')
        self.assertEqual(diagnostics.directory_stage(MARKER), 'directory.other')

    def test_json_decode_diagnostic_does_not_include_response(self):
        with patch.object(service, 'fetch', return_value=('{"private":"' + MARKER).encode()), self.assertRaises(service.ServiceError):
            service.json_request('https://fixture.invalid/', {})
        self.assertIn('stage=response.json', self.lines[-1])
        self.assertIn('exception=JSONDecodeError', self.lines[-1])
        self.assert_private()

    def test_http_network_error_keeps_original_bounded_status(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError('https://fixture.invalid/?secret=' + MARKER, 503, MARKER, {}, None)
        with patch.object(service, 'build_opener', return_value=opener), self.assertRaises(service.NetworkError):
            service.fetch('https://fixture.invalid/')
        self.assertIn('category=network http_status=503 exception=HTTPError', self.lines[-1])
        self.assert_private()

    def test_restriction_stages_without_weakening_guards(self):
        with self.assertRaises(service.UnsupportedStreamError):
            service.checked_media_playlist('https://fixture.invalid/master.m3u8?session=' + MARKER)
        self.assertTrue(any('stage=manifest.url_policy' in line for line in self.lines))
        self.assert_private()

    def test_request_failure_keeps_catalog_stage_status(self):
        client = fixtures.ServiceTests().client()
        with patch.object(service, 'json_request', side_effect=service.HTTPFailure(403)), self.assertRaises(service.HTTPFailure):
            client.get('/pages/' + MARKER)
        self.assertIn('stage=catalog.page category=service http_status=403 exception=HTTPFailure', self.lines[-1])
        self.assert_private()

    def test_documents_external_audio_association_loss_without_fix(self):
        # Characterization, NOT an assertion that this is acceptable playback.
        # This valid external-audio fixture demonstrates the existing defect;
        # it does not establish that the observed Shield VOD uses this layout.
        master = b'''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",DEFAULT=YES,URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc1.4d401f",AUDIO="audio"
video.m3u8
'''
        child = b'#EXTM3U\n#EXTINF:10,\nvideo.ts\n#EXT-X-ENDLIST\n'
        with patch.object(service, 'fetch', side_effect=[master, child]) as request:
            result = service.checked_media_playlist('https://fixture.invalid/master.m3u8')
        self.assertEqual(result, 'https://fixture.invalid/video.m3u8')
        self.assertNotEqual(result, 'https://fixture.invalid/master.m3u8')
        self.assertEqual(request.call_count, 2)
        self.assertNotIn('#EXT-X-MEDIA', child.decode())

    def test_non_full_channel_edition_is_only_a_policy_characterization(self):
        client = fixtures.ServiceTests().client()
        client.get = MagicMock(side_effect=[{}, [{'id': 'fixture', 'editionType': 'linear', 'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}]])
        with self.assertRaises(service.UnsupportedStreamError):
            client.resolve('channel', 'fixture')
        self.assertTrue(any('stage=resolve.edition_policy' in line for line in self.lines))
        self.assertEqual(client.get.call_count, 2)

    def test_legacy_native_selector_still_rejects_queries_without_global_relaxation(self):
        # Live now uses a separate ISA path; VOD/legacy checks remain strict.
        with patch.object(service, 'fetch') as fetch, self.assertRaises(service.UnsupportedStreamError):
            service.checked_media_playlist('https://fixture.invalid/live.m3u8?session=' + MARKER)
        fetch.assert_not_called()
        self.assertTrue(any('stage=manifest.url_policy' in line for line in self.lines))
        self.assert_private()


class CallbackTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)
        self.modules['xbmc'].log = MagicMock()
        self.modules['xbmc'].LOGWARNING = 2  # Known Nexus constant, mock only.
        self.addCleanup(diagnostics.configure)

    def route(self, action):
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', '?action=' + action]):
            self.plugin.run()

    def test_unexpected_directory_failure_logs_safe_class_and_completes_once(self):
        with patch.object(self.plugin, 'Client', side_effect=KeyError(MARKER)):
            self.route('browse')
        line = self.modules['xbmc'].log.call_args.args[0]
        self.assertIn('stage=directory.browse category=unexpected', line)
        self.assertIn('exception=KeyError', line)
        self.assertNotIn(MARKER, line)
        self.assertEqual(self.dialog.ok.call_args.args[1], 'label-30009')
        self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(1, succeeded=False, cacheToDisc=False)
        self.modules['xbmcplugin'].setResolvedUrl.assert_not_called()

    def test_failed_resolution_callback_still_called_once_if_logger_fails(self):
        self.modules['xbmc'].log.side_effect = RuntimeError(MARKER)
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', side_effect=service.UnsupportedStreamError('Unsupported stream.')):
            self.route('play')
        self.modules['xbmcplugin'].setResolvedUrl.assert_called_once()
        self.assertFalse(self.modules['xbmcplugin'].setResolvedUrl.call_args.args[1])
        self.modules['xbmcplugin'].endOfDirectory.assert_not_called()

    def test_successful_root_completion_unchanged_and_no_failure_logging(self):
        self.route('root')
        self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(1, succeeded=True, cacheToDisc=False)
        self.assertEqual(self.modules['xbmcplugin'].addDirectoryItem.call_count, 4)
        self.modules['xbmc'].log.assert_not_called()

    def test_successful_resolution_callback_still_called_once(self):
        client = MagicMock()
        client.resolve.return_value = 'https://fixture.invalid/media.m3u8'
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', return_value=(client, 'reused')):
            self.route('play')
        self.modules['xbmcplugin'].setResolvedUrl.assert_called_once()
        self.assertTrue(self.modules['xbmcplugin'].setResolvedUrl.call_args.args[1])
        self.modules['xbmcplugin'].endOfDirectory.assert_not_called()
        self.modules['xbmc'].log.assert_not_called()


if __name__ == '__main__':
    unittest.main()
