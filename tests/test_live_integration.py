"""Live root policy and resolver contracts; synthetic fixtures, no requests."""
from contextlib import ExitStack
import logging
from pathlib import Path
import traceback
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import quote
import xml.etree.ElementTree as ET

import test_hardening as fixtures
import diagnostics
import service


REPO = Path(__file__).resolve().parents[1]
HOST = 'cdn-uw2-prod.tsv2.amagi.tv'
BASE = 'https://' + HOST + '/fixture/master.m3u8'
BEARER = 'SYNTHETIC_API_BEARER'
ROOT = BASE + '?unknown=a%20b&token=synthetic-media&sessionId=fixture&signature=a%2Bb&unknown=second'


def live_client(url=ROOT):
    client = fixtures.ServiceTests().client()
    client.headers = {'Authorization': 'Bearer ' + BEARER, 'X-Fixture': 'not-a-credential'}
    client.get = MagicMock(side_effect=[{}, [
        {'id': 'fixture', 'editionType': 'full',
         'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}],
        {'drm': 'unencrypted', 'url': url}])
    return client


class OfflineLiveTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.fetch = stack.enter_context(patch.object(
            service, 'fetch', side_effect=AssertionError('No media requests in live root validation.')))
        self.request = stack.enter_context(patch.object(
            service, 'json_request', side_effect=AssertionError('Only synthetic API responses are permitted.')))
        self.python_log = stack.enter_context(patch.object(logging.Logger, '_log'))
        self.lines = []
        diagnostics.configure(self.lines.append)
        self.addCleanup(diagnostics.configure)

    def tearDown(self):
        self.fetch.assert_not_called()
        self.request.assert_not_called()
        emitted = repr(self.lines) + repr(self.python_log.call_args_list)
        for value in ['https://', BEARER, 'synthetic-media', 'synthetic@example.invalid',
                      'synthetic-password', 'eight888']:
            self.assertNotIn(value, emitted)


class LiveUrlPolicyTests(OfflineLiveTests):
    def test_signed_unknown_duplicate_and_many_query_fields_are_byte_unchanged(self):
        urls = [BASE, ROOT, BASE.replace(HOST, HOST + ':443'),
                 BASE + '?token=a%2fb%2Bc==&sessionId=one+two&signature=%2F%2b&empty=&flag',
                BASE + '?access_token=synthetic-media&user=public-channel&email=public-metadata',
                BASE + '?' + '&'.join('unknown{}=value'.format(i) for i in range(24))]
        for index, url in enumerate(urls):
            with self.subTest(case=index):
                self.assertEqual(service.checked_live_url(url), url)

    def test_only_exact_https_host_default_port_and_nonempty_path_are_accepted(self):
        urls = [None, '', 42, BASE.replace('https:', 'http:'),
                BASE.replace(HOST, 'fixture.invalid'), BASE.replace(HOST, HOST + '.fixture.invalid'),
                BASE.replace(HOST, 'sub.' + HOST), BASE.replace(HOST, HOST + '.'),
                BASE.replace(HOST, HOST + ':444'), BASE.replace(HOST, HOST + ':invalid'),
                BASE.replace(HOST, 'user@' + HOST), BASE.replace(HOST, 'user:pass@' + HOST),
                BASE.replace(HOST, '@' + HOST), BASE + '#fragment', BASE + '#',
                'https://' + HOST, 'https://' + HOST + '?token=fixture']
        for index, url in enumerate(urls):
            with self.subTest(case=index), self.assertRaises(service.UnsupportedStreamError):
                service.checked_live_url(url)

    def test_raw_whitespace_controls_and_encoded_protocol_injection_are_refused(self):
        unsafe = [' ', '\t', '\r', '\n', '\x00', '\x1f', '\x7f', '\u00a0', '|', '\\',
                  '%00', '%09', '%0a', '%0D', '%1f', '%7f', '%7C', '%7c', '%5C', '%5c']
        for value in unsafe:
            for url in [BASE + '?custom=' + value + 'fixture',
                        BASE.replace('/fixture/', '/fix' + value + 'ture/')]:
                with self.subTest(value=repr(value), location='query' if '?' in url else 'path'), \
                        self.assertRaises(service.UnsupportedStreamError):
                    service.checked_live_url(url)
        for url in [' ' + BASE, BASE + '\n']:
            with self.assertRaises(service.UnsupportedStreamError):
                service.checked_live_url(url)

    def test_reusable_credential_query_keys_are_normalized_and_refused(self):
        keys = ['refreshToken', 'refresh_token', 'password', 'Pass-word',
                'cookie', 'cookies', 'authorization', 'set_cookie',
                'api_key', 'API.KEY', 'client_secret', 'clientSecret']
        for key in keys:
            with self.subTest(key=key), self.assertRaises(service.UnsupportedStreamError):
                service.checked_live_url(BASE + '?token=allowed&' + key + '=synthetic')

    def test_known_long_credentials_are_refused_in_decoded_path_and_query(self):
        for credential in [BEARER, 'synthetic@example.invalid', 'synthetic-password', 'eight888']:
            encoded = ''.join('%{:02X}'.format(ord(char)) for char in credential)
            for url in [BASE + '?token=prefix' + encoded + 'suffix',
                        BASE.replace('/fixture/', '/prefix' + encoded + 'suffix/')]:
                with self.subTest(length=len(credential), location='query' if '?' in url else 'path'), \
                        self.assertRaises(service.UnsupportedStreamError) as result:
                    service.checked_live_url(url, credentials=(credential,))
                self.assertNotIn(credential, ''.join(traceback.format_exception(result.exception)))

    def test_form_encoded_spaces_do_not_hide_long_credential_substrings(self):
        credential = 'long pass'
        with self.assertRaises(service.UnsupportedStreamError):
            service.checked_live_url(BASE + '?custom=prefixlong+passsuffix', credentials=(credential,))

    def test_encoded_slash_is_not_a_boundary_for_short_credential_components(self):
        credential = 'abc/def'
        for encoded in ['abc%2Fdef', 'abc%252Fdef', 'abc/def']:
            with self.subTest(encoding=encoded), self.assertRaises(service.UnsupportedStreamError):
                service.checked_live_url(BASE.replace('/fixture/', '/' + encoded + '/'),
                                         credentials=(credential,))

    def test_short_credentials_match_complete_query_values_or_path_components(self):
        for credential in ['abc', 'seven77', 'a b']:
            for value in [quote(credential, safe=''), quote(credential, safe='').replace('%20', '+')]:
                with self.subTest(length=len(credential)), self.assertRaises(service.UnsupportedStreamError):
                    service.checked_live_url(BASE + '?custom=' + value, credentials=(credential,))
            for url in [BASE + '?token=prefix' + quote(credential, safe='') + 'suffix',
                        BASE.replace('/fixture/', '/prefix' + quote(credential, safe='') + 'suffix/')]:
                self.assertEqual(service.checked_live_url(url, credentials=(credential,)), url)
            with self.assertRaises(service.UnsupportedStreamError):
                service.checked_live_url(BASE.replace('/fixture/', '/' + quote(credential, safe='') + '/'),
                                         credentials=(credential,))
        self.assertEqual(service.checked_live_url(ROOT, credentials=('',)), ROOT)


class LiveResolverTests(OfflineLiveTests):
    def test_authorized_channel_checks_root_after_api_with_bearer_only_and_no_crawl(self):
        url = ROOT + '&custom=not-a-credential'
        client = live_client(url)
        client.get.side_effect = [{}, [
            {'id': 'blocked', 'editionType': 'full', 'blocked': [{'reason': 'GEO'}]},
            {'id': 'preview', 'editionType': 'preview',
             'streams': [{'type': 'hls', 'drm': 'unencrypted'}]},
            {'id': 'fixture', 'editionType': 'full',
             'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}],
            {'drm': 'unencrypted', 'url': url}]
        check = service.checked_live_url

        def checked(value, credentials=()):
            self.assertEqual(client.get.call_count, 3)
            self.assertEqual(tuple(credentials), (BEARER,))
            return check(value, credentials=credentials)

        with patch.object(service, 'checked_live_url', side_effect=checked) as policy, \
                patch.object(service, 'checked_media_playlist') as vod:
            self.assertEqual(client.resolve('channel', 'fixture'), url)
        policy.assert_called_once()
        vod.assert_not_called()
        self.assertEqual([call.args[0] for call in client.get.call_args_list], [
            '/media/channels/fixture', '/media/channels/fixture/editions', '/media/channels/fixture/stream'])
        self.assertEqual(client.get.call_args_list[-1].args[1], {
            'editionId': 'fixture', 'type': 'hls', 'drm': 'unencrypted'})

    def test_current_api_bearer_in_signed_url_is_refused_without_leaking(self):
        for bearer in [BEARER, 'short']:
            client = live_client(BASE + '?token=' + quote(bearer, safe=''))
            client.headers['Authorization'] = 'Bearer stale-synthetic-bearer'
            responses = iter(client.get.side_effect)

            def response(path, query=None):
                if path.endswith('/stream'):
                    # A stream API request may have refreshed the session.
                    client.headers['Authorization'] = 'Bearer ' + bearer
                return next(responses)

            client.get.side_effect = response
            with self.subTest(length=len(bearer)), self.assertRaises(service.UnsupportedStreamError) as result:
                client.resolve('channel', 'fixture')
            self.assertEqual(client.get.call_count, 3)
            self.assertNotIn(bearer, ''.join(traceback.format_exception(result.exception)))
            self.assertNotIn(bearer, repr(self.lines))

    def test_short_api_bearer_with_authorization_prefix_is_also_refused(self):
        client = live_client(BASE + '?custom=Bearer+short')
        client.headers['Authorization'] = 'Bearer short'
        with self.assertRaises(service.UnsupportedStreamError):
            client.resolve('channel', 'fixture')

    def test_asset_and_edition_blockers_stop_before_root_policy(self):
        cases = [([{'blocked': [{'reason': 'AUTHENTICATION'}]}], service.AuthenticationError),
                 ([{}, [{'id': 'fixture', 'editionType': 'full',
                         'blocked': [{'reason': 'GEO'}]}]], service.RegionError),
                 ([{}, [{'id': 'fixture', 'editionType': 'full',
                         'blocked': [{'reason': 'SUBSCRIPTION'}]}]], service.EntitlementError)]
        for responses, error in cases:
            client = live_client()
            client.get.side_effect = responses
            with self.subTest(error=error.__name__), patch.object(service, 'checked_live_url') as policy, \
                    self.assertRaises(error):
                client.resolve('channel', 'fixture')
            policy.assert_not_called()
            self.assertEqual(client.get.call_count, len(responses))

    def test_non_full_encrypted_and_indirect_results_never_reach_root_policy(self):
        cases = [
            [{}, [{'id': 'fixture', 'editionType': 'linear',
                   'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}]],
            [{}, [{'id': 'fixture', 'editionType': 'preview',
                   'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}]],
            [{}, [{'id': 'fixture', 'editionType': 'full',
                   'streams': [{'type': 'hls', 'drm': 'widevine'}]}]],
            [{}, [{'id': 'fixture', 'editionType': 'full',
                   'streams': [{'type': 'dash', 'drm': 'unencrypted'}]}]],
        ]
        full = {'id': 'fixture', 'editionType': 'full',
                'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}
        cases.extend([[{}, [full], {'drm': 'widevine', 'url': ROOT}],
                      [{}, [full], {'drm': 'unencrypted'}]])
        for index, responses in enumerate(cases):
            client = live_client()
            client.get.side_effect = responses
            with self.subTest(case=index), patch.object(service, 'checked_live_url') as policy, \
                    self.assertRaises(service.UnsupportedStreamError):
                client.resolve('channel', 'fixture')
            policy.assert_not_called()
            self.assertEqual(client.get.call_count, len(responses))


class LiveAddonContractTests(unittest.TestCase):
    def test_manifest_has_optional_isa_floor_and_no_service_or_helper(self):
        manifest = ET.parse(REPO / 'addon.xml').getroot()
        dependencies = manifest.findall('requires/import')
        self.assertEqual({node.get('addon') for node in dependencies}, {'xbmc.python', 'inputstream.adaptive'})
        self.assertEqual(len(dependencies), 2)
        python, isa = [next(node for node in dependencies if node.get('addon') == name)
                       for name in ['xbmc.python', 'inputstream.adaptive']]
        self.assertEqual(python.get('version'), '3.0.1')
        self.assertEqual(isa.get('version'), '20.3.18')
        self.assertEqual(isa.get('optional'), 'true')
        self.assertFalse(manifest.findall("extension[@point='xbmc.service']"))
        self.assertEqual(manifest.find("extension[@point='xbmc.python.pluginsource']").get('library'), 'default.py')

    def test_real_live_setting_defaults_off_and_old_relay_files_are_absent(self):
        settings = ET.parse(REPO / 'resources/settings.xml').getroot()
        nodes = settings.findall('.//setting')
        self.assertEqual({node.get('id') for node in nodes}, {'username', 'password', 'enable_live'})
        live = next(node for node in nodes if node.get('id') == 'enable_live')
        self.assertEqual(live.get('type'), 'boolean')
        self.assertEqual(live.findtext('default'), 'false')
        for name in ['username', 'password']:
            node = next(node for node in nodes if node.get('id') == name)
            self.assertFalse(node.findtext('default'))
        for path in ['live_service.py', 'resources/lib/live_relay.py', 'tests/test_live_relay.py']:
            with self.subTest(path=path):
                self.assertFalse((REPO / path).exists())


if __name__ == '__main__':
    unittest.main()
