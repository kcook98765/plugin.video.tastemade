"""Official web-client protocol; fixed safe errors, no response/URL logging."""
import ast
import json
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

APP = 'https://app.tastemade.com'
API = 'https://backstage-api.com'
GRAPHQL = 'https://gql.tastemadecdn.net/v1/graphql'
BUNDLE = APP + '/_next/static/chunks/79707.bd7603679c84782e.js'
MAX_BYTES = 12000000
PAGE_SIZE = 30


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
        raise ServiceError('Redirect requires review; request stopped.')


def fetch(url, headers=None, body=None, method=None):
    if urlsplit(url).scheme != 'https':
        raise UnsupportedStreamError('Only HTTPS is supported.')
    request_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': APP + '/'}
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
        if error.code == 429 or error.code >= 500:
            raise NetworkError('Service busy or temporarily unavailable. Try again later.') from None
        raise HTTPFailure(error.code) from None
    except (URLError, OSError, ValueError):
        raise NetworkError('Network request failed. Check connectivity and try again later.') from None


def json_request(url, headers, body=None, method=None):
    try:
        payload = fetch(url, headers, body, method)
        return json.loads(payload) if payload else {}
    except (ValueError, UnicodeError):
        raise ServiceError('Unexpected service response; no sensitive details recorded.') from None


def segment(value):
    return quote(str(value), safe='')


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


def checked_media_playlist(url):
    """Keep the working clear-HLS selection and credential-refusal policy."""
    for _ in range(2):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.query or parts.fragment or parts.username or parts.password:
            raise UnsupportedStreamError('Token-bearing or non-HTTPS playback URLs are not supported.')
        manifest = fetch(url).decode('utf-8')
        if not manifest.startswith('#EXTM3U'):
            raise UnsupportedStreamError('Expected an HLS playlist.')
        if '#EXT-X-KEY' in manifest or '#EXT-X-SESSION-KEY' in manifest:
            raise UnsupportedStreamError('Encrypted HLS is not implemented by this prototype.')
        lines = [line.strip() for line in manifest.splitlines() if line.strip()]
        references = [line for line in lines if not line.startswith('#')]
        references += re.findall(r'URI="([^"]+)"', manifest)
        for reference in references:
            target = urlsplit(urljoin(url, reference))
            if target.scheme != 'https' or target.query or target.fragment or target.username or target.password:
                raise UnsupportedStreamError('Token-bearing media references are not supported.')
        if '#EXT-X-STREAM-INF' in manifest:
            if not references:
                raise UnsupportedStreamError('No HLS media playlist was returned.')
            url = urljoin(url, references[0])
        elif '#EXTINF:' in manifest and references:
            return url
        else:
            raise UnsupportedStreamError('Unsupported HLS playlist structure.')
    raise UnsupportedStreamError('Nested HLS masters are not implemented.')


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
        text = fetch(BUNDLE).decode('utf-8')
        match = re.search(r"13322:function\(e\).*?JSON\.parse\(('(?:\\.|[^'\\])*')\)", text, re.S)
        if not match:
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
        except (KeyError, TypeError, ValueError, SyntaxError):
            raise ServiceError('Official configuration changed.') from None
        self.configuration = self.get('/configurations/application')

    def set_token(self, token):
        if not isinstance(token, str) or not token:
            raise AuthenticationError('The service did not return a usable viewing session.')
        self.headers['Authorization'] = 'Bearer ' + token
        if self.on_token:
            self.on_token(token)

    def request(self, path, query=None, body=None, method=None):
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
        return [s for s in self.get('/pages/' + segment(page), {'includeItems': 'false'}) if s.get('playlistId')]

    def playlist(self, playlist, offset=0):
        offset = page_offset(offset)
        return catalog_page(self.get('/playlists/' + segment(playlist),
                                     {'offset': offset, 'size': PAGE_SIZE + 1}), offset)

    def episodes(self, series, offset=0):
        offset = page_offset(offset)
        return catalog_page(self.get('/media/series/' + segment(series) + '/episodes',
                                     {'offset': offset, 'size': PAGE_SIZE + 1}), offset)

    @staticmethod
    def asset_path(kind, asset_id):
        collections = {'episode': 'episodes', 'movie': 'movies', 'clip': 'clips', 'channel': 'channels'}
        if kind not in collections:
            raise UnsupportedStreamError('This asset type is not supported by the prototype.')
        return '/media/' + collections[kind] + '/' + segment(asset_id)

    def resolve(self, kind, asset_id):
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
                        raise UnsupportedStreamError('Indirect/ad-insertion stream is not implemented.')
                    return checked_media_playlist(url)
        if not eligible and blockers:
            reject_blockers(blockers)
        raise UnsupportedStreamError('No supported unencrypted full-length HLS stream is available.')
