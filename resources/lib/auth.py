"""Private per-profile session persistence, never logging secrets.

No password/email duplication. Salted credential binding invalidates old
sessions when either setting changes. Permissions are privacy, not encryption.
Only server 401 triggers refresh; connection failures do not erase sessions.
"""
import hashlib
import hmac
import json
import os
import sys
import uuid
from contextlib import contextmanager
from copy import copy

from service import AuthenticationError, Client, ServiceError


class SessionStore:
    def __init__(self, profile):
        self.directory = os.path.join(profile, 'auth')
        self.path = os.path.join(self.directory, 'session.json')
        self.record = {}
        self._interactive = False

    @contextmanager
    def _locked(self):
        """Serialize read/check/replace across Kodi invocations, not network I/O.

        Keep the lock file: unlinking it would let another process lock a new
        inode while an existing writer still owns the old one. OS locks are
        released when an invocation exits, including after a crash.
        """
        lock_path = os.path.join(self.directory, 'session.lock')
        try:
            if any(os.path.islink(path) for path in (self.directory, self.path, lock_path)):
                raise ServiceError('Private session storage must not use symbolic links.')
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
            os.chmod(self.directory, 0o700)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
            with os.fdopen(os.open(lock_path, flags, 0o600), 'r+b') as lock:
                if sys.platform == 'win32':
                    import msvcrt
                    # Byte-range locks may extend beyond EOF. Do not initialize
                    # the byte before locking: another invocation may own it.
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if sys.platform == 'win32':
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except OSError:
            raise ServiceError('Private session storage is unavailable. Check the add-on profile permissions.') from None

    def _read(self):
        try:
            with open(self.path, encoding='utf-8') as stream:
                raw = stream.read(65537)
            os.chmod(self.path, 0o600)
            record = json.loads(raw)
            if len(raw) > 65536 or not isinstance(record, dict) or record.get('schema') != 1:
                raise ValueError()
            return record
        except (FileNotFoundError, ValueError, TypeError):
            return {}

    def _binding(self, username, password, salt):
        value = json.dumps([username, password], ensure_ascii=False).encode('utf-8')
        return hashlib.pbkdf2_hmac('sha256', value, bytes.fromhex(salt), 100000).hex()

    def bind(self, username, password):
        with self._locked():
            record = self._read()
            try:
                valid = hmac.compare_digest(record['binding'], self._binding(username, password, record['salt']))
                valid = valid and isinstance(record.get('device'), str) and bool(record['device'])
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                salt = os.urandom(32).hex()
                record = {'schema': 1, 'salt': salt,
                          'binding': self._binding(username, password, salt),
                          'device': str(uuid.uuid4()), 'signed_out': False}
            if not valid or not isinstance(record.get('generation'), str) or not record['generation']:
                record['generation'] = str(uuid.uuid4())
                self._write(record)
            self.record = record
            self._interactive = False
            return self

    def _write(self, record):
        # Caller owns the profile lock. Publish memory only after replacement.
        temporary = self.path + '.' + str(uuid.uuid4())
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise ServiceError('Could not save the private viewing session.') from None
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def _current(self):
        current = self._read()
        generation = self.record.get('generation')
        if not generation or current.get('generation') != generation:
            raise AuthenticationError('The viewing session changed. Choose Verify login to try again.')
        return current

    def check(self):
        with self._locked():
            self._current()

    def save(self):
        with self._locked():
            self._current()
            record = dict(self.record, generation=str(uuid.uuid4()))
            self._write(record)
            self.record = record

    def for_client(self, interactive=False):
        # A callback must keep its own generation even if the caller rebinds or
        # logs out using the original store object while a request is in flight.
        writer = copy(self)
        writer.record = dict(self.record)
        writer._interactive = interactive
        return writer

    def token(self, value):
        if not isinstance(value, str) or not value:
            raise AuthenticationError('The service did not return a usable viewing session.')
        with self._locked():
            current = self._current()
            if current.get('signed_out') and not self._interactive:
                raise AuthenticationError('Signed out on this Kodi profile. Choose Verify login to sign in again.')
            record = dict(current, token=value, signed_out=False, generation=str(uuid.uuid4()))
            self._write(record)
            self.record = record

    def invalidate(self, signed_out=False):
        with self._locked():
            record = self._current()
            record.pop('token', None)
            record.update(signed_out=signed_out, generation=str(uuid.uuid4()))
            self._write(record)
            self.record = record

    def logout(self):
        # Official client logout(false) also removes its local token only.
        # This is not a claim that other devices/server sessions are revoked.
        with self._locked():
            # Logout is an explicit action against the latest session. An old
            # refresh result, in contrast, must never invalidate a newer login.
            record = self._read()
            if not record:
                raise ServiceError('Private session storage is unavailable. Check the add-on profile permissions.')
            record.pop('token', None)
            record.update(signed_out=True, generation=str(uuid.uuid4()))
            self._write(record)
            self.record = record
            self._interactive = False


def authenticated_client(store, username, password, interactive=False, factory=Client):
    store.bind(username, password)
    if store.record.get('signed_out') and not interactive:
        raise AuthenticationError('Signed out on this Kodi profile. Choose Verify login to sign in again.')
    was_signed_out = bool(store.record.get('signed_out'))
    store = store.for_client(interactive)
    client = factory(device_id=store.record['device'])
    cached = store.record.get('token')
    if isinstance(cached, str) and cached:
        # Loading a cached bearer is not a session mutation. A stale invocation
        # must not write it over a refresh completed by another invocation.
        client.set_token(cached)
    client.on_token = store.token
    if isinstance(cached, str) and cached:
        try:
            client.get('/user')
            store.check()
            return client, 'refreshed' if client.refreshed else 'reused'
        except AuthenticationError:
            store.invalidate(signed_out=True)
            if not interactive:
                raise
    try:
        client.login(username, password)
    except AuthenticationError:
        store.invalidate(signed_out=was_signed_out or bool(cached))
        raise
    store.check()
    return client, 'signed_in'
