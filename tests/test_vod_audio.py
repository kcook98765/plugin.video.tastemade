"""VOD AUDIO linkage and public-header regressions; synthetic URLs only."""
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import test_hardening as fixtures
import service
import sys

BASE = 'https://fixture.invalid/content/master.m3u8'
MASTER = b'''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",DEFAULT=YES,AUTOSELECT=YES,URI="audio/main.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc1.4d401f,mp4a.40.2",AUDIO="audio"
video/high.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=500000,CODECS="avc1.4d401e,mp4a.40.2",AUDIO="audio"
video/low.m3u8
'''
MEDIA = b'#EXTM3U\n#EXTINF:10,\nsegment.ts\n#EXT-X-ENDLIST\n'


def fixture_fetch(url, *args, **kwargs):
    return {BASE: MASTER,
            'https://fixture.invalid/content/video/high.m3u8': MEDIA,
            'https://fixture.invalid/content/video/low.m3u8': MEDIA,
            'https://fixture.invalid/content/audio/main.m3u8': MEDIA}[url]


class VODAudioTests(unittest.TestCase):
    def check(self, master=MASTER, overrides=None):
        payloads = {BASE: master,
                    'https://fixture.invalid/content/video/high.m3u8': MEDIA,
                    'https://fixture.invalid/content/video/low.m3u8': MEDIA,
                    'https://fixture.invalid/content/audio/main.m3u8': MEDIA}
        payloads.update(overrides or {})
        with patch.object(service, 'fetch', side_effect=lambda url: payloads[url]) as request:
            result = service.checked_media_playlist(BASE, preserve_master=True)
        return result, request

    def test_vod_resolver_retains_master_with_audio_association(self):
        client = fixtures.ServiceTests().client()
        client.get = MagicMock(side_effect=[{}, [
            {'id': 'fixture', 'editionType': 'full', 'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}],
            {'drm': 'unencrypted', 'url': BASE}])
        with patch.object(service, 'fetch', side_effect=fixture_fetch):
            result = client.resolve('episode', 'fixture')
        self.assertTrue(result == BASE, 'VOD resolution discarded master AUDIO linkage (synthetic fixture)')

    def test_all_variants_and_shared_audio_checked_once_without_api_headers(self):
        result, request = self.check()
        self.assertTrue(result == BASE)
        self.assertEqual(request.call_count, 4)
        self.assertEqual({call.args[0] for call in request.call_args_list}, {
            BASE, 'https://fixture.invalid/content/video/high.m3u8',
            'https://fixture.invalid/content/video/low.m3u8',
            'https://fixture.invalid/content/audio/main.m3u8'})
        self.assertTrue(all(len(call.args) == 1 and not call.kwargs for call in request.call_args_list))

    def test_combined_audio_video_master_preserved(self):
        combined = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100,CODECS="avc1.4d401f,mp4a.40.2"\nvideo/high.m3u8\n'
        result, request = self.check(combined)
        self.assertTrue(result == BASE)
        self.assertEqual(request.call_count, 2)

    def test_direct_combined_media_playlist_preserved(self):
        result, request = self.check(MEDIA)
        self.assertTrue(result == BASE)
        self.assertEqual(request.call_count, 1)

    def test_relative_parent_and_root_audio_references_resolve(self):
        for reference, resolved in [('../shared/audio.m3u8', 'https://fixture.invalid/shared/audio.m3u8'),
                                    ('/audio.m3u8', 'https://fixture.invalid/audio.m3u8'),
                                    ('//fixture.invalid/audio.m3u8', 'https://fixture.invalid/audio.m3u8')]:
            with self.subTest(reference_type=reference.split('/')[0]):
                master = MASTER.replace(b'audio/main.m3u8', reference.encode())
                result, request = self.check(master, {resolved: MEDIA})
                self.assertTrue(result == BASE)
                self.assertIn(resolved, [call.args[0] for call in request.call_args_list])

    def test_multiple_named_audio_renditions_in_one_group(self):
        second = b'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="French",URI="audio/fr.m3u8"\n'
        master = MASTER.replace(b'#EXTM3U\n', b'#EXTM3U\n' + second)
        result, request = self.check(master, {'https://fixture.invalid/content/audio/fr.m3u8': MEDIA})
        self.assertTrue(result == BASE)
        self.assertEqual(request.call_count, 5)

    def test_in_band_audio_group_without_uri_is_valid(self):
        master = MASTER.replace(b',URI="audio/main.m3u8"', b'')
        _, request = self.check(master)
        self.assertEqual(request.call_count, 3)

    def test_missing_or_empty_referenced_audio_group_rejected(self):
        for replacement in [b'AUDIO="missing"', b'AUDIO=""']:
            with self.subTest(empty=replacement == b'AUDIO=""'), self.assertRaises(service.UnsupportedStreamError):
                self.check(MASTER.replace(b'AUDIO="audio"', replacement))
        without_group = b'\n'.join(line for line in MASTER.split(b'\n') if not line.startswith(b'#EXT-X-MEDIA:'))
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(without_group)

    def test_malformed_audio_group_declarations_rejected(self):
        changes = [(b'GROUP-ID="audio"', b'GROUP-ID=""'),
                   (b'GROUP-ID="audio"', b'GROUP-ID=audio'),
                   (b'NAME="English"', b'NAME=""'),
                   (b',NAME="English"', b''),
                   (b'URI="audio/main.m3u8"', b'URI=""'),
                   (b'AUTOSELECT=YES', b'AUTOSELECT=NO'),
                   (b'DEFAULT=YES', b'DEFAULT=invalid')]
        for old, new in changes:
            with self.subTest(case=changes.index((old, new))), self.assertRaises(service.UnsupportedStreamError):
                self.check(MASTER.replace(old, new))

    def test_duplicate_audio_names_rejected_but_quoted_commas_valid(self):
        duplicate = MASTER.replace(b'#EXTM3U\n', b'#EXTM3U\n' + MASTER.splitlines(keepends=True)[1])
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(duplicate)
        self.check(MASTER.replace(b'NAME="English"', b'NAME="English, stereo"'))

    def test_missing_variant_uri_and_nested_master_rejected(self):
        for master in [b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n',
                       b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n#comment\n']:
            with self.assertRaises(service.UnsupportedStreamError):
                self.check(master)
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(overrides={'https://fixture.invalid/content/video/high.m3u8': MASTER})

    def test_encryption_in_master_video_or_audio_rejected(self):
        encrypted = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:10,\ns.ts\n'
        for path in ['https://fixture.invalid/content/video/high.m3u8',
                     'https://fixture.invalid/content/video/low.m3u8',
                     'https://fixture.invalid/content/audio/main.m3u8']:
            with self.subTest(role='audio' if '/audio/' in path else 'video'), self.assertRaises(service.UnsupportedStreamError):
                self.check(overrides={path: encrypted})
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(MASTER.replace(b'#EXTM3U\n', b'#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES\n'))

    def test_unsafe_audio_references_rejected(self):
        references = ['http://fixture.invalid/audio.m3u8', 'audio.m3u8?token=synthetic',
                      'audio.m3u8#fragment', 'https://user:fixture@fixture.invalid/audio.m3u8',
                      'audio.m3u8|Cookie=fixture', 'audio.m3u8%7CCookie=fixture',
                      'audio.m3u8%0d%0aCookie:fixture', '{$variable}.m3u8']
        for index, reference in enumerate(references):
            with self.subTest(case=index), self.assertRaises(service.UnsupportedStreamError):
                self.check(MASTER.replace(b'audio/main.m3u8', reference.encode()))

    def test_unsafe_segments_and_init_map_rejected(self):
        for child in [MEDIA.replace(b'segment.ts', b'segment.ts?token=synthetic'),
                      b'#EXTM3U\n#EXT-X-MAP:URI="http://fixture.invalid/init.mp4"\n#EXTINF:10,\ns.m4s\n']:
            with self.assertRaises(service.UnsupportedStreamError):
                self.check(overrides={'https://fixture.invalid/content/audio/main.m3u8': child})

    def test_graph_size_and_reference_bounds(self):
        large = b'#EXTM3U\n' + b''.join(b'#EXT-X-STREAM-INF:BANDWIDTH=1\nv' + str(i).encode() + b'.m3u8\n'
                                           for i in range(service.MAX_VOD_PLAYLISTS))
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(large)
        many_refs = b'#EXTM3U\n' + b'#EXTINF:1,\ns.ts\n' * (service.MAX_VOD_REFERENCES + 1)
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(many_refs)

    def test_content_steering_and_redirect_policy_not_expanded(self):
        with self.assertRaises(service.UnsupportedStreamError):
            self.check(MASTER.replace(b'#EXTM3U\n', b'#EXTM3U\n#EXT-X-CONTENT-STEERING:SERVER-URI="steer.json"\n'))
        with self.assertRaises(service.ServiceError):
            service.NoRedirect().redirect_request(None, None, 302, 'fixture', {}, 'https://fixture.invalid/redirect')

    def test_only_vod_resolver_requests_master_preservation(self):
        for kind in ['episode', 'movie', 'clip']:
            client = fixtures.ServiceTests().client()
            client.get = MagicMock(side_effect=[{}, [
                {'id': 'fixture', 'editionType': 'full', 'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}],
                {'drm': 'unencrypted', 'url': BASE}])
            with patch.object(service, 'checked_media_playlist', return_value=BASE) as check:
                client.resolve(kind, 'fixture')
            check.assert_called_once_with(BASE, preserve_master=True)

    def test_native_path_only_contains_public_user_agent(self):
        base, options = service.vod_playback_path(BASE).split('|')
        self.assertTrue(base == BASE)
        self.assertEqual(parse_qs(options), {'User-Agent': ['Mozilla/5.0']})
        for bad in [BASE + '|Cookie=fixture', BASE + '?token=synthetic', BASE + '%0d%0aHeader:fixture']:
            with self.assertRaises(service.UnsupportedStreamError):
                service.vod_playback_path(bad)


class VODKodiPathTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)

    def route(self, kind):
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', '?action=play&kind=' + kind + '&asset=fixture']):
            self.plugin.run()

    def test_native_vod_receives_master_and_public_header_only(self):
        client = MagicMock()
        client.resolve.return_value = BASE
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', return_value=(client, 'reused')):
            self.route('episode')
        path = self.modules['xbmcgui'].ListItem.call_args.kwargs['path']
        base, options = path.split('|')
        self.assertTrue(base == BASE)
        self.assertEqual(parse_qs(options), {'User-Agent': ['Mozilla/5.0']})
        self.modules['xbmcplugin'].setResolvedUrl.assert_called_once()
        self.assertTrue(self.modules['xbmcplugin'].setResolvedUrl.call_args.args[1])

if __name__ == '__main__':
    unittest.main()
