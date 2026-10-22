"""Offline synthetic fixtures only; no Kodi, network, account or profile access."""
import importlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import traceback
import types
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

LIB = Path(__file__).resolve().parents[1] / 'resources' / 'lib'
sys.path.insert(0, str(LIB))
import service
import auth


class FakeClient:
    def __init__(self, device_id=None):
        self.device_id = device_id
        self.on_token = None
        self.refreshed = False
        self.login_calls = 0

    def set_token(self, value):
        self.value = value
        if self.on_token:
            self.on_token(value)

    def login(self, username, password):
        self.login_calls += 1
        self.set_token('synthetic-session')

    def get(self, path):
        return {}


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tm-test-')
        self.addCleanup(self.temp.cleanup)

    def store(self):
        return auth.SessionStore(self.temp.name)

    def test_first_login_and_new_invocation_reuses_no_password_login(self):
        first, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=FakeClient)
        second, other = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=FakeClient)
        self.assertEqual((state, other), ('signed_in', 'reused'))
        self.assertEqual((first.login_calls, second.login_calls), (1, 0))
        self.assertEqual(first.device_id, second.device_id)

    def test_private_permissions_and_no_duplicate_credentials(self):
        store = self.store()
        auth.authenticated_client(store, 'fixture-user', 'fixture-password', factory=FakeClient)
        self.assertEqual(stat.S_IMODE(os.stat(store.directory).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(store.path).st_mode), 0o600)
        data = Path(store.path).read_text()
        self.assertNotIn('fixture-user', data)
        self.assertNotIn('fixture-password', data)
        lock = Path(store.directory) / 'session.lock'
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(set(Path(store.directory).iterdir()), {Path(store.path), lock})

    def test_email_and_password_changes_invalidate(self):
        for username, password in [('other-user', 'fixture-password'), ('fixture-user', 'other-password')]:
            with self.subTest(change=username):
                store = self.store().bind('fixture-user', 'fixture-password')
                store.token('synthetic-old-session')
                changed = self.store().bind(username, password)
                self.assertNotIn('token', changed.record)
                self.assertFalse(changed.record['signed_out'])

    def test_logout_survives_invocation_and_blocks_silent_signin(self):
        store = self.store().bind('fixture-user', 'fixture-password')
        store.token('synthetic-session')
        store.logout()
        factory = MagicMock()
        with self.assertRaises(auth.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=factory)
        factory.assert_not_called()
        client, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', interactive=True, factory=FakeClient)
        self.assertEqual(state, 'signed_in')
        self.assertEqual(client.login_calls, 1)

    def test_account_change_exits_signed_out_state_without_old_token(self):
        store = self.store().bind('fixture-user', 'fixture-password')
        store.logout()
        changed = self.store().bind('other-user', 'fixture-password')
        self.assertFalse(changed.record['signed_out'])
        self.assertNotIn('token', changed.record)

    def test_corrupt_cache_rebuilt_without_crash(self):
        store = self.store().bind('fixture-user', 'fixture-password')
        Path(store.path).write_text('{broken')
        self.assertNotIn('token', self.store().bind('fixture-user', 'fixture-password').record)

    def test_symlink_refused(self):
        store = self.store()
        os.symlink(self.temp.name, store.directory)
        with self.assertRaises(service.ServiceError):
            store.bind('fixture-user', 'fixture-password')

    def test_network_failure_retains_session_and_no_password_retry(self):
        self.store().bind('fixture-user', 'fixture-password').token('synthetic-session')
        class Broken(FakeClient):
            def get(self, path):
                raise service.NetworkError('Network unavailable.')
        with self.assertRaises(service.NetworkError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=Broken)
        self.assertEqual(self.store().bind('fixture-user', 'fixture-password').record['token'], 'synthetic-session')

    def test_expired_cache_removed_and_requires_explicit_signin(self):
        self.store().bind('fixture-user', 'fixture-password').token('synthetic-expired')
        class Expired(FakeClient):
            def get(self, path):
                raise service.AuthenticationError('Session expired.')
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=Expired)
        self.assertNotIn('token', self.store().bind('fixture-user', 'fixture-password').record)
        _, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', interactive=True, factory=Expired)
        self.assertEqual(state, 'signed_in')

    def test_refreshed_state_and_token_persist(self):
        self.store().bind('fixture-user', 'fixture-password').token('synthetic-old')
        class Refresh(FakeClient):
            def get(self, path):
                self.refreshed = True
                self.set_token('synthetic-new')
                return {}
        _, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=Refresh)
        self.assertEqual(state, 'refreshed')
        self.assertEqual(self.store().bind('fixture-user', 'fixture-password').record['token'], 'synthetic-new')


