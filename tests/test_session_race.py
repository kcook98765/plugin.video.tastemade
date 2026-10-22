"""Deterministic session interleavings; synthetic accounts and no network."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'resources' / 'lib'))
import auth
import service
from test_hardening import FakeClient


def delayed_process_writer(profile, ready, resume, result):
    """Separate invocation captures a record before its parent logs out."""
    try:
        store = auth.SessionStore(profile).bind('fixture-user', 'fixture-password')
        ready.set()
        if not resume.wait(10):
            raise RuntimeError('Test synchronization timed out.')
        store.token('synthetic-child')
        result.put('accepted')
    except Exception as error:
        result.put(type(error).__name__)


class SessionRaceTests(unittest.TestCase):
    def setUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix='tm-race-')
        self.addCleanup(self.profile.cleanup)
        self.seed = self.store()
        self.seed.token('synthetic-original')

    def store(self):
        return auth.SessionStore(self.profile.name).bind('fixture-user', 'fixture-password')

    def read(self):
        return json.loads(Path(self.seed.path).read_text())

    def reject_stale(self, operation):
        try:
            operation()
        except service.AuthenticationError:
            pass

    def assert_signed_out(self):
        self.assertTrue(self.read()['signed_out'])
        self.assertNotIn('token', self.read())

    def test_audit_late_token_cannot_undo_logout(self):
        delayed = self.store()
        self.store().logout()
        self.reject_stale(lambda: delayed.token('synthetic-late'))
        self.assert_signed_out()

    def test_captured_callback_cannot_undo_same_store_logout(self):
        store = self.store()
        client, _ = auth.authenticated_client(store, 'fixture-user', 'fixture-password', factory=FakeClient)
        store.logout()
        self.reject_stale(lambda: client.set_token('synthetic-late'))
        self.assert_signed_out()

    def test_logout_during_refresh_cannot_restore_session(self):
        owner = self
        class Refresh(FakeClient):
            def get(self, path):
                owner.store().logout()
                self.set_token('synthetic-refreshed')
                return {}
        self.reject_stale(lambda: auth.authenticated_client(
            self.store(), 'fixture-user', 'fixture-password', interactive=True, factory=Refresh))
        self.assert_signed_out()

    def service_client(self, device_id=None):
        client = object.__new__(service.Client)
        client.headers = {}
        client.on_token = None
        client.refreshed = False
        return client

    def test_actual_401_refresh_response_after_logout_is_rejected_before_retry(self):
        def refresh(url, headers, body=None, method=None):
            if url.endswith('/user/refresh-token'):
                self.store().logout()
                return {'token': 'synthetic-delayed-refresh'}
            raise service.HTTPFailure(401)
        with patch.object(service, 'json_request', side_effect=refresh) as request:
            with self.assertRaises(service.AuthenticationError):
                auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=self.service_client)
        self.assertEqual(request.call_count, 2)
        self.assert_signed_out()

    def test_sequential_service_refreshes_advance_callback_generation(self):
        responses = [service.HTTPFailure(401), {'token': 'synthetic-refresh-one'}, {},
                     service.HTTPFailure(401), {'token': 'synthetic-refresh-two'}, {}]
        with patch.object(service, 'json_request', side_effect=responses) as request:
            client, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password',
                                                     factory=self.service_client)
            self.assertEqual(state, 'refreshed')
            client.get('/user')
        self.assertEqual(request.call_count, 6)
        self.assertEqual(self.read()['token'], 'synthetic-refresh-two')

    def test_late_auth_failure_cannot_clear_fresh_login(self):
        owner = self
        class Expired(FakeClient):
            def get(self, path):
                owner.store().logout()
                auth.authenticated_client(owner.store(), 'fixture-user', 'fixture-password',
                                          interactive=True, factory=FakeClient)
                raise service.AuthenticationError('Synthetic expiry.')
        self.reject_stale(lambda: auth.authenticated_client(
            self.store(), 'fixture-user', 'fixture-password', factory=Expired))
        self.assertFalse(self.read()['signed_out'])
        self.assertEqual(self.read().get('token'), 'synthetic-session')

    def test_older_writer_cannot_replace_newer_token(self):
        first, second = self.store(), self.store()
        first.token('synthetic-newer')
        self.reject_stale(lambda: second.token('synthetic-older'))
        self.assertEqual(self.read()['token'], 'synthetic-newer')

    def test_independent_process_cannot_restore_session(self):
        context = multiprocessing.get_context('spawn')
        ready, resume, result = context.Event(), context.Event(), context.Queue()
        child = context.Process(target=delayed_process_writer,
                                args=(self.profile.name, ready, resume, result))
        child.start()
        try:
            self.assertTrue(ready.wait(10))
            self.store().logout()
            resume.set()
            self.assertEqual(result.get(timeout=10), 'AuthenticationError')
            child.join(10)
            self.assertEqual(child.exitcode, 0)
            self.assert_signed_out()
        finally:
            resume.set()
            if child.is_alive():
                child.terminate()
                child.join(10)
            result.close()
            result.join_thread()

    def test_logout_waits_for_in_flight_atomic_write_then_invalidates_it(self):
        writer, logout = self.store(), self.store()
        replacing, release, logout_attempt = threading.Event(), threading.Event(), threading.Event()
        errors = []
        real_replace = os.replace
        real_locked = logout._locked

        def replace(source, destination):
            if threading.current_thread().name == 'session-writer':
                replacing.set()
                if not release.wait(10):
                    raise RuntimeError('Test synchronization timed out.')
            return real_replace(source, destination)

        def locked():
            logout_attempt.set()
            return real_locked()

        def run(operation):
            try:
                operation()
            except Exception as error:
                errors.append(type(error).__name__)

        writing = threading.Thread(name='session-writer', target=run,
                                   args=(lambda: writer.token('synthetic-in-flight'),))
        logging_out = threading.Thread(target=run, args=(logout.logout,))
        with patch.object(auth.os, 'replace', side_effect=replace), patch.object(logout, '_locked', side_effect=locked):
            writing.start()
            try:
                self.assertTrue(replacing.wait(10))
                logging_out.start()
                self.assertTrue(logout_attempt.wait(10))
            finally:
                release.set()
                writing.join(10)
                if logging_out.ident is not None:
                    logging_out.join(10)
        self.assertFalse(writing.is_alive())
        self.assertFalse(logging_out.is_alive())
        self.assertEqual(errors, [])
        self.assert_signed_out()
        with self.assertRaises(service.AuthenticationError):
            writer.token('synthetic-late')

    def test_concurrent_persistence_has_one_winner(self):
        writers = [self.store() for _ in range(4)]
        barrier = threading.Barrier(len(writers))
        results = []

        def write(store, number):
            try:
                barrier.wait(timeout=10)
                store.token('synthetic-concurrent-{}'.format(number))
                results.append('accepted')
            except Exception as error:
                results.append(type(error).__name__)

        threads = [threading.Thread(target=write, args=(store, i)) for i, store in enumerate(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ['accepted'] + ['AuthenticationError'] * 3)
        self.assertTrue(self.read()['token'].startswith('synthetic-concurrent-'))

    def test_cached_reuse_does_not_write_session(self):
        before = Path(self.seed.path).read_bytes()
        with patch.object(auth.os, 'replace', side_effect=AssertionError('Reuse must not persist.')):
            client, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=FakeClient)
        self.assertEqual((state, client.login_calls), ('reused', 0))
        self.assertEqual(Path(self.seed.path).read_bytes(), before)

    def test_logout_during_cached_validation_does_not_report_success(self):
        owner = self
        class Validating(FakeClient):
            def get(self, path):
                owner.store().logout()
                return {}
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=Validating)
        self.assert_signed_out()

    def test_logout_during_login_requires_another_explicit_login(self):
        self.store().logout()
        owner = self
        class Login(FakeClient):
            def login(self, username, password):
                owner.store().logout()
                super().login(username, password)
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', interactive=True, factory=Login)
        self.assert_signed_out()
        _, state = auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password',
                                             interactive=True, factory=FakeClient)
        self.assertEqual(state, 'signed_in')

    def test_failed_login_after_token_keeps_explicit_signout(self):
        self.store().logout()
        class Rejected(FakeClient):
            def login(self, username, password):
                self.set_token('synthetic-unverified')
                raise service.AuthenticationError('Synthetic rejection.')
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', interactive=True, factory=Rejected)
        self.assert_signed_out()
        factory = MagicMock()
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=factory)
        factory.assert_not_called()

    def test_expired_session_blocks_later_silent_login(self):
        class Expired(FakeClient):
            def get(self, path):
                raise service.AuthenticationError('Synthetic expiry.')
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=Expired)
        self.assert_signed_out()
        factory = MagicMock()
        with self.assertRaises(service.AuthenticationError):
            auth.authenticated_client(self.store(), 'fixture-user', 'fixture-password', factory=factory)
        factory.assert_not_called()

    def test_invalid_token_does_not_mutate_session(self):
        for token in (None, '', {}, 4):
            with self.subTest(kind=type(token).__name__):
                before = self.read()
                with self.assertRaises(service.AuthenticationError):
                    self.store().token(token)
                self.assertEqual(self.read(), before)

    def test_failed_replace_or_fsync_is_atomic_private_and_retryable(self):
        for operation in ('replace', 'fsync'):
            with self.subTest(operation=operation):
                store = self.store()
                before = self.read()
                with patch.object(auth.os, operation, side_effect=OSError('synthetic-secret')):
                    try:
                        store.token('synthetic-sensitive-token')
                    except service.ServiceError as error:
                        # Public message and traceback must suppress raw OS text.
                        rendered = ''.join(traceback.format_exception(error))
                        self.assertNotIn('synthetic-secret', rendered)
                        self.assertNotIn('synthetic-sensitive-token', str(error))
                    else:
                        self.fail('Expected a sanitized storage failure.')
                self.assertEqual(self.read(), before)
                self.assertEqual(store.record, before)
                self.assertEqual({path.name for path in Path(store.directory).iterdir()},
                                 {'session.json', 'session.lock'})
                store.token('synthetic-retry')
                self.assertEqual(self.read()['token'], 'synthetic-retry')

    def test_failed_logout_does_not_claim_or_publish_success(self):
        store = self.store()
        before = self.read()
        with patch.object(auth.os, 'replace', side_effect=OSError('synthetic-secret')):
            with self.assertRaises(service.ServiceError):
                store.logout()
        self.assertEqual(self.read(), before)
        store.logout()
        self.assert_signed_out()

    def test_lock_failure_is_sanitized_and_does_not_modify_session(self):
        before = self.read()
        with patch.object(auth.os, 'open', side_effect=OSError('synthetic-private-os-detail')):
            try:
                self.seed.token('synthetic-never-saved')
            except service.ServiceError as error:
                self.assertNotIn('synthetic-private-os-detail', ''.join(traceback.format_exception(error)))
            else:
                self.fail('Expected a sanitized storage failure.')
        self.assertEqual(self.read(), before)

    def test_repeated_logout_invalidates_even_recent_signed_out_writer(self):
        self.store().logout()
        delayed = self.store().for_client(interactive=True)
        self.store().logout()
        with self.assertRaises(service.AuthenticationError):
            delayed.token('synthetic-late-login')
        self.assert_signed_out()

    def test_account_change_rejects_old_token_and_invalidation(self):
        old = self.store()
        changed = auth.SessionStore(self.profile.name).bind('other-fixture-user', 'fixture-password')
        changed.token('synthetic-other-account')
        for operation in (lambda: old.token('synthetic-old-account'), old.invalidate, old.save):
            with self.assertRaises(service.AuthenticationError):
                operation()
        self.assertEqual(self.read()['token'], 'synthetic-other-account')

    def test_legacy_session_migration_preserves_reuse_and_signout(self):
        for signed_out in (False, True):
            with self.subTest(signed_out=signed_out):
                legacy = self.read()
                legacy.pop('generation')
                legacy['signed_out'] = signed_out
                if signed_out:
                    legacy.pop('token', None)
                Path(self.seed.path).write_text(json.dumps(legacy))
                current = self.store()
                self.assertTrue(current.record['generation'])
                self.assertEqual({k: v for k, v in current.record.items() if k != 'generation'}, legacy)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink fixture')
    def test_symlink_lock_refused(self):
        lock = Path(self.seed.directory) / 'session.lock'
        lock.unlink()
        lock.symlink_to(self.seed.path)
        with self.assertRaises(service.ServiceError):
            self.store()

    def test_windows_lock_uses_same_byte_for_acquire_and_release(self):
        windows = types.SimpleNamespace(locking=MagicMock(), LK_LOCK=1, LK_UNLCK=0)
        positions = []
        windows.locking.side_effect = lambda descriptor, mode, count: positions.append(
            (os.lseek(descriptor, 0, os.SEEK_CUR), mode, count))
        with patch.dict(sys.modules, {'msvcrt': windows}), patch.object(auth.sys, 'platform', 'win32'):
            with self.seed._locked():
                pass
        self.assertEqual(positions, [(0, windows.LK_LOCK, 1), (0, windows.LK_UNLCK, 1)])


if __name__ == '__main__':
    unittest.main()
