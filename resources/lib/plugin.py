"""Normal plugin routing only. UI actions replace their route with safe root."""
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from auth import SessionStore, authenticated_client
from service import AuthenticationError, Client, ServiceError, page_offset


def run():
    addon = xbmcaddon.Addon()
    handle = int(sys.argv[1])
    base = sys.argv[0]
    query = parse_qs(sys.argv[2].lstrip('?'))
    action = query.get('action', ['root'])[0]
    playback = action == 'play'
    ui_action = action in ('settings', 'login', 'logout')
    success = True
    store = None

    def text(number):
        return addon.getLocalizedString(number)

    def value(key):
        return query.get(key, [''])[0]

    def add(label, route, folder=True, **parameters):
        item = xbmcgui.ListItem(label=str(label))
        if not folder:
            item.setProperty('IsPlayable', 'true' if route == 'play' else 'false')
        url = base + '?' + urlencode(dict(action=route, **parameters))
        xbmcplugin.addDirectoryItem(handle, url, item, isFolder=folder)

    def list_assets(assets):
        for asset in assets:
            kind = asset.get('type')
            if kind == 'series':
                add(asset.get('label', text(30008)), 'episodes', asset=asset['id'])
            elif kind in ('episode', 'movie', 'clip', 'channel'):
                add(asset.get('label', text(30008)), 'play', folder=False,
                    asset=asset['id'], kind=kind)

    def list_page(result, route, **identity):
        if result['previous_offset'] is not None:
            add('Previous page', route, offset=result['previous_offset'], **identity)
        list_assets(result['items'])
        if result['next_offset'] is not None:
            add(text(30007), route, offset=result['next_offset'], **identity)
        if not result['items']:
            xbmcgui.Dialog().notification(addon.getAddonInfo('name'), 'No items on this page.')

    def account():
        nonlocal store
        store = SessionStore(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
        return addon.getSetting('username'), addon.getSetting('password')

    try:
        xbmcplugin.setContent(handle, 'videos')
        if action == 'root':
            # Root stays offline and does not read authentication/profile data.
            add(text(30003), 'settings')
            add(text(30004), 'login')
            add(text(30005), 'browse')
            add('Log out (this Kodi profile)', 'logout')
        elif action == 'settings':
            addon.openSettings()
            username, password = account()
            assert store is not None
            store.bind(username, password)
        elif action == 'login':
            username, password = account()
            _, state = authenticated_client(store, username, password, interactive=True)
            messages = {
                'signed_in': 'Signed in. A private viewing session was saved.',
                'reused': 'Authenticated using the saved viewing session. No password sign-in was needed.',
                'refreshed': 'Authenticated. The saved viewing session was refreshed by the service.',
            }
            xbmcgui.Dialog().ok(addon.getAddonInfo('name'), messages[state])
        elif action == 'logout':
            username, password = account()
            assert store is not None
            store.bind(username, password).logout()
            xbmcgui.Dialog().ok(addon.getAddonInfo('name'),
                               'Signed out on this Kodi profile. Choose Verify login to sign in again.')
        elif action == 'browse':
            for menu in Client().menus():
                add(menu.get('label', text(30008)), 'page', page=menu['reference'])
        elif action == 'page':
            for section in Client().sections(value('page')):
                add(section.get('label', text(30008)), 'playlist', playlist=section['playlistId'])
        elif action == 'playlist':
            offset = page_offset(value('offset') or '0')
            result = Client().playlist(value('playlist'), offset)
            list_page(result, 'playlist', playlist=value('playlist'))
        elif action == 'episodes':
            offset = page_offset(value('offset') or '0')
            result = Client().episodes(value('asset'), offset)
            list_page(result, 'episodes', asset=value('asset'))
        elif playback:
            username, password = account()
            client, _ = authenticated_client(store, username, password)
            stream = client.resolve(value('kind'), value('asset'))
            item = xbmcgui.ListItem(path=stream)
            item.setMimeType('application/vnd.apple.mpegurl')
            item.setContentLookup(False)
            xbmcplugin.setResolvedUrl(handle, True, item)
        else:
            raise ServiceError('Unsupported prototype route.')
    except ServiceError as error:
        success = False
        if isinstance(error, AuthenticationError) and store and store.record:
            store.invalidate(signed_out=bool(store.record.get('signed_out')))
        xbmcgui.Dialog().ok(addon.getAddonInfo('name'), str(error))
    except Exception:
        success = False
        xbmcgui.Dialog().ok(addon.getAddonInfo('name'), text(30009))
    finally:
        if playback:
            if not success:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        else:
            xbmcplugin.endOfDirectory(handle, succeeded=success or ui_action, cacheToDisc=False)
            if ui_action:
                # Replace the action URL after the modal closes, including on
                # failure. Restoring Videos must never reopen login/settings.
                xbmc.executebuiltin('Container.Update({},replace)'.format(base))