class ServiceTests(unittest.TestCase):
    def client(self):
        client = object.__new__(service.Client)
        client.headers = {'Authorization': 'Bearer synthetic-old'}
        client.on_token = None
        client.refreshed = False
        return client

    def test_401_refresh_uses_post_no_invented_body_and_retries_once(self):
        client = self.client()
        client.on_token = MagicMock()
        with patch.object(service, 'json_request', side_effect=[service.HTTPFailure(401), {'token': 'synthetic-new'}, {'ok': True}]) as request:
            self.assertEqual(client.get('/user'), {'ok': True})
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[1].args[0], service.API + '/user/refresh-token')
        self.assertEqual(request.call_args_list[1].kwargs, {'method': 'POST'})
        client.on_token.assert_called_once_with('synthetic-new')
        self.assertTrue(client.refreshed)

    def test_refresh_rejection_is_authentication_no_loop(self):
        with patch.object(service, 'json_request', side_effect=service.HTTPFailure(401)) as request:
            with self.assertRaises(service.AuthenticationError):
                self.client().get('/user')
        self.assertEqual(request.call_count, 2)

    def test_retry_401_not_refreshed_twice(self):
        with patch.object(service, 'json_request', side_effect=[service.HTTPFailure(401), {'token': 'synthetic-new'}, service.HTTPFailure(401)]) as request:
            with self.assertRaises(service.AuthenticationError):
                self.client().get('/user')
        self.assertEqual(request.call_count, 3)

    def test_403_not_guessed_as_password_or_region_or_refreshed(self):
        with patch.object(service, 'json_request', side_effect=service.HTTPFailure(403)) as request:
            with self.assertRaises(service.HTTPFailure) as result:
                self.client().get('/user')
        self.assertEqual(result.exception.category, 'service')
        self.assertEqual(request.call_count, 1)

    def test_explicit_blocker_mapping_and_no_untrusted_message(self):
        mapping = {'GEO': service.RegionError, 'AUTHENTICATION': service.AuthenticationError,
                   'SUBSCRIPTION': service.EntitlementError, 'PRODUCTS_MISMATCH_BLOCKED': service.EntitlementError,
                   'REQUIRES PURCHASE': service.EntitlementError, 'BLOCKED_WINDOW': service.UnavailableError}
        for reason, error in mapping.items():
            with self.subTest(reason=reason), self.assertRaises(error) as result:
                service.reject_blockers([{'reason': reason, 'message': 'SYNTHETIC-SENSITIVE-MARKER'}])
            self.assertNotIn('SYNTHETIC-SENSITIVE-MARKER', str(result.exception))

    def test_network_raw_errors_and_tracebacks_are_sanitized(self):
        for problem, expected in [(URLError('SYNTHETIC-SENSITIVE-MARKER'), service.NetworkError),
                                  (HTTPError('https://fixture.invalid/?private=SYNTHETIC-SENSITIVE-MARKER', 503, 'SYNTHETIC-SENSITIVE-MARKER', {}, None), service.NetworkError)]:
            opener = MagicMock()
            opener.open.side_effect = problem
            with patch.object(service, 'build_opener', return_value=opener), self.assertRaises(expected) as result:
                service.fetch('https://fixture.invalid/')
            self.assertNotIn('SYNTHETIC-SENSITIVE-MARKER', ''.join(traceback.format_exception(result.exception)))

    def test_menu_dedup_preserves_different_references(self):
        client = self.client()
        client.get = MagicMock(return_value=[{'items': [
            {'type': 'page', 'reference': 'a', 'label': 'Home'},
            {'type': 'page', 'reference': 'a', 'label': 'Home'},
            {'type': 'page', 'reference': 'b', 'label': 'Home'}]}])
        self.assertEqual([m['reference'] for m in client.menus()], ['a', 'b'])

    def test_clear_hls_unchanged_master_media_and_secret_refusal(self):
        master = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nmedia.m3u8\n'
        media = b'#EXTM3U\n#EXTINF:10,\nsegment.ts\n#EXT-X-ENDLIST\n'
        with patch.object(service, 'fetch', side_effect=[master, media]):
            self.assertEqual(service.checked_media_playlist('https://fixture.invalid/master.m3u8'), 'https://fixture.invalid/media.m3u8')
        for url in ['http://fixture.invalid/a', 'https://fixture.invalid/a?private=fixture', 'https://user:fixture@fixture.invalid/a']:
            with self.subTest(url=url), self.assertRaises(service.UnsupportedStreamError):
                service.checked_media_playlist(url)
        for playlist in [b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128\n', b'#EXTM3U\n#EXTINF:10,\ns.ts?private=fixture\n']:
            with patch.object(service, 'fetch', return_value=playlist), self.assertRaises(service.UnsupportedStreamError):
                service.checked_media_playlist('https://fixture.invalid/a')

    def test_blocked_edition_skipped_preserving_working_stream_path(self):
        client = self.client()
        client.get = MagicMock(side_effect=[{}, [
            {'id': 'blocked', 'editionType': 'full', 'blocked': [{'reason': 'GEO'}]},
            {'id': 'allowed', 'editionType': 'full', 'streams': [{'type': 'hls', 'drm': 'unencrypted'}]}],
            {'drm': 'unencrypted', 'url': 'https://fixture.invalid/a.m3u8'}])
        with patch.object(service, 'checked_media_playlist', return_value='safe-result') as checked:
            self.assertEqual(client.resolve('episode', 'fixture'), 'safe-result')
        self.assertEqual(client.get.call_args_list[2].args[1]['editionId'], 'allowed')
        checked.assert_called_once()


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.modules = {name: types.ModuleType(name) for name in ['xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcplugin', 'xbmcvfs']}
        self.modules['xbmc'].executebuiltin = MagicMock()
        self.addon = MagicMock()
        self.addon.getAddonInfo.side_effect = lambda name: '/tmp/unused-profile' if name == 'profile' else 'Fixture'
        self.addon.getSetting.side_effect = lambda name: 'fixture-' + name
        self.addon.getLocalizedString.side_effect = lambda number: 'label-' + str(number)
        self.modules['xbmcaddon'].Addon = MagicMock(return_value=self.addon)
        self.dialog = MagicMock()
        self.modules['xbmcgui'].Dialog = MagicMock(return_value=self.dialog)
        self.modules['xbmcgui'].ListItem = MagicMock()
        self.modules['xbmcplugin'].setContent = MagicMock()
        self.modules['xbmcplugin'].setPluginCategory = MagicMock()
        self.modules['xbmcplugin'].setPluginFanart = MagicMock()
        self.modules['xbmcplugin'].addDirectoryItem = MagicMock()
        self.modules['xbmcplugin'].endOfDirectory = MagicMock()
        self.modules['xbmcplugin'].setResolvedUrl = MagicMock()
        self.modules['xbmcvfs'].translatePath = lambda path: path
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        sys.modules.pop('plugin', None)
        self.plugin = importlib.import_module('plugin')

    def route(self, action):
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', '?action=' + action]):
            self.plugin.run()

    def test_root_is_offline_four_entries_no_account_reads(self):
        with patch.object(self.plugin, 'Client') as client, patch.object(self.plugin, 'SessionStore') as store:
            self.route('root')
        client.assert_not_called()
        store.assert_not_called()
        self.addon.getSetting.assert_not_called()
        self.assertEqual(self.modules['xbmcplugin'].addDirectoryItem.call_count, 4)

    def test_login_success_restores_root_without_reopening_action(self):
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', return_value=(None, 'reused')):
            self.route('login')
        self.assertIn('saved viewing session', self.dialog.ok.call_args.args[1])
        self.modules['xbmc'].executebuiltin.assert_called_once_with('Container.Update(plugin://fixture/,replace)')
        self.addon.openSettings.assert_not_called()

    def test_login_error_still_restores_root_sanitized(self):
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', side_effect=service.NetworkError('Network unavailable.')):
            self.route('login')
        self.assertEqual(self.dialog.ok.call_args.args[1], 'Network unavailable.')
        self.modules['xbmc'].executebuiltin.assert_called_once_with('Container.Update(plugin://fixture/,replace)')

    def test_settings_closes_then_checks_binding_then_root(self):
        with patch.object(self.plugin, 'SessionStore') as store:
            self.route('settings')
        self.addon.openSettings.assert_called_once()
        store.return_value.bind.assert_called_once_with('fixture-username', 'fixture-password')
        self.modules['xbmc'].executebuiltin.assert_called_once_with('Container.Update(plugin://fixture/,replace)')

    def test_logout_no_network_and_restores_root(self):
        with patch.object(self.plugin, 'SessionStore') as store, patch.object(self.plugin, 'Client') as client:
            self.route('logout')
        store.return_value.bind.return_value.logout.assert_called_once()
        client.assert_not_called()
        self.modules['xbmc'].executebuiltin.assert_called_once()

    def test_playback_error_stays_in_listing_resolves_false(self):
        with patch.object(self.plugin, 'SessionStore'), patch.object(self.plugin, 'authenticated_client', side_effect=service.AuthenticationError('Signed out.')):
            self.route('play')
        self.modules['xbmc'].executebuiltin.assert_not_called()
        self.assertFalse(self.modules['xbmcplugin'].setResolvedUrl.call_args.args[1])

    def test_unknown_exception_is_generic_no_raw_marker(self):
        with patch.object(self.plugin, 'Client', side_effect=RuntimeError('SYNTHETIC-SENSITIVE-MARKER')):
            self.route('browse')
        self.assertEqual(self.dialog.ok.call_args.args[1], 'label-30009')


if __name__ == '__main__':
    unittest.main()
