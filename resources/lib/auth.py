"""Private per-profile session persistence, never logging secrets.

No password/email duplication. Salted credential binding invalidates old
sessions when either setting changes. Permissions are privacy, not encryption.
Only server 401 triggers refresh; connection failures do not erase sessions.
"""
import hashlib
import hmac
import json
import os
import uuid

from service import AuthenticationError, Client, ServiceError


class SessionStore:
    def __init__(self, profile):
        self.directory = os.path.join(profile, 'auth')
        self.path = os.path.join(self.directory, 'session.json')
        self.record = {}

    def _binding(self, username, password, salt):
        value = json.dumps([username, password], ensure_ascii=False).encode('utf-8')
        return hashlib.pbkdf2_hmac('sha256', value, bytes.fromhex(salt), 100000).hex()

    def bind(self, username, password):
        try:
            if os.path.islink(self.directory) or os.path.islink(self.path):
                raise ServiceError('Private session storage must not use symbolic links.')
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
            os.chmod(self.directory, 0o700)
            try:
                with open(self.path, encoding='utf-8') as stream:
                    raw = stream.read(65537)
                os.chmod(self.path, 0o600)
                if len(raw) > 65536:
                    raise ValueError()
                record = json.loads(raw)
                if not isinstance(record, dict) or record.get('schema') != 1:
                    raise ValueError()
                valid = hmac.compare_digest(record['binding'], self._binding(username, password, record['salt']))
                valid = valid and isinstance(record.get('device'), str) and bool(record['device'])
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                record, valid = {}, False
            if not valid:
                salt = os.urandom(32).hex()
                record = {'schema': 1, 'salt': salt,
                          'binding': self._binding(username, password, salt),
                          'device': str(uuid.uuid4()), 'signed_out': False}
            self.record = record
            if not valid:
                self.save()
            return self
        except OSError:
            raise ServiceError('Private session storage is unavailable. Check the add-on profile permissions.') from None

    def save(self):
        temporary = self.path + '.' + str(uuid.uuid4())
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(self.record, stream)
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

    def token(self, value):
        self.record['token'] = value
        self.record['signed_out'] = False
        self.save()

    def invalidate(self, signed_out=False):
        self.record.pop('token', None)
        self.record['signed_out'] = signed_out
        self.save()

    def logout(self):
        # Official client logout(false) also removes its local token only.
        # This is not a claim that other devices/server sessions are revoked.
        self.invalidate(signed_out=True)


def authenticated_client(store, username, password, interactive=False, factory=Client):
    store.bind(username, password)
    if store.record.get('signed_out') and not interactive:
        raise AuthenticationError('Signed out on this Kodi profile. Choose Verify login to sign in again.')
    client = factory(device_id=store.record['device'])
    client.on_token = store.token
    cached = store.record.get('token')
    if isinstance(cached, str) and cached:
        client.set_token(cached)
        try:
            client.get('/user')
            return client, 'refreshed' if client.refreshed else 'reused'
        except AuthenticationError:
            store.invalidate()
            if not interactive:
                raise
    try:
        client.login(username, password)
    except AuthenticationError:
        store.invalidate(signed_out=bool(store.record.get('signed_out')))
        raise
    return client, 'signed_in'
