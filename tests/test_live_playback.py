"""ISA properties and plugin callbacks with NavigationTests' mocked Kodi only."""
from contextlib import ExitStack
from inspect import signature
import logging
import sys
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import test_hardening as fixtures
import diagnostics
import live_playback
import service


BASE = 'https://cdn-uw2-prod.tsv2.amagi.tv/fixture/master.m3u8'
ROOT = BASE + '?token=synthetic-media&unknown=a%20b&unknown=two&signature=a%2Bb'
PUBLIC_HEADERS = urlencode({'User-Agent': 'Mozilla/5.0'})
PROPERTIES = {
    'inputstream': 'inputstream.adaptive',
    'IsPlayable': 'true',
    'inputstream.adaptive.manifest_headers': PUBLIC_HEADERS,
    'inputstream.adaptive.stream_headers': PUBLIC_HEADERS,
}


class LivePropertiesTests(unittest.TestCase):
    def test_20_numeric_floor_and_build_return_only_public_headers_and_hls_type(self):
        for version in ['20.3.18', '20.3.18.0', '20.3.18.12', '20.3.100', '20.10.0', '20.99.0']:
            with self.subTest(version=version):
                self.assertEqual(live_playback.live_properties(version), {
                    **PROPERTIES, 'inputstream.adaptive.manifest_type': 'hls'})

    def test_21_numeric_floor_and_build_omit_manifest_type_and_other_options(self):
        for version in ['21.4.3', '21.4.3.0', '21.4.3.12', '21.4.10', '21.10.0', '21.99.0']:
            with self.subTest(version=version):
                self.assertEqual(live_playback.live_properties(version), PROPERTIES)

    def test_older_other_major_and_malformed_versions_raise_fixed_service_error(self):
        versions = ['20.3.17', '20.2.100', '20.0.0', '21.4.2', '21.3.100',
                    '19.99.99', '22.0.0', '3.4.0', '', None, 20318,
                    '20.3', '20.3.18.1.2', '20.3.18-beta1', 'v20.3.18',
                    '20.3.18.foo', '20.-3.18', '20.3.x', ' 20.3.18', '20.3.18\n',
                    '20.3.18.', '20.3.18.+1', '20.3.18-SYNTHETIC_PRIVATE']
        self.assertIsInstance(live_playback.INPUTSTREAM_ERROR, str)
        self.assertTrue(live_playback.INPUTSTREAM_ERROR)
        for index, version in enumerate(versions):
            with self.subTest(case=index), self.assertRaises(service.ServiceError) as result:
                live_playback.live_properties(version)
            self.assertEqual(str(result.exception), live_playback.INPUTSTREAM_ERROR)


class LiveKodiPlaybackTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.original_properties = live_playback.live_properties
        # Patch exported APIs before NavigationTests imports plugin: both
        # direct imports and module-qualified calls exercise the same spies.
        self.properties = stack.enter_context(patch.object(
            live_playback, 'live_properties', wraps=self.original_properties))
        self.original_ensure = live_playback.ensure_inputstream
        self.ensure = stack.enter_context(patch.object(
            live_playback, 'ensure_inputstream', wraps=self.original_ensure))
        self.guard = stack.enter_context(patch.object(
            service, 'checked_live_url', wraps=service.checked_live_url))
        fixtures.NavigationTests.setUp(self)
        self.modules['xbmc'].log = MagicMock()
        self.modules['xbmc'].LOGWARNING = 2  # Verified Nexus constant, mock only.
        self.modules['xbmc'].getCondVisibility = MagicMock(return_value=False)
        self.dialog.yesno.return_value = False
        self.addCleanup(diagnostics.configure)
        self.addon.getSettingBool.return_value = True
        self.isa = MagicMock()
        self.isa.getAddonInfo.return_value = '20.3.18'
        self.isa_error = None

        def addon(addon_id=None):
            if addon_id is None:
                return self.addon
            self.assertEqual(addon_id, 'inputstream.adaptive')
            if self.isa_error is not None:
                raise self.isa_error
            return self.isa

        self.modules['xbmcaddon'].Addon.side_effect = addon
        self.store = stack.enter_context(patch.object(self.plugin, 'SessionStore'))
        self.client = MagicMock()
        self.client.resolve.return_value = ROOT
        self.auth = stack.enter_context(patch.object(
            self.plugin, 'authenticated_client', return_value=(self.client, 'reused')))
        self.factory = stack.enter_context(patch.object(self.plugin, 'Client'))
        self.fetch = stack.enter_context(patch.object(
            service, 'fetch', side_effect=AssertionError('No real requests from plugin tests.')))
        self.request = stack.enter_context(patch.object(
            service, 'json_request', side_effect=AssertionError('No real API requests from plugin tests.')))
        self.python_log = stack.enter_context(patch.object(logging.Logger, '_log'))

    def reset_calls(self):
        for mock in [self.addon, self.isa, self.store, self.auth, self.client, self.factory,
                     self.properties, self.ensure, self.guard,
                     self.dialog, self.python_log, self.modules['xbmcaddon'].Addon,
                     self.modules['xbmcgui'].ListItem, self.modules['xbmc'].log,
                     self.modules['xbmc'].getCondVisibility, self.modules['xbmc'].executebuiltin,
                     self.modules['xbmcplugin'].setResolvedUrl,
                     self.modules['xbmcplugin'].endOfDirectory,
                     self.modules['xbmcplugin'].addDirectoryItem]:
            mock.reset_mock()

    def route(self, action='play', kind='channel', **parameters):
        query = urlencode(dict(action=action, kind=kind, asset='fixture', **parameters))
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', '?' + query]):
            self.plugin.run()

    def assert_private(self):
        emitted = repr(self.modules['xbmc'].log.call_args_list) + repr(self.python_log.call_args_list)
        shown = repr(self.dialog.ok.call_args_list) + repr(self.dialog.yesno.call_args_list)
        shown += repr(self.modules['xbmc'].executebuiltin.call_args_list)
        for value in ['https://', 'synthetic-media', 'fixture-username', 'fixture-password',
                      'SYNTHETIC_PRIVATE']:
            self.assertNotIn(value, emitted + shown)

    def assert_failed_once(self, message=None, setup_command=None):
        item = self.modules['xbmcgui'].ListItem.return_value
        self.modules['xbmcplugin'].setResolvedUrl.assert_called_once_with(1, False, item)
        self.modules['xbmcplugin'].endOfDirectory.assert_not_called()
        if setup_command is None:
            self.modules['xbmc'].executebuiltin.assert_not_called()
        else:
            self.modules['xbmc'].executebuiltin.assert_called_once_with(setup_command, wait=True)
        self.dialog.ok.assert_called_once()
        if message is not None:
            self.assertEqual(self.dialog.ok.call_args.args[1], message)
        for invocation in self.modules['xbmcgui'].ListItem.call_args_list:
            self.assertNotIn('path', invocation.kwargs)
        self.assert_private()

    def assert_no_account_or_api(self):
        self.addon.getSetting.assert_not_called()
        self.assertNotIn(call('profile'), self.addon.getAddonInfo.call_args_list)
        self.store.assert_not_called()
        self.auth.assert_not_called()
        self.client.resolve.assert_not_called()
        self.factory.assert_not_called()

    def assert_ensure_callbacks(self):
        self.ensure.assert_called_once()
        args, kwargs = self.ensure.call_args
        bound = signature(self.original_ensure).bind(*args, **kwargs)
        self.assertEqual(bound.arguments, {
            'addon_factory': self.modules['xbmcaddon'].Addon,
            'has_addon': self.modules['xbmc'].getCondVisibility,
            'confirm': self.dialog.yesno,
            'execute': self.modules['xbmc'].executebuiltin,
            'heading': 'Fixture',
        })

    def assert_no_consent_or_setup(self):
        self.modules['xbmc'].getCondVisibility.assert_not_called()
        self.dialog.yesno.assert_not_called()
        for invocation in self.modules['xbmc'].executebuiltin.call_args_list:
            self.assertFalse(invocation.args[0].startswith(('InstallAddon(', 'EnableAddon(')))

    def assert_isa_untouched(self):
        self.ensure.assert_not_called()
        self.isa.getAddonInfo.assert_not_called()
        self.assert_no_consent_or_setup()

    def tearDown(self):
        self.fetch.assert_not_called()
        self.request.assert_not_called()
        self.assert_private()
        self.assertIsNone(diagnostics._sink)

    def test_live_handoff_preserves_original_signed_url_properties_and_callback(self):
        for version in ['20.3.18', '21.4.3']:
            with self.subTest(version=version):
                self.reset_calls()
                self.isa.getAddonInfo.return_value = version
                order = []

                def properties(value):
                    order.append('properties')
                    self.addon.getSettingBool.assert_called_once_with('enable_live')
                    self.assert_no_account_or_api()
                    return self.original_properties(value)

                def resolve(kind, asset):
                    order.append('resolve')
                    return ROOT

                self.client.resolve.side_effect = resolve
                self.properties.side_effect = properties
                with patch.object(self.plugin, 'vod_playback_path') as vod:
                    self.route()
                self.assertEqual(order, ['properties', 'resolve'])
                self.assert_ensure_callbacks()
                self.assert_no_consent_or_setup()
                self.modules['xbmcaddon'].Addon.assert_has_calls([call(), call('inputstream.adaptive')])
                self.isa.getAddonInfo.assert_called_once_with('version')
                self.auth.assert_called_once_with(self.store.return_value, 'fixture-username', 'fixture-password')
                self.client.resolve.assert_called_once_with('channel', 'fixture')
                self.guard.assert_called_once()
                self.assertEqual(self.guard.call_args.args[0], ROOT)
                arguments = self.guard.call_args
                credentials = arguments.kwargs.get('credentials', arguments.args[1] if len(arguments.args) > 1 else ())
                self.assertEqual(tuple(credentials), ('fixture-username', 'fixture-password'))
                vod.assert_not_called()
                self.modules['xbmcgui'].ListItem.assert_called_once_with(path=ROOT)
                item = self.modules['xbmcgui'].ListItem.return_value
                expected = dict(PROPERTIES)
                if version.startswith('20.'):
                    expected['inputstream.adaptive.manifest_type'] = 'hls'
                self.assertEqual(item.setProperty.call_count, len(expected))
                self.assertEqual(dict(invocation.args for invocation in item.setProperty.call_args_list), expected)
                item.setMimeType.assert_called_once_with('application/vnd.apple.mpegurl')
                item.setContentLookup.assert_called_once_with(False)
                self.modules['xbmcplugin'].setResolvedUrl.assert_called_once_with(1, True, item)
                self.modules['xbmcplugin'].endOfDirectory.assert_not_called()
                self.modules['xbmc'].executebuiltin.assert_not_called()
                self.modules['xbmc'].log.assert_not_called()
                self.dialog.ok.assert_not_called()

    def test_live_off_explains_enable_and_isa_without_account_or_isa_access(self):
        self.addon.getSettingBool.return_value = False
        self.route()
        self.addon.getSettingBool.assert_called_once_with('enable_live')
        self.modules['xbmcaddon'].Addon.assert_called_once_with()
        self.properties.assert_not_called()
        self.assert_isa_untouched()
        self.guard.assert_not_called()
        self.assert_no_account_or_api()
        self.assert_failed_once(
            'Live TV is disabled. Enable live TV in add-on settings, then select a channel to set up InputStream Adaptive.')
        message = self.dialog.ok.call_args.args[1].casefold()
        self.assertIn('enable', message)
        self.assertIn('inputstream', message)
        self.assertIn('exception=ServiceError', repr(self.modules['xbmc'].log.call_args_list))

    def test_missing_or_disabled_isa_declined_consent_cancels_before_account(self):
        # Exact Kodi 20.5/21.3 Addon.cpp uses OnlyEnabled::CHOICE_YES:
        # a disabled installed add-on throws at construction, before metadata.
        for stage in ['missing', 'disabled']:
            with self.subTest(stage=stage):
                self.reset_calls()
                self.isa_error = RuntimeError('SYNTHETIC_PRIVATE')
                self.modules['xbmc'].getCondVisibility.return_value = stage == 'disabled'
                self.route()
                self.assert_ensure_callbacks()
                self.modules['xbmc'].getCondVisibility.assert_called_once_with(
                    'System.HasAddon(inputstream.adaptive)')
                self.dialog.yesno.assert_called_once()
                self.assertEqual(self.dialog.yesno.call_args.args[0], 'Fixture')
                self.modules['xbmcaddon'].Addon.assert_has_calls([call(), call('inputstream.adaptive')])
                self.assertEqual(self.modules['xbmcaddon'].Addon.call_count, 2)
                self.isa.getAddonInfo.assert_not_called()
                self.properties.assert_not_called()
                self.guard.assert_not_called()
                self.assert_no_account_or_api()
                self.assert_failed_once(live_playback.INPUTSTREAM_CANCELLED)

    def test_enabled_version_lookup_failure_uses_fixed_error_without_consent(self):
        self.isa.getAddonInfo.side_effect = RuntimeError('SYNTHETIC_PRIVATE')
        self.route()
        self.assert_ensure_callbacks()
        self.assert_no_consent_or_setup()
        self.isa.getAddonInfo.assert_called_once_with('version')
        self.properties.assert_not_called()
        self.assert_no_account_or_api()
        self.assert_failed_once(live_playback.INPUTSTREAM_ERROR)

    def test_bad_or_unsupported_isa_version_fails_before_account_or_network(self):
        for version in ['20.3.17', '21.4.2', '22.0.0', '20.3.18-SYNTHETIC_PRIVATE', '']:
            with self.subTest(version=version):
                self.reset_calls()
                self.isa.getAddonInfo.return_value = version
                self.route()
                self.assert_ensure_callbacks()
                self.assert_no_consent_or_setup()
                self.assert_no_account_or_api()
                self.assert_failed_once(live_playback.INPUTSTREAM_ERROR)

    def test_install_or_enable_fresh_ready_before_account_and_resolver(self):
        for installed, command in [(False, 'InstallAddon(inputstream.adaptive)'),
                                   (True, 'EnableAddon(inputstream.adaptive)')]:
            with self.subTest(installed=installed):
                self.reset_calls()
                order = []

                def addon(addon_id=None):
                    if addon_id is None:
                        return self.addon
                    self.assertEqual(addon_id, 'inputstream.adaptive')
                    self.assert_no_account_or_api()
                    if 'probe' not in order:
                        order.append('probe')
                        raise RuntimeError('SYNTHETIC_PRIVATE')
                    self.assertEqual(order[-1], 'execute')
                    order.append('fresh')
                    return self.isa

                def visible(condition):
                    self.assertEqual(condition, 'System.HasAddon(inputstream.adaptive)')
                    self.assert_no_account_or_api()
                    order.append('visibility')
                    return installed

                def confirm(heading, message):
                    self.assertEqual(heading, 'Fixture')
                    self.assertIn('enabl' if installed else 'install', message.casefold())
                    self.assert_no_account_or_api()
                    order.append('consent')
                    return True

                def execute(value, *, wait):
                    self.assertEqual((value, wait), (command, True))
                    self.assert_no_account_or_api()
                    order.append('execute')
                    return None

                def version(key):
                    self.assertEqual(key, 'version')
                    self.assert_no_account_or_api()
                    order.append('version')
                    return '20.3.18'

                def properties(value):
                    self.assertEqual(order[-1], 'version')
                    self.assert_no_account_or_api()
                    order.append('properties')
                    return self.original_properties(value)

                def account(*args):
                    self.assertEqual(order[-1], 'properties')
                    order.append('account')
                    return self.store.return_value

                def authenticate(*args):
                    order.append('authenticate')
                    return self.client, 'reused'

                def resolve(*args):
                    order.append('resolve')
                    return ROOT

                self.modules['xbmcaddon'].Addon.side_effect = addon
                self.modules['xbmc'].getCondVisibility.side_effect = visible
                self.dialog.yesno.side_effect = confirm
                self.modules['xbmc'].executebuiltin.side_effect = execute
                self.isa.getAddonInfo.side_effect = version
                self.properties.side_effect = properties
                self.store.side_effect = account
                self.auth.side_effect = authenticate
                self.client.resolve.side_effect = resolve
                with patch.object(self.plugin, 'vod_playback_path') as vod:
                    self.route()
                self.assertEqual(order, ['probe', 'visibility', 'consent', 'execute', 'fresh',
                                         'version', 'properties', 'account', 'authenticate', 'resolve'])
                self.assert_ensure_callbacks()
                self.assertEqual(self.modules['xbmcaddon'].Addon.call_args_list,
                                 [call(), call('inputstream.adaptive'), call('inputstream.adaptive')])
                self.modules['xbmc'].getCondVisibility.assert_called_once_with(
                    'System.HasAddon(inputstream.adaptive)')
                self.dialog.yesno.assert_called_once()
                self.modules['xbmc'].executebuiltin.assert_called_once_with(command, wait=True)
                self.isa.getAddonInfo.assert_called_once_with('version')
                self.auth.assert_called_once_with(self.store.return_value, 'fixture-username', 'fixture-password')
                self.client.resolve.assert_called_once_with('channel', 'fixture')
                self.guard.assert_called_once()
                self.modules['xbmcgui'].ListItem.assert_called_once_with(path=ROOT)
                item = self.modules['xbmcgui'].ListItem.return_value
                self.assertEqual(dict(invocation.args for invocation in item.setProperty.call_args_list),
                                 {**PROPERTIES, 'inputstream.adaptive.manifest_type': 'hls'})
                self.modules['xbmcplugin'].setResolvedUrl.assert_called_once_with(1, True, item)
                self.modules['xbmcplugin'].endOfDirectory.assert_not_called()
                self.dialog.ok.assert_not_called()
                vod.assert_not_called()
                self.assert_private()

    def test_native_cancel_after_consent_resolves_false_once_without_account_or_chain(self):
        for installed in [False, True]:
            with self.subTest(installed=installed):
                self.reset_calls()
                self.modules['xbmcaddon'].Addon.side_effect = [
                    self.addon, RuntimeError('SYNTHETIC_PRIVATE'), RuntimeError('SYNTHETIC_PRIVATE')]
                self.modules['xbmc'].getCondVisibility.return_value = installed
                self.dialog.yesno.return_value = True
                self.modules['xbmc'].executebuiltin.return_value = 0
                self.route()
                self.assert_ensure_callbacks()
                self.assert_no_account_or_api()
                self.assertEqual(self.modules['xbmcaddon'].Addon.call_args_list,
                                 [call(), call('inputstream.adaptive'), call('inputstream.adaptive')])
                self.modules['xbmc'].getCondVisibility.assert_called_once_with(
                    'System.HasAddon(inputstream.adaptive)')
                self.dialog.yesno.assert_called_once()
                self.properties.assert_not_called()
                self.guard.assert_not_called()
                command = ('EnableAddon' if installed else 'InstallAddon') + '(inputstream.adaptive)'
                self.assert_failed_once(live_playback.INPUTSTREAM_ERROR, setup_command=command)

    def test_known_username_and_password_are_refused_before_listitem_handoff(self):
        for credential in ['fixture-username', 'fixture-password']:
            with self.subTest(credential_kind='username' if credential.endswith('username') else 'password'):
                self.reset_calls()
                self.client.resolve.return_value = BASE + '?token=prefix' + quote(credential, safe='') + 'suffix'
                self.route()
                self.client.resolve.assert_called_once_with('channel', 'fixture')
                self.assert_failed_once()

    def test_plugin_rechecks_root_even_when_resolver_returns_unsafe_url(self):
        for url in [ROOT.replace('https:', 'http:'), ROOT.replace('cdn-uw2-prod.tsv2.amagi.tv', 'fixture.invalid'),
                    ROOT + '&refresh_token=SYNTHETIC_PRIVATE', ROOT + '%7CCookie=SYNTHETIC_PRIVATE']:
            with self.subTest(case=urlsplit(url).scheme):
                self.reset_calls()
                self.client.resolve.return_value = url
                self.route()
                self.assert_failed_once()

    def test_auth_and_stream_failures_resolve_false_once_with_sanitized_details(self):
        for stage in ['auth', 'resolve']:
            with self.subTest(stage=stage):
                self.reset_calls()
                error = service.AuthenticationError('Signed out.') if stage == 'auth' else ValueError(ROOT)
                self.auth.side_effect = error if stage == 'auth' else None
                self.client.resolve.side_effect = error if stage == 'resolve' else None
                self.route()
                self.assert_failed_once('Signed out.' if stage == 'auth' else 'label-30009')
                if stage == 'auth':
                    self.client.resolve.assert_not_called()

    def test_root_is_offline_and_never_checks_live_flag_or_isa(self):
        self.route('root')
        self.assert_isa_untouched()
        self.modules['xbmc'].executebuiltin.assert_not_called()
        self.modules['xbmcaddon'].Addon.assert_called_once_with()
        self.addon.getSettingBool.assert_not_called()
        self.properties.assert_not_called()
        self.guard.assert_not_called()
        self.assert_no_account_or_api()
        self.assertEqual(self.modules['xbmcplugin'].addDirectoryItem.call_count, 4)
        self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(1, succeeded=True, cacheToDisc=False)
        self.modules['xbmcplugin'].setResolvedUrl.assert_not_called()

    def test_account_actions_never_check_live_flag_or_isa(self):
        for action in ['settings', 'login', 'logout']:
            with self.subTest(action=action):
                self.reset_calls()
                self.route(action)
                self.assert_isa_untouched()
                self.modules['xbmc'].executebuiltin.assert_called_once_with(
                    'Container.Update(plugin://fixture/,replace)')
                self.modules['xbmcaddon'].Addon.assert_called_once_with()
                self.addon.getSettingBool.assert_not_called()
                self.properties.assert_not_called()
                self.guard.assert_not_called()
                self.isa.getAddonInfo.assert_not_called()
                self.modules['xbmcplugin'].setResolvedUrl.assert_not_called()
                self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(1, succeeded=True, cacheToDisc=False)

    def test_vod_stays_native_without_live_flag_isa_or_live_validation(self):
        vod_url = 'https://fixture.invalid/vod/master.m3u8'
        self.client.resolve.return_value = vod_url
        self.addon.getSettingBool.side_effect = AssertionError('VOD must not read the live setting.')
        for kind in ['episode', 'movie', 'clip']:
            with self.subTest(kind=kind):
                self.reset_calls()
                self.route(kind=kind)
                self.assert_isa_untouched()
                self.modules['xbmc'].executebuiltin.assert_not_called()
                self.modules['xbmcaddon'].Addon.assert_called_once_with()
                self.addon.getSettingBool.assert_not_called()
                self.properties.assert_not_called()
                self.guard.assert_not_called()
                self.modules['xbmcgui'].ListItem.assert_called_once_with(path=vod_url + '|' + PUBLIC_HEADERS)
                item = self.modules['xbmcgui'].ListItem.return_value
                item.setProperty.assert_not_called()
                item.setMimeType.assert_called_once_with('application/vnd.apple.mpegurl')
                item.setContentLookup.assert_called_once_with(False)
                self.modules['xbmcplugin'].setResolvedUrl.assert_called_once_with(1, True, item)
                self.modules['xbmcplugin'].endOfDirectory.assert_not_called()

    def test_catalogue_keeps_live_entries_visible_without_live_flag_or_isa(self):
        self.addon.getSettingBool.return_value = False
        self.factory.return_value.playlist.return_value = {
            'items': [{'id': 'fixture', 'type': 'channel', 'label': 'Synthetic Live'}],
            'previous_offset': None, 'next_offset': None}
        self.route('playlist', playlist='synthetic')
        self.assert_isa_untouched()
        self.modules['xbmc'].executebuiltin.assert_not_called()
        self.modules['xbmcaddon'].Addon.assert_called_once_with()
        self.addon.getSettingBool.assert_not_called()
        self.properties.assert_not_called()
        self.guard.assert_not_called()
        self.addon.getSetting.assert_not_called()
        self.store.assert_not_called()
        self.auth.assert_not_called()
        self.modules['xbmcplugin'].addDirectoryItem.assert_called_once()
        invocation = self.modules['xbmcplugin'].addDirectoryItem.call_args
        self.assertFalse(invocation.kwargs['isFolder'])
        self.assertEqual(parse_qs(urlsplit(invocation.args[1]).query), {
            'action': ['play'], 'kind': ['channel'], 'asset': ['fixture']})
        self.modules['xbmcgui'].ListItem.return_value.setProperty.assert_called_once_with('IsPlayable', 'true')
        self.modules['xbmcplugin'].setResolvedUrl.assert_not_called()


if __name__ == '__main__':
    unittest.main()
