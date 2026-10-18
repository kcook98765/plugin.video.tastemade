"""Normal plugin routing only. UI actions replace their route with safe root."""
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from auth import SessionStore, authenticated_client
from catalog_metadata import catalog_metadata, clean_description, clean_label
from catalogue import season_groups, season_number, season_page
from diagnostics import configure, directory_stage, report
from live_playback import ensure_inputstream
from service import AuthenticationError, Client, ServiceError, checked_live_url, page_offset, vod_playback_path


def run():
    configure(lambda line: xbmc.log(line, xbmc.LOGWARNING))
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

    def heading(label):
        xbmcplugin.setPluginCategory(handle, clean_label(label, 'Tastemade'))

    def identity(identifier):
        return ((isinstance(identifier, str) and bool(identifier.strip())) or
                (type(identifier) is int and identifier >= 0))

    def season_label(number):
        return text(30019) if number is None else (text(30024) if number == 0 else text(30018).format(number))

    def add(label, route, folder=True, details=None, parent=None, icon=None, numbered=False,
            summary=None, secondary=None, **parameters):
        metadata = catalog_metadata(details, text(30008), parent) if details is not None else None
        label = metadata.title if metadata else clean_label(label, text(30008))
        if numbered and metadata and metadata.episode is not None:
            label = '{:02d}. {}'.format(metadata.episode, label)
        item = xbmcgui.ListItem(label=label)
        if metadata:
            # Populate the listed item, not only the later playback result:
            # Kodi's native Information action must work before resolution.
            tag = item.getVideoInfoTag()
            tag.setTitle(metadata.title)
            tag.setMediaType(metadata.media_type)
            plot = metadata.plot or clean_description(summary)
            if plot:
                tag.setPlot(plot)
            if metadata.outline:
                tag.setPlotOutline(metadata.outline)
            if metadata.show_title:
                tag.setTvShowTitle(metadata.show_title)
            if metadata.season is not None:
                tag.setSeason(metadata.season)
            if metadata.episode is not None:
                tag.setEpisode(metadata.episode)
            if metadata.year is not None:
                tag.setYear(metadata.year)
            if metadata.premiered:
                tag.setPremiered(metadata.premiered)
            if metadata.genres:
                tag.setGenres(metadata.genres)
            item.setArt(metadata.art)
        else:
            icons = {'settings': 'icons/settings.png', 'login': 'icons/settings/profiles.png',
                     'browse': 'DefaultAddonVideo.png', 'logout': 'DefaultUser.png'}
            fallback = icon or icons.get(route, 'DefaultFolder.png')
            item.setArt({'icon': fallback, 'thumb': fallback})
            plot = clean_description(summary)
            if plot:
                # Untyped folder help, not a playable video's fabricated metadata.
                tag = item.getVideoInfoTag()
                tag.setTitle(label)
                tag.setPlot(plot)
        if clean_label(secondary):
            item.setLabel2(clean_label(secondary))
        if not folder:
            item.setProperty('IsPlayable', 'true' if route == 'play' else 'false')
        url = base + '?' + urlencode(dict(action=route, **parameters))
        xbmcplugin.addDirectoryItem(handle, url, item, isFolder=folder)

    def list_assets(assets, parent=None, allowed=None):
        rendered = 0
        for asset in assets:
            if not isinstance(asset, dict) or not identity(asset.get('id')):
                continue
            kind = asset.get('type')
            if allowed is not None and kind not in allowed:
                continue
            if kind == 'series':
                title = clean_label(asset.get('label'), text(30008))
                add(title, 'seasons', details=asset, summary=text(30039), asset=asset['id'], title=title)
            elif kind in ('episode', 'movie', 'clip', 'channel'):
                add(asset.get('label', text(30008)), 'play', folder=False, details=asset,
                    parent=parent, numbered=parent is not None, asset=asset['id'], kind=kind)
            else:
                continue
            rendered += 1
        return rendered

    def list_page(result, route, parent=None, allowed=None, **context):
        if result['previous_offset'] is not None:
            add(text(30014), route, icon='DefaultFolderBack.png', summary=text(30036),
                offset=result['previous_offset'], **context)
        rendered = list_assets(result['items'], parent, allowed)
        if result['next_offset'] is not None:
            add(text(30007), route, summary=text(30037), offset=result['next_offset'], **context)
        if not rendered:
            title = text(30026) if route == 'live' else clean_label(value('title'), 'Tastemade')
            if route == 'season_episodes':
                title += ' — ' + season_label(season_number(value('season')))
            heading(title + ' — ' + text(30015 if not result['items'] else 30016))

    def series_context(client):
        series = client.series(value('asset'))
        title = clean_label(series.get('label'), clean_label(value('title'), text(30008)))
        art = catalog_metadata(series, title).art
        if art.get('fanart'):
            xbmcplugin.setPluginFanart(handle, image=art['fanart'])
        return series, title, client.episode_inventory(value('asset'))

    def account():
        nonlocal store
        store = SessionStore(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
        return addon.getSetting('username'), addon.getSetting('password')

    try:
        if not playback:
            xbmcplugin.setContent(handle, 'files')
            heading(clean_label(value('title'), 'Tastemade'))
            xbmcplugin.setPluginFanart(handle)
        if action == 'root':
            # Root stays offline and does not read authentication/profile data.
            add(text(30003), 'settings', summary=text(30030))
            add(text(30004), 'login', summary=text(30031))
            add(text(30005), 'browse', summary=text(30029))
            add(text(30013), 'logout', summary=text(30032))
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
            count = 0
            for menu in Client().menus():
                if isinstance(menu, dict) and identity(menu.get('reference')):
                    label = clean_label(menu.get('label'), text(30008))
                    purpose = label.casefold()
                    route = 'page'
                    summary = (clean_description(menu.get('description')) or
                               clean_description(menu.get('shortDescription')))
                    if purpose == 'home':
                        label, summary = text(30025), text(30027)
                    elif purpose == 'live now':
                        label, summary, route = text(30026), text(30028), 'live'
                    add(label, route, summary=summary or text(30033).format(label),
                        page=menu['reference'], title=label)
                    count += 1
            if not count:
                heading('Tastemade — ' + text(30015))
        elif action == 'page':
            count = 0
            for section in Client().sections(value('page')):
                if isinstance(section, dict) and identity(section.get('playlistId')):
                    label = clean_label(section.get('label'), text(30008))
                    summary = (clean_description(section.get('description')) or
                               clean_description(section.get('shortDescription')) or text(30033).format(label))
                    add(label, 'playlist', summary=summary, playlist=section['playlistId'], title=label)
                    count += 1
            if not count:
                heading(clean_label(value('title'), 'Tastemade') + ' — ' + text(30015))
        elif action == 'live':
            offset = page_offset(value('offset') or '0')
            result = Client().live_channels(value('page'), offset)
            xbmcplugin.setContent(handle, 'videos')
            heading(text(30026))
            list_page(result, 'live', allowed=('channel',), page=value('page'), title=text(30026))
        elif action == 'playlist':
            offset = page_offset(value('offset') or '0')
            result = Client().playlist(value('playlist'), offset)
            kinds = {item.get('type') for item in result['items']
                     if identity(item.get('id')) and item.get('type') in ('series', 'movie', 'episode', 'clip', 'channel')}
            content = {'series': 'tvshows', 'movie': 'movies', 'episode': 'episodes'}
            xbmcplugin.setContent(handle, content.get(next(iter(kinds)), 'videos') if len(kinds) == 1 else 'videos')
            context = {'playlist': value('playlist')}
            if value('title'):
                context['title'] = clean_label(value('title'))
            list_page(result, 'playlist', **context)
        elif action == 'seasons':
            series, title, inventory = series_context(Client())
            heading(title + ' — ' + text(30017))
            xbmcplugin.setContent(handle, 'seasons')
            if not inventory['complete']:
                heading(title + ' — ' + text(30021))
                add(text(30020), 'episodes', summary=text(30035), asset=value('asset'), title=title)
            else:
                groups = season_groups(inventory['items'])
                for group in groups:
                    number = group['number']
                    label = season_label(number)
                    details = {'type': 'season', 'label': label, 'seriesName': title}
                    if number is not None:
                        details['seasonNumber'] = number
                    add(label, 'season_episodes', details=details, parent=series,
                        summary=text(30033).format(label),
                        secondary=text(30038) if group['count'] == 1 else text(30034).format(group['count']),
                        asset=value('asset'), season='unknown' if number is None else str(number), title=title)
                if not groups:
                    heading(title + ' — ' + text(30015))
        elif action == 'season_episodes':
            number = season_number(value('season'))
            offset = page_offset(value('offset') or '0')
            series, title, inventory = series_context(Client())
            xbmcplugin.setContent(handle, 'episodes')
            heading(title + ' — ' + season_label(number))
            if not inventory['complete']:
                heading(title + ' — ' + text(30021))
                add(text(30020), 'episodes', summary=text(30035), asset=value('asset'), title=title)
            else:
                result = season_page(inventory['items'], value('season'), offset)
                list_page(result, 'season_episodes', parent=series, asset=value('asset'),
                          season=value('season'), title=title)
        elif action == 'episodes':
            offset = page_offset(value('offset') or '0')
            result = Client().episodes(value('asset'), offset)
            xbmcplugin.setContent(handle, 'episodes')
            heading(clean_label(value('title'), text(30020)))
            context = {'asset': value('asset')}
            if value('title'):
                context['title'] = clean_label(value('title'))
            list_page(result, 'episodes', **context)
        elif playback:
            properties = {}
            if value('kind') == 'channel':
                if not addon.getSettingBool('enable_live'):
                    raise ServiceError('Live TV is disabled. Enable live TV in add-on settings, then select a channel to set up InputStream Adaptive.')
                properties = ensure_inputstream(
                    xbmcaddon.Addon, xbmc.getCondVisibility, xbmcgui.Dialog().yesno,
                    xbmc.executebuiltin, addon.getAddonInfo('name'))
            username, password = account()
            client, _ = authenticated_client(store, username, password)
            stream = client.resolve(value('kind'), value('asset'))
            if value('kind') == 'channel':
                path = checked_live_url(stream, credentials=(username, password))
            else:
                path = vod_playback_path(stream)
            item = xbmcgui.ListItem(path=path)
            for key, setting in properties.items():
                item.setProperty(key, setting)
            item.setMimeType('application/vnd.apple.mpegurl')
            item.setContentLookup(False)
            xbmcplugin.setResolvedUrl(handle, True, item)
        else:
            raise ServiceError('Unsupported prototype route.')
    except ServiceError as error:
        success = False
        report(directory_stage(action), error)
        if isinstance(error, AuthenticationError) and store and store.record:
            store.invalidate(signed_out=bool(store.record.get('signed_out')))
        xbmcgui.Dialog().ok(addon.getAddonInfo('name'), str(error))
    except Exception as error:
        success = False
        report(directory_stage(action), error)
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
        configure(None)
