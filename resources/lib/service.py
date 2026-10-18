"""Official web-client protocol; fixed safe errors, no response/URL logging."""
import ast
import json
import re
import uuid
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from diagnostics import diagnostic_stage, report, request_stage

APP = 'https://app.tastemade.com'
API = 'https://backstage-api.com'
GRAPHQL = 'https://gql.tastemadecdn.net/v1/graphql'
BUNDLE = APP + '/_next/static/chunks/79707.bd7603679c84782e.js'
MAX_BYTES = 12000000
PAGE_SIZE = 30
SERIES_INVENTORY_LIMIT = 300
MEDIA_USER_AGENT = 'Mozilla/5.0'
MAX_VOD_PLAYLISTS = 16
MAX_VOD_REFERENCES = 4096


class ServiceError(Exception):
    """Callers may display these fixed messages, never raw response objects."""
    category = 'service'


class AuthenticationError(ServiceError):
    category = 'authentication'


class EntitlementError(ServiceError):
    category = 'entitlement'


class RegionError(ServiceError):
    category = 'region'


class NetworkError(ServiceError):
    category = 'network'


class UnsupportedStreamError(ServiceError):
    category = 'unsupported_stream'


class UnavailableError(ServiceError):
    category = 'unavailable'


class HTTPFailure(ServiceError):
    def __init__(self, status):
        self.status = status
        super().__init__('Official service returned HTTP {}. No account or region cause was established.'.format(status))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        error = ServiceError('Redirect requires review; request stopped.')
        report('request.redirect', error, status=code)
        raise error


def fetch(url, headers=None, body=None, method=None):
    if urlsplit(url).scheme != 'https':
        raise UnsupportedStreamError('Only HTTPS is supported.')
    request_headers = {'User-Agent': MEDIA_USER_AGENT, 'Referer': APP + '/'}
    request_headers.update(headers or {})
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            payload = response.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise ServiceError('Response exceeded the safety limit.')
            return payload
    except HTTPError as error:
        report('request.http', error, status=error.code,
               category='network' if error.code == 429 or error.code >= 500 else 'service')
        if error.code == 429 or error.code >= 500:
            raise NetworkError('Service busy or temporarily unavailable. Try again later.') from None
        raise HTTPFailure(error.code) from None
    except (URLError, OSError, ValueError) as error:
        report('request.http', error, category='network')
        raise NetworkError('Network request failed. Check connectivity and try again later.') from None


def json_request(url, headers, body=None, method=None):
    try:
        payload = fetch(url, headers, body, method)
        return json.loads(payload) if payload else {}
    except (ValueError, UnicodeError) as error:
        report('response.json', error)
        raise ServiceError('Unexpected service response; no sensitive details recorded.') from None


def segment(value):
    return quote(str(value), safe='')


def _catalog_id(value):
    return ((isinstance(value, str) and bool(value.strip())) or
            (type(value) is int and value >= 0))


