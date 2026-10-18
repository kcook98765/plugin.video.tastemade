"""Allowlisted failure metadata only. Never format exception strings/payloads."""
from contextlib import contextmanager

STAGES = frozenset({
    'bootstrap.bundle', 'bootstrap.config', 'request.http', 'request.redirect',
    'response.json', 'catalog.menus', 'catalog.page', 'catalog.playlist',
    'catalog.episodes', 'request.other', 'auth.request', 'auth.refresh',
    'resolve.asset', 'resolve.editions', 'resolve.stream', 'resolve.vod',
    'resolve.channel', 'resolve.edition_policy', 'resolve.indirect',
    'manifest.check', 'manifest.url_policy', 'manifest.reference_policy',
    'manifest.format', 'manifest.encryption', 'manifest.depth',
    'manifest.audio_group', 'manifest.graph_limit',
    'live.url_policy', 'live.inputstream',
    'directory.root', 'directory.browse', 'directory.page', 'directory.playlist',
    'directory.episodes', 'directory.action', 'directory.other', 'playback.resolve',
    'directory.seasons', 'directory.season_episodes',
    'directory.live',
    'unknown',
})
CATEGORIES = frozenset({'service', 'authentication', 'entitlement', 'region',
                        'network', 'unsupported_stream', 'unavailable', 'unexpected'})
EXCEPTIONS = frozenset({
    'ServiceError', 'AuthenticationError', 'EntitlementError', 'RegionError',
    'NetworkError', 'UnsupportedStreamError', 'UnavailableError', 'HTTPFailure',
    'HTTPError', 'URLError', 'TimeoutError', 'OSError', 'ConnectionError',
    'ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError',
    'UnicodeDecodeError', 'JSONDecodeError', 'SyntaxError', 'AssertionError',
})
_sink = None


def configure(sink=None):
    global _sink
    _sink = sink


def _safe_attr(value, name, default=None):
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def report(stage, error, status=None, category=None):
    """Unknown strings/classes collapse to fixed values, even if malicious."""
    stage = stage if isinstance(stage, str) and stage in STAGES else 'unknown'
    if category is None:
        category = _safe_attr(error, 'category', 'unexpected')
    category = category if isinstance(category, str) and category in CATEGORIES else 'unexpected'
    name = type(error).__name__
    name = name if name in EXCEPTIONS else 'OtherError'
    if status is None:
        status = _safe_attr(error, 'status', _safe_attr(error, 'code'))
    bounded = type(status) is int and 100 <= status <= 599
    status_text = str(status) if bounded else 'none'
    line = 'Tastemade diagnostic stage={} category={} http_status={} exception={}'.format(
        stage, category, status_text, name)
    if _sink is not None:
        try:
            _sink(line)
        except Exception:
            # A logger failure must not change resolution/directory callbacks.
            pass
    return line


@contextmanager
def diagnostic_stage(stage):
    try:
        yield
    except Exception as error:
        report(stage, error)
        raise


def request_stage(path):
    if path == '/menus':
        return 'catalog.menus'
    if path.startswith('/pages/'):
        return 'catalog.page'
    if path.startswith('/playlists/'):
        return 'catalog.playlist'
    if path.endswith('/episodes'):
        return 'catalog.episodes'
    if path.endswith('/editions'):
        return 'resolve.editions'
    if path.endswith('/stream'):
        return 'resolve.stream'
    if path.startswith('/media/'):
        return 'resolve.asset'
    if path == '/user/refresh-token':
        return 'auth.refresh'
    if path.startswith('/user'):
        return 'auth.request'
    return 'request.other'


def directory_stage(action):
    if action == 'play':
        return 'playback.resolve'
    if action in ('settings', 'login', 'logout'):
        return 'directory.action'
    return {'root': 'directory.root', 'browse': 'directory.browse',
            'page': 'directory.page', 'playlist': 'directory.playlist',
            'episodes': 'directory.episodes', 'seasons': 'directory.seasons',
            'season_episodes': 'directory.season_episodes', 'live': 'directory.live'}.get(action, 'directory.other')