def page_offset(value):
    """Reject malformed/negative/oversized route input before any request."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ServiceError('Invalid catalog page. Return to the previous listing.')
    raw = str(value)
    if not raw.isascii() or not raw.isdigit() or len(raw) > 7 or int(raw) > 1000000:
        raise ServiceError('Invalid catalog page. Return to the previous listing.')
    return int(raw)


def catalog_page(response, offset):
    """Bounded lookahead handles episodes, whose API omits total/size/offset.

    Consume only displayed raw positions, not the lookahead item. A short or
    empty last page terminates naturally without an empty Next-page loop.
    """
    offset = page_offset(offset)
    if not isinstance(response, dict) or not isinstance(response.get('items'), list):
        raise ServiceError('Unexpected catalog page response. Return to the previous listing.')
    items = response['items']
    if len(items) > PAGE_SIZE + 1 or any(not isinstance(item, dict) for item in items):
        raise ServiceError('Unexpected catalog page size or items.')
    returned_offset = response.get('offset', offset)
    if isinstance(returned_offset, bool) or returned_offset != offset:
        raise ServiceError('The service returned a different catalog page. Return to the previous listing.')
    size = response.get('size', PAGE_SIZE + 1)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ServiceError('Unexpected catalog page size.')
    step = min(PAGE_SIZE, size)
    visible = items[:step]
    end = offset + len(visible)
    total = response.get('total')
    known_total = isinstance(total, int) and not isinstance(total, bool) and total >= 0
    more = bool(visible) and (len(items) > step or (known_total and end < total))
    return {'items': visible, 'offset': offset,
            'previous_offset': max(0, offset - step) if offset else None,
            'next_offset': end if more else None}


def manifest_restriction(stage, message) -> NoReturn:
    error = UnsupportedStreamError(message)
    report(stage, error)
    raise error


def checked_media_playlist(url, preserve_master=False):
    with diagnostic_stage('manifest.check'):
        if preserve_master:
            return _checked_vod_playlist(url)
        return _checked_media_playlist(url)


def _vod_reference(base, reference):
    """Same HTTPS/no-query policy, with protocol-option injection refused."""
    if not isinstance(reference, str) or not reference:
        manifest_restriction('manifest.format', 'A required HLS reference is missing.')
    decoded = unquote(reference)
    if any(ord(c) < 32 or ord(c) == 127 or c in '|\\' for c in decoded) or reference != reference.strip():
        manifest_restriction('manifest.reference_policy', 'Unsafe HLS reference syntax is not supported.')
    if '{$' in reference:
        manifest_restriction('manifest.reference_policy', 'Variable HLS references are not supported.')
    try:
        target = urljoin(base, reference) if base else reference
        parts = urlsplit(target)
        valid = parts.scheme == 'https' and bool(parts.hostname) and not (
            parts.query or parts.fragment or parts.username or parts.password)
    except (ValueError, TypeError):
        valid = False
        target = ''
    if not valid:
        manifest_restriction('manifest.url_policy', 'Token-bearing or non-HTTPS playback URLs are not supported.')
    return target


def _hls_attributes(line):
    raw = line.split(':', 1)[1]
    pattern = re.compile(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\s"]+)(?:,|$)')
    result = {}
    position = 0
    quoted = {'URI', 'GROUP-ID', 'NAME', 'AUDIO', 'VIDEO', 'SUBTITLES',
              'CODECS', 'LANGUAGE', 'ASSOC-LANGUAGE', 'CHANNELS'}
    while position < len(raw):
        match = pattern.match(raw, position)
        if not match or match.group(1) in result:
            manifest_restriction('manifest.format', 'Malformed HLS attributes are not supported.')
        key, value = match.group(1), match.group(2)
        if key in quoted and not value.startswith('"'):
            manifest_restriction('manifest.format', 'Malformed HLS string attributes are not supported.')
        result[key] = value[1:-1] if value.startswith('"') else value
        position = match.end()
    return result


def _checked_vod_playlist(url):
    """Return the original VOD master after validating its playable graph.

    Keeping it intact lets native HLS retain AUDIO groups and relative bases.
    Every advertised variant/rendition playlist is checked, not just one child.
    Depth remains master -> media; total requests/references are bounded.
    """
    root = _vod_reference(None, url)
    validated: set[str] = set()
    visiting: set[str] = set()

    def visit(current, depth):
        if current in visiting or depth > 1:
            manifest_restriction('manifest.depth', 'Nested HLS masters are not implemented.')
        if current in validated:
            return
        if len(validated) + len(visiting) >= MAX_VOD_PLAYLISTS:
            manifest_restriction('manifest.graph_limit', 'HLS rendition graph exceeds the safety limit.')
        visiting.add(current)
        manifest = fetch(current).decode('utf-8')
        if not manifest.startswith('#EXTM3U'):
            manifest_restriction('manifest.format', 'Expected an HLS playlist.')
        if '#EXT-X-KEY' in manifest or '#EXT-X-SESSION-KEY' in manifest:
            manifest_restriction('manifest.encryption', 'Encrypted HLS is not implemented by this prototype.')
        if '#EXT-X-CONTENT-STEERING' in manifest:
            manifest_restriction('manifest.format', 'HLS content steering is not supported.')
        lines = [line.strip() for line in manifest.splitlines() if line.strip()]
        references = [line for line in lines if not line.startswith('#')]
        uri_references = []
        for line in lines:
            if line.startswith('#EXT-') and re.search(r'[:,]URI=', line):
                attributes = _hls_attributes(line)
                if 'URI' in attributes:
                    uri_references.append(attributes['URI'])
        if len(references) + len(uri_references) > MAX_VOD_REFERENCES:
            manifest_restriction('manifest.graph_limit', 'HLS references exceed the safety limit.')
        for reference in references + uri_references:
            _vod_reference(current, reference)
        variants = []
        renditions = []
        audio_groups: dict[str, set[str]] = {}
        for index, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:'):
                if index + 1 >= len(lines) or lines[index + 1].startswith('#'):
                    manifest_restriction('manifest.format', 'A required HLS variant URI is missing.')
                variants.append((_hls_attributes(line), _vod_reference(current, lines[index + 1])))
            elif line.startswith('#EXT-X-MEDIA:'):
                media = _hls_attributes(line)
                if media.get('TYPE') not in {'AUDIO', 'VIDEO', 'SUBTITLES', 'CLOSED-CAPTIONS'}:
                    manifest_restriction('manifest.format', 'Unsupported HLS rendition declaration.')
                if not media.get('GROUP-ID') or not media.get('NAME'):
                    manifest_restriction('manifest.audio_group', 'An HLS rendition group is malformed.')
                if media['TYPE'] == 'AUDIO':
                    group = audio_groups.setdefault(media['GROUP-ID'], set())
                    if media['NAME'] in group or any(media.get(k) not in (None, 'YES', 'NO') for k in ('DEFAULT', 'AUTOSELECT')):
                        manifest_restriction('manifest.audio_group', 'An HLS audio group is malformed.')
                    if media.get('DEFAULT') == 'YES' and media.get('AUTOSELECT') == 'NO':
                        manifest_restriction('manifest.audio_group', 'An HLS audio group is malformed.')
                    group.add(media['NAME'])
                if 'URI' in media:
                    if media['TYPE'] == 'CLOSED-CAPTIONS':
                        manifest_restriction('manifest.format', 'Malformed closed-caption rendition URI.')
                    renditions.append(_vod_reference(current, media['URI']))
            elif line.startswith('#EXT-X-I-FRAME-STREAM-INF:'):
                iframe = _hls_attributes(line)
                renditions.append(_vod_reference(current, iframe.get('URI')))
        if variants:
            if depth or len(references) != len(variants):
                manifest_restriction('manifest.depth', 'Nested or malformed HLS masters are not implemented.')
            for variant, _ in variants:
                if 'AUDIO' in variant and (not variant['AUDIO'] or variant['AUDIO'] not in audio_groups):
                    manifest_restriction('manifest.audio_group', 'A referenced HLS audio group is missing or malformed.')
            children = list(dict.fromkeys([child for _, child in variants] + renditions))
            if len(children) + 1 > MAX_VOD_PLAYLISTS:
                manifest_restriction('manifest.graph_limit', 'HLS rendition graph exceeds the safety limit.')
            for child in children:
                visit(child, depth + 1)
        elif not any(line.startswith('#EXTINF:') for line in lines) or not references:
            manifest_restriction('manifest.format', 'Unsupported HLS playlist structure.')
        visiting.remove(current)
        validated.add(current)

    visit(root, 0)
    return root


def vod_playback_path(url):
    """Native Kodi/FFmpeg protocol option; only an evidenced public header.

    API bearer/credential/provider header maps are deliberately never accepted.
    """
    return _vod_reference(None, url) + '|' + urlencode({'User-Agent': MEDIA_USER_AGENT})


def checked_live_url(url, credentials=()):
    """Check the resolved provider URL, preserving its playback query exactly.

    Media/session URLs may reach native player logs. Reusable account secrets
    may not. This is not an HLS downloader, rewriter or redirect policy engine.
    """
    with diagnostic_stage('live.url_policy'):
        try:
            if (not isinstance(url, str) or not url or len(url) > 8192 or
                    any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '|\\' for c in url) or
                    re.search(r'%(?![0-9a-fA-F]{2})', url) or '#' in url):
                raise ValueError()
            parts = urlsplit(url)
            host = 'cdn-uw2-prod.tsv2.amagi.tv'
            if (parts.scheme != 'https' or parts.hostname != host or
                    parts.netloc.lower() not in (host, host + ':443') or
                    parts.port not in (None, 443) or parts.username is not None or
                    parts.password is not None or not parts.path.startswith('/') or
                    parts.fragment or len(parts.query) > 4096):
                raise ValueError()
            decoded, path_components = url, parts.path.split('/')
            for _ in range(3):
                decoded = unquote(decoded, errors='strict')
                path_components = [unquote(part, errors='strict') for part in path_components]
                if any(ord(c) < 32 or ord(c) == 127 or c in '|\\' for c in decoded):
                    raise ValueError()
            pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64, errors='strict')
            reusable_keys = {
                'password', 'passwd', 'authorization', 'refreshtoken',
                'accountaccesstoken', 'accountrefreshtoken', 'cookie', 'cookies',
                'setcookie', 'sessioncookie', 'apikey', 'clientsecret',
            }
            if any(re.sub(r'[^a-z0-9]', '', key.lower()) in reusable_keys for key, _ in pairs):
                raise ValueError()
            bounded_path = '/' + '/'.join(path_components) + '/'
            for secret in credentials:
                if isinstance(secret, str) and secret and (
                        secret in path_components or '/' + secret + '/' in bounded_path or
                        any(value in (secret, 'Bearer ' + secret) or (len(secret) >= 8 and secret in value)
                            for _, value in pairs) or
                        (len(secret) >= 8 and secret in decoded)):
                    raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise UnsupportedStreamError('Unsafe or account-credential-bearing live URL is not supported.') from None
        return url


def _checked_media_playlist(url):
    """Keep the working clear-HLS selection and credential-refusal policy."""
    for _ in range(2):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.query or parts.fragment or parts.username or parts.password:
            manifest_restriction('manifest.url_policy', 'Token-bearing or non-HTTPS playback URLs are not supported.')
        manifest = fetch(url).decode('utf-8')
        if not manifest.startswith('#EXTM3U'):
            manifest_restriction('manifest.format', 'Expected an HLS playlist.')
        if '#EXT-X-KEY' in manifest or '#EXT-X-SESSION-KEY' in manifest:
            manifest_restriction('manifest.encryption', 'Encrypted HLS is not implemented by this prototype.')
        lines = [line.strip() for line in manifest.splitlines() if line.strip()]
        references = [line for line in lines if not line.startswith('#')]
        references += re.findall(r'URI="([^"]+)"', manifest)
        for reference in references:
            target = urlsplit(urljoin(url, reference))
            if target.scheme != 'https' or target.query or target.fragment or target.username or target.password:
                manifest_restriction('manifest.reference_policy', 'Token-bearing media references are not supported.')
        if '#EXT-X-STREAM-INF' in manifest:
            if not references:
                manifest_restriction('manifest.format', 'No HLS media playlist was returned.')
            url = urljoin(url, references[0])
        elif '#EXTINF:' in manifest and references:
            return url
        else:
            manifest_restriction('manifest.format', 'Unsupported HLS playlist structure.')
    manifest_restriction('manifest.depth', 'Nested HLS masters are not implemented.')


def reject_blockers(blockers):
    reasons = {b.get('reason') for b in blockers if isinstance(b, dict)}
    if 'GEO' in reasons:
        raise RegionError('This video is not available in your region.')
    if 'AUTHENTICATION' in reasons:
        raise AuthenticationError('This video requires sign-in. Choose Verify login.')
    if reasons.intersection({'SUBSCRIPTION', 'PRODUCTS_MISMATCH_BLOCKED', 'REQUIRES PURCHASE'}):
        raise EntitlementError('Your account does not include this video. Check membership on the official website.')
    raise UnavailableError('The service has blocked this video. Availability or another access condition prevents playback.')


class Client:
    def __init__(self, device_id=None):
        self.on_token = None
        self.refreshed = False
        with diagnostic_stage('bootstrap.bundle'):
            text = fetch(BUNDLE).decode('utf-8')
        match = re.search(r"13322:function\(e\).*?JSON\.parse\(('(?:\\.|[^'\\])*')\)", text, re.S)
        if not match:
            report('bootstrap.config', ServiceError())
            raise ServiceError('Official application changed; client update required.')
        try:
            runtime = json.loads(ast.literal_eval(match.group(1)))
            self.headers = {
                'Origin': APP, 'Accept': 'application/json',
                'Content-Type': 'application/json', 'Accept-Language': 'en',
                'X-Device-Type': 'web', 'X-Device-ID': device_id or str(uuid.uuid4()),
                'X-Service-ID': runtime['apiService']['id'],
                'X-Application-ID': runtime['apiService']['appId']['web'],
            }
        except (KeyError, TypeError, ValueError, SyntaxError) as error:
            report('bootstrap.config', error)
            raise ServiceError('Official configuration changed.') from None
        self.configuration = self.get('/configurations/application')

    def set_token(self, token):
        if not isinstance(token, str) or not token:
            raise AuthenticationError('The service did not return a usable viewing session.')
        self.headers['Authorization'] = 'Bearer ' + token
        if self.on_token:
            self.on_token(token)

    def request(self, path, query=None, body=None, method=None):
        with diagnostic_stage(request_stage(path)):
            return self._request(path, query=query, body=body, method=method)

    def _request(self, path, query=None, body=None, method=None):
        url = API + path + ('?' + urlencode(query) if query else '')
        try:
            return json_request(url, self.headers, body, method)
        except HTTPFailure as error:
            if error.status != 401:
                if error.status == 404:
                    raise UnavailableError('Requested content is no longer available.') from None
                raise
            if not self.headers.get('Authorization') or path == '/user/code/verify':
                raise AuthenticationError('Sign-in was rejected or expired. Choose Verify login.') from None
        # Match the official client: authenticated 401 -> POST refresh with
        # the current bearer, then retry the original request ONCE. No guessed
        # refresh_token field, JWT expiry policy, or unbounded login loop.
        try:
            with diagnostic_stage('auth.refresh'):
                result = json_request(API + '/user/refresh-token', self.headers, method='POST')
            self.set_token(result.get('token'))
            self.refreshed = True
            return json_request(url, self.headers, body, method)
        except HTTPFailure as error:
            if error.status == 401:
                raise AuthenticationError('Your viewing session expired. Choose Verify login.') from None
            raise

    def get(self, path, query=None):
        return self.request(path, query=query)

    def post(self, path, body):
        return self.request(path, body=body, method='POST')

    def graphql(self, operation, query, variables, token=None):
        headers = {'Content-Type': 'application/json',
                   'X-Source-Page-URL': 'https://www.tastemade.com/app',
                   'Origin': 'https://www.tastemade.com',
                   'Referer': 'https://www.tastemade.com/app'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            result = json_request(GRAPHQL, headers, {
                'operationName': operation, 'query': query, 'variables': variables})
        except HTTPFailure as error:
            if error.status == 401:
                raise AuthenticationError('Sign-in was rejected. Check login on the official website.') from None
            raise
        if result.get('errors') or not result.get('data'):
            # A GraphQL sign-in failure does not establish bad password vs MFA.
            raise AuthenticationError('Sign-in did not complete. Check your account or any browser challenge on the official website.')
        return result['data']

    def login(self, username, password):
        if not username or not password:
            raise AuthenticationError('Enter your email and password in add-on settings, then choose Verify login.')
        code = self.get('/user/code')['code']
        data = self.graphql('LogInUserWithEmail', '''
          mutation LogInUserWithEmail($email: String!, $password: String!, $client: String = "web") {
            users_login_with_email(email: $email, password: $password, client: $client) {
              access_token expires_at
            }
          }''', {'email': username, 'password': password, 'client': 'ott'})
        token = data['users_login_with_email']['access_token']
        self.graphql('LoginWithConnectCode', '''
          mutation LoginWithConnectCode($code: String!) {
            users_authorize_connect_code(code: $code) { message client }
          }''', {'code': code}, token)
        session = self.post('/user/code/verify', {'code': code})
        self.set_token(session.get('token'))
        self.get('/user')

    def menus(self):
        seen = set()
        items = []
        for menu in self.get('/menus'):
            for item in menu.get('items', []):
                key = (item.get('reference'), item.get('label'))
                if item.get('type') == 'page' and item.get('reference') and key not in seen:
                    seen.add(key)
                    items.append(item)
        return items

    def sections(self, page):
        return [s for s in self.get('/pages/' + segment(page), {'includeItems': 'false'})
                if _catalog_id(s.get('playlistId'))]

    def live_channels(self, page, offset=0):
        """Resolve the observed live page's one playlist without an extra UI level.

        Discover references from the current service; never hardcode IDs or choose
        the first of several different playlists after a provider layout change.
        """
        offset = page_offset(offset)
        message = 'Live TV channel layout changed. Try Browse again.'
        try:
            sections = self.sections(page)
        except (TypeError, AttributeError):
            raise ServiceError(message) from None
        if not isinstance(sections, list):
            raise ServiceError(message)
        playlists = []
        for section in sections:
            if not isinstance(section, dict) or not _catalog_id(section.get('playlistId')):
                raise ServiceError(message)
            reference = section['playlistId']
            if reference not in playlists:
                playlists.append(reference)
        if len(playlists) != 1:
            raise ServiceError(message)
        return self.playlist(playlists[0], offset)

    def playlist(self, playlist, offset=0):
        offset = page_offset(offset)
        return catalog_page(self.get('/playlists/' + segment(playlist),
                                     {'offset': offset, 'size': PAGE_SIZE + 1}), offset)

    def episodes(self, series, offset=0):
        offset = page_offset(offset)
        return catalog_page(self.get('/media/series/' + segment(series) + '/episodes',
                                     {'offset': offset, 'size': PAGE_SIZE + 1}), offset)

    def series(self, series):
        result = self.get('/media/series/' + segment(series))
        if not isinstance(result, dict):
            raise ServiceError('Unexpected series response. Return to the previous listing.')
        return result

    def episode_inventory(self, series):
        # The official frontend groups seasons from a bounded episode inventory;
        # no separate season endpoint/art contract was observed. A full/capped
        # response is not declared complete: retain the old paged All episodes.
        result = self.get('/media/series/' + segment(series) + '/episodes',
                          {'offset': 0, 'size': SERIES_INVENTORY_LIMIT})
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise ServiceError('Unexpected episode response. Return to the previous listing.')
        items = result['items']
        if len(items) > SERIES_INVENTORY_LIMIT or any(not isinstance(item, dict) for item in items):
            raise ServiceError('Unexpected episode inventory size or items.')
        if 'offset' in result and (type(result['offset']) is not int or result['offset'] != 0):
            raise ServiceError('The service returned a different episode inventory. Return to the previous listing.')
        total = result.get('total')
        size = result.get('size', SERIES_INVENTORY_LIMIT)
        complete = len(items) < SERIES_INVENTORY_LIMIT
        if type(total) is int and total > len(items):
            complete = False
        if type(size) is int and 0 < size < SERIES_INVENTORY_LIMIT and len(items) >= size:
            complete = False
        return {'items': items, 'complete': complete}

    @staticmethod
    def asset_path(kind, asset_id):
        collections = {'episode': 'episodes', 'movie': 'movies', 'clip': 'clips', 'channel': 'channels'}
        if kind not in collections:
            raise UnsupportedStreamError('This asset type is not supported by the prototype.')
        return '/media/' + collections[kind] + '/' + segment(asset_id)

    def resolve(self, kind, asset_id):
        with diagnostic_stage('resolve.channel' if kind == 'channel' else 'resolve.vod'):
            return self._resolve(kind, asset_id)

    def _resolve(self, kind, asset_id):
        path = self.asset_path(kind, asset_id)
        asset = self.get(path)
        if asset.get('blocked'):
            reject_blockers(asset['blocked'])
        editions = self.get(path + '/editions')
        blockers = []
        eligible = False
        for edition in editions:
            if edition.get('editionType') not in ('full', None):
                continue
            if edition.get('blocked'):
                blockers.extend(edition['blocked'])
                continue
            eligible = True
            for stream in edition.get('streams', []):
                if stream.get('type') == 'hls' and stream.get('drm') == 'unencrypted':
                    result = self.get(path + '/stream', {
                        'editionId': edition['id'], 'type': 'hls', 'drm': 'unencrypted'})
                    if result.get('drm') not in ('unencrypted', None):
                        raise UnsupportedStreamError('DRM playback is not supported by this prototype.')
                    url = result.get('url')
                    if not url:
                        error = UnsupportedStreamError('Indirect/ad-insertion stream is not implemented.')
                        report('resolve.indirect', error)
                        raise error
                    if kind == 'channel':
                        # Keep API authentication out of the native media path.
                        authorization = self.headers.get('Authorization', '')
                        token = authorization[7:] if authorization.startswith('Bearer ') else ''
                        return checked_live_url(url, credentials=(token,))
                    return checked_media_playlist(url, preserve_master=kind != 'channel')
        if not eligible and blockers:
            reject_blockers(blockers)
        error = UnsupportedStreamError('No supported unencrypted full-length HLS stream is available.')
        if editions and not any(e.get('editionType') in ('full', None) for e in editions):
            report('resolve.edition_policy', error)
        raise error
