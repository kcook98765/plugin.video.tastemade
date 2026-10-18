"""Offline presentation regressions using synthetic catalogues and mocked Kodi."""
from copy import deepcopy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qs, urlencode, urlsplit

import test_hardening as fixtures
import service


BACKGROUND = 'https://assets.tastemadecdn.net/synthetic/presentation/background.jpg'
POSTER = 'https://assets.tastemadecdn.net/synthetic/presentation/poster.jpg'
STILL = 'https://assets.tastemadecdn.net/synthetic/presentation/episode.jpg'
SERIES_ID = 'synthetic/series &?'
TITLE = 'Public & Travel'


def series():
    return {
        'id': SERIES_ID, 'type': 'series', 'label': '<b>Public &amp; Travel</b>\r\n',
        'description': '<p>Series &amp; overview.</p>',
        'year': 2020, 'releaseDate': '2020-01-01',
        'seasonNumber': 9, 'episodeNumber': 8,
        'images': {'background': [{'url': BACKGROUND}], 'poster': [{'url': POSTER}]},
    }


def episode(asset_id, season=2, number=1, label='Synthetic episode'):
    return {
        'id': asset_id, 'type': 'episode', 'label': label,
        'seriesName': '<i>Public &amp; Travel</i>',
        'seasonNumber': season, 'episodeNumber': number,
        'images': {'still': [{'url': STILL}]},
    }


def forbid(test, target, name):
    """Fail even when plugin.run catches an accidental I/O/account invocation."""
    patcher = patch.object(target, name, side_effect=AssertionError('Unexpected ' + name))
    mocked = patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(mocked.assert_not_called)
    return mocked


class PresentationRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)
        forbid(self, service, 'fetch')
        forbid(self, service, 'json_request')
        forbid(self, self.plugin, 'SessionStore')
        forbid(self, self.plugin, 'authenticated_client')
        forbid(self, self.modules['xbmcvfs'], 'translatePath')
        for name in ('getSetting', 'getSettingBool', 'openSettings'):
            forbid(self, self.addon, name)
        labels = {
            30007: 'Next page', 30008: 'Untitled', 30014: 'Previous page',
            30015: 'No items on this page', 30016: 'No supported items on this page',
            30017: 'Seasons', 30018: 'Season {}', 30019: 'Other episodes',
            30020: 'All episodes', 30021: 'Browse all episodes by page', 30024: 'Specials',
        }
        self.addon.getLocalizedString.side_effect = lambda number: labels.get(number, 'label-' + str(number))
        self.client = MagicMock(spec=service.Client)
        self.client.series.return_value = series()
        self.client.episode_inventory.return_value = {'items': [], 'complete': True}
        factory = patch.object(self.plugin, 'Client', return_value=self.client)
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.directory = self.modules['xbmcplugin']
        self.directory.addSortMethod = MagicMock()
        self.modules['xbmcgui'].ListItem.side_effect = self.new_item
        self.directory.addDirectoryItem.side_effect = self.capture

    def tearDown(self):
        self.modules['xbmc'].executebuiltin.assert_not_called()
        self.directory.addSortMethod.assert_not_called()
        self.directory.setResolvedUrl.assert_not_called()
        for method in ('login', 'post', 'graphql', 'set_token', 'resolve'):
            getattr(self.client, method).assert_not_called()

    def new_item(self, label):
        item = MagicMock(spec=['getVideoInfoTag', 'setArt', 'setProperty', 'setLabel2'])
        item.label = label
        item.getVideoInfoTag.return_value = MagicMock(spec=[
            'setTitle', 'setMediaType', 'setPlot', 'setPlotOutline', 'setTvShowTitle',
            'setSeason', 'setEpisode', 'setYear', 'setPremiered', 'setGenres', 'setDuration',
        ])
        return item

    def capture(self, handle, url, item, isFolder):
        self.assertEqual(handle, 1)
        self.listed.append(SimpleNamespace(
            url=url, query=parse_qs(urlsplit(url).query), label=item.label,
            item=item, folder=isFolder, inserted=tuple(item.mock_calls)))

    def route(self, parameters=None, succeeds=True):
        self.listed = []
        for name in ('setContent', 'setPluginCategory', 'setPluginFanart',
                     'addDirectoryItem', 'endOfDirectory'):
            getattr(self.directory, name).reset_mock()
        self.dialog.reset_mock()
        query = urlsplit(parameters).query if isinstance(parameters, str) else urlencode(parameters or {})
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', '?' + query]):
            self.plugin.run()
        self.directory.endOfDirectory.assert_called_once_with(
            1, succeeded=succeeds, cacheToDisc=False)
        self.dialog.notification.assert_not_called()
        if succeeds:
            self.dialog.ok.assert_not_called()
        return list(self.listed)

    def inventory(self, assets, complete=True):
        self.client.episode_inventory.return_value = {'items': assets, 'complete': complete}

    def test_series_playlist_links_use_seasons_and_only_clean_public_title(self):
        asset = dict(series(), Authorization='SYNTHETIC_PRIVATE', url='https://synthetic.invalid/private')
        self.client.playlist.return_value = service.catalog_page({'items': [asset]}, 0)
        entry, = self.route({'action': 'playlist', 'playlist': 'synthetic-list'})
        self.assertEqual(entry.query, {'action': ['seasons'], 'asset': [SERIES_ID], 'title': [TITLE]})
        self.assertNotIn('SYNTHETIC_PRIVATE', entry.url)
        self.assertNotIn('synthetic.invalid', entry.url)
        self.assertEqual(entry.label, TITLE)
        self.assertTrue(entry.folder)
        entry.item.setProperty.assert_not_called()
        self.directory.setContent.assert_called_with(1, 'tvshows')
        self.inventory([episode('synthetic-episode')])
        season, = self.route(entry.url)
        self.assertEqual(season.query, {
            'action': ['season_episodes'], 'asset': [SERIES_ID], 'season': ['2'], 'title': [TITLE]})
        self.client.series.assert_called_once_with(SERIES_ID)
        self.client.episode_inventory.assert_called_once_with(SERIES_ID)

    def test_complete_inventory_numeric_folders_inherit_series_art_not_dates(self):
        assets = [episode('ten', 10), episode('unknown', None), episode('two', 2),
                  episode('special', 0), episode('one', 1), None, 'not-an-asset',
                  {'type': 'movie', 'id': 'not-an-episode'}, episode(True, 7), episode('', 8)]
        original = deepcopy(assets)
        self.inventory(assets)
        entries = self.route({'action': 'seasons', 'asset': SERIES_ID, 'title': 'Stale title'})
        self.assertEqual([entry.label for entry in entries],
                         ['Specials', 'Season 1', 'Season 2', 'Season 10', 'Other episodes'])
        self.assertEqual([entry.query['season'][0] for entry in entries], ['0', '1', '2', '10', 'unknown'])
        for entry, number in zip(entries, [0, 1, 2, 10, None]):
            self.assertTrue(entry.folder)
            self.assertEqual(entry.query['asset'], [SERIES_ID])
            self.assertEqual(entry.query['title'], [TITLE])
            entry.item.setProperty.assert_not_called()
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(entry.label)
            tag.setMediaType.assert_called_once_with('season')
            tag.setTvShowTitle.assert_called_once_with(TITLE)
            tag.setPlot.assert_called_once_with('Series & overview.')
            if number is None:
                tag.setSeason.assert_not_called()
            else:
                tag.setSeason.assert_called_once_with(number)
            for name in ('setEpisode', 'setYear', 'setPremiered', 'setDuration'):
                getattr(tag, name).assert_not_called()
            entry.item.setArt.assert_called_once_with({
                'icon': 'DefaultFolderSquare.png', 'thumb': BACKGROUND,
                'poster': POSTER, 'fanart': BACKGROUND})
            self.assertIn(call.getVideoInfoTag().setMediaType('season'), entry.inserted)
            self.assertIn(call.setArt(entry.item.setArt.call_args.args[0]), entry.inserted)
        self.assertEqual(assets, original)
        self.directory.setContent.assert_called_with(1, 'seasons')
        self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — Seasons')
        self.assertEqual(self.directory.setPluginFanart.call_args_list,
                         [call(1), call(1, image=BACKGROUND)])

    def test_selected_season_numbers_display_labels_but_preserves_titles_art_and_play_ids(self):
        assets = [episode('synthetic/ep&?=2', number=2, label='<b>Two &amp; tasty</b>\r\n'),
                  episode(10 ** 20, number=10, label='Ten'), episode(0, number=0, label='Zero'),
                  episode('unnumbered', number=True, label='<i>Bonus</i>'),
                  episode('other-season', season=1), episode(True), episode(-1), episode(None),
                  episode(''), None, {'type': 'movie', 'id': 'movie', 'seasonNumber': 2}]
        original = deepcopy(assets)
        self.inventory(assets)
        entries = self.route({'action': 'season_episodes', 'asset': SERIES_ID, 'season': '2'})
        self.assertEqual([entry.label for entry in entries], ['00. Zero', '02. Two & tasty', '10. Ten', 'Bonus'])
        for entry, asset_id, title, number in zip(
                entries, ['0', 'synthetic/ep&?=2', str(10 ** 20), 'unnumbered'],
                ['Zero', 'Two & tasty', 'Ten', 'Bonus'], [0, 2, 10, None]):
            self.assertEqual(entry.query, {'action': ['play'], 'asset': [asset_id], 'kind': ['episode']})
            self.assertFalse(entry.folder)
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(title)
            tag.setMediaType.assert_called_once_with('episode')
            tag.setTvShowTitle.assert_called_once_with(TITLE)
            tag.setSeason.assert_called_once_with(2)
            if number is None:
                tag.setEpisode.assert_not_called()
            else:
                tag.setEpisode.assert_called_once_with(number)
            tag.setYear.assert_not_called()
            tag.setPremiered.assert_not_called()
            entry.item.setArt.assert_called_once_with({
                'icon': 'DefaultTVShows.png', 'thumb': STILL, 'fanart': BACKGROUND})
            entry.item.setProperty.assert_called_once_with('IsPlayable', 'true')
            self.assertIn(call.getVideoInfoTag().setTitle(title), entry.inserted)
            self.assertIn(call.setProperty('IsPlayable', 'true'), entry.inserted)
        self.assertEqual(entries[1].url,
                         'plugin://fixture/?action=play&asset=synthetic%2Fep%26%3F%3D2&kind=episode')
        self.assertEqual(assets, original)
        self.directory.setContent.assert_called_with(1, 'episodes')

    def test_unknown_folder_selects_missing_and_invalid_seasons_not_specials(self):
        missing = episode('missing', number=3)
        del missing['seasonNumber']
        self.inventory([episode('special', 0), missing, episode('null', None, 1),
                        episode('string-zero', '0', 2), episode('boolean', True, 4)])
        folders = self.route({'action': 'seasons', 'asset': SERIES_ID})
        self.assertEqual([entry.label for entry in folders], ['Specials', 'Other episodes'])
        entries = self.route(folders[1].url)
        self.assertEqual([entry.query['asset'][0] for entry in entries],
                         ['null', 'string-zero', 'missing', 'boolean'])
        for entry in entries:
            entry.item.getVideoInfoTag.return_value.setSeason.assert_not_called()
        self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — Other episodes')
        special, = self.route(folders[0].url)
        self.assertEqual(special.query['asset'], ['special'])
        special.item.getVideoInfoTag.return_value.setSeason.assert_called_once_with(0)
        self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — Specials')

    def test_season_pagination_round_trips_identity_offsets_and_clean_title_without_gaps(self):
        assets = [episode('synthetic-' + str(i), number=i) for i in reversed(range(1, 66))]
        self.inventory(assets + [episode('other-season', 10)])
        route = {'action': 'season_episodes', 'asset': SERIES_ID, 'season': '02', 'title': '<b>Stale</b>'}
        seen = []
        for offset, count, previous, following in [(0, 30, None, 30), (30, 30, 0, 60), (60, 5, 30, None)]:
            entries = self.route(route)
            playable = [entry for entry in entries if not entry.folder]
            self.assertEqual(len(playable), count)
            seen.extend(entry.query['asset'][0] for entry in playable)
            controls = [entry for entry in entries if entry.folder]
            self.assertEqual([int(entry.query['offset'][0]) for entry in controls],
                             [value for value in (previous, following) if value is not None])
            for entry in controls:
                target = int(entry.query['offset'][0])
                self.assertEqual(entry.query, {
                    'action': ['season_episodes'], 'asset': [SERIES_ID], 'season': ['02'],
                    'title': [TITLE], 'offset': [str(target)]})
                icon = 'DefaultFolderBack.png' if target < offset else 'DefaultFolder.png'
                entry.item.setArt.assert_called_once_with({'icon': icon, 'thumb': icon})
                tag = entry.item.getVideoInfoTag.return_value
                tag.setTitle.assert_called_once_with(entry.label)
                tag.setPlot.assert_called_once_with('label-30036' if target < offset else 'label-30037')
                tag.setMediaType.assert_not_called()
                entry.item.setProperty.assert_not_called()
            if following is not None:
                route = next(entry.url for entry in controls if entry.query['offset'] == [str(following)])
        self.assertEqual(seen, ['synthetic-' + str(i) for i in range(1, 66)])
        self.assertEqual(self.client.series.call_args_list, [call(SERIES_ID)] * 3)
        self.assertEqual(self.client.episode_inventory.call_args_list, [call(SERIES_ID)] * 3)
        self.client.episodes.assert_not_called()

    def test_malformed_season_or_offset_fails_before_constructing_public_client(self):
        bad_seasons = ['', '-1', '+1', '1.5', ' 1', '１', 'Unknown', '100001', '9' * 40]
        bad_offsets = ['-1', '+1', '1.5', ' 1', '１２', '1000001', '9' * 40]
        cases = [({'season': value, 'offset': '0'}, 'season') for value in bad_seasons]
        cases += [({'season': '2', 'offset': value}, 'page') for value in bad_offsets]
        for parameters, message in cases:
            with self.subTest(parameters=parameters):
                self.factory.reset_mock()
                self.assertEqual(self.route(dict(action='season_episodes', asset=SERIES_ID, **parameters),
                                            succeeds=False), [])
                self.factory.assert_not_called()
                self.assertEqual(self.client.method_calls, [])
                self.assertEqual(self.dialog.ok.call_args.args[1],
                                 'Invalid catalog {}. Return to the previous listing.'.format(message))

    def test_capped_inventory_offers_only_all_episodes_and_legacy_route_still_pages_by_30(self):
        self.inventory([episode('synthetic-' + str(i), season=i % 3, number=i)
                        for i in range(300)], complete=False)
        for action in ('seasons', 'season_episodes'):
            with self.subTest(action=action):
                entry, = self.route({'action': action, 'asset': SERIES_ID, 'season': '2'})
                self.assertEqual(entry.label, 'All episodes')
                self.assertEqual(entry.query, {'action': ['episodes'], 'asset': [SERIES_ID], 'title': [TITLE]})
                self.assertTrue(entry.folder)
                tag = entry.item.getVideoInfoTag.return_value
                tag.setTitle.assert_called_once_with('All episodes')
                tag.setPlot.assert_called_once_with('label-30035')
                tag.setMediaType.assert_not_called()
                self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — Browse all episodes by page')
        self.client.episodes.return_value = service.catalog_page(
            {'items': [episode('legacy-' + str(i), number=i) for i in range(31)]}, 0)
        entries = self.route(entry.url)
        self.assertEqual(len([item for item in entries if not item.folder]), 30)
        self.assertEqual(entries[0].label, 'Synthetic episode')
        self.assertEqual(entries[-1].query, {
            'action': ['episodes'], 'asset': [SERIES_ID], 'title': [TITLE], 'offset': ['30']})
        self.client.episodes.assert_called_once_with(SERIES_ID, 0)
        self.assertEqual(self.client.series.call_count, 2)
        self.assertEqual(self.client.episode_inventory.call_count, 2)

    def test_menu_drilldown_cleans_html_and_uses_files_and_native_folder_icons(self):
        root = self.route()
        browse = next(entry for entry in root if entry.query['action'] == ['browse'])
        browse.item.setArt.assert_called_once_with({'icon': 'DefaultAddonVideo.png', 'thumb': 'DefaultAddonVideo.png'})
        self.factory.assert_not_called()
        self.client.menus.return_value = [
            None, {'reference': False},
            {'reference': 'synthetic/page&1', 'label': ' <b>Food &amp; Travel</b>\r\n menu '},
        ]
        menu, = self.route(browse.url)
        self.assertEqual(menu.label, 'Food & Travel menu')
        self.assertEqual(menu.query, {'action': ['page'], 'page': ['synthetic/page&1'], 'title': ['Food & Travel menu']})
        self.directory.setContent.assert_called_once_with(1, 'files')
        self.client.sections.return_value = [
            {'playlistId': None}, {'playlistId': 'synthetic/list+1', 'label': '<i>Curated</i>\t&amp; more'},
        ]
        section, = self.route(menu.url)
        self.assertEqual(section.label, 'Curated & more')
        self.assertEqual(section.query, {
            'action': ['playlist'], 'playlist': ['synthetic/list+1'], 'title': ['Curated & more']})
        self.directory.setPluginCategory.assert_called_with(1, 'Food & Travel menu')
        self.directory.setContent.assert_called_once_with(1, 'files')
        self.directory.setPluginFanart.assert_called_once_with(1)
        for entry in (menu, section):
            self.assertTrue(entry.folder)
            entry.item.setArt.assert_called_once_with({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(entry.label)
            tag.setPlot.assert_called_once_with('label-30033')
            tag.setMediaType.assert_not_called()
        self.client.menus.assert_called_once_with()
        self.client.sections.assert_called_once_with('synthetic/page&1')

    def test_mixed_curated_playlist_keeps_order_and_unnumbered_clean_labels(self):
        assets = [episode('ten', 10, 10, '<b>Ten</b>\n&amp; first'),
                  dict(episode('movie'), type='movie'), dict(series(), id='show'),
                  episode('one', 1, 1), dict(episode('clip'), type='clip'),
                  dict(episode('channel'), type='channel')]
        original = deepcopy(assets)
        self.client.playlist.return_value = service.catalog_page({'items': assets}, 0)
        entries = self.route({'action': 'playlist', 'playlist': 'synthetic-curated'})
        self.assertEqual([entry.query['asset'][0] for entry in entries],
                         ['ten', 'movie', 'show', 'one', 'clip', 'channel'])
        self.assertEqual([entry.folder for entry in entries], [False, False, True, False, False, False])
        self.assertEqual(entries[0].label, 'Ten & first')
        entries[0].item.getVideoInfoTag.return_value.setTitle.assert_called_once_with('Ten & first')
        self.assertEqual(entries[3].label, 'Synthetic episode')
        self.assertEqual(assets, original)
        self.directory.setContent.assert_called_with(1, 'videos')
        self.client.series.assert_not_called()
        self.client.episode_inventory.assert_not_called()

    def test_empty_or_filtered_complete_inventory_uses_heading_without_fallback_folder(self):
        for assets in ([], [None, {}, episode(False), {'type': 'movie', 'id': 'unsupported'}]):
            with self.subTest(assets=assets):
                self.inventory(assets)
                self.assertEqual(self.route({'action': 'seasons', 'asset': SERIES_ID}), [])
                self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — No items on this page')
                self.directory.setContent.assert_called_with(1, 'seasons')

    def test_empty_selected_season_retains_previous_link_and_clear_heading(self):
        self.inventory([episode('different-season', 10)])
        for offset in (0, 60):
            with self.subTest(offset=offset):
                entries = self.route({'action': 'season_episodes', 'asset': SERIES_ID,
                                      'season': '2', 'title': TITLE, 'offset': offset})
                self.directory.setPluginCategory.assert_called_with(1, TITLE + ' — Season 2 — No items on this page')
                self.directory.setContent.assert_called_with(1, 'episodes')
                self.assertEqual(len(entries), 0 if offset == 0 else 1)
                if entries:
                    self.assertTrue(entries[0].folder)
                    self.assertEqual(entries[0].query, {
                        'action': ['season_episodes'], 'asset': [SERIES_ID], 'season': ['2'],
                        'title': [TITLE], 'offset': ['30']})

    def test_unsupported_playlist_keeps_both_pagination_links_and_uses_heading_not_toast(self):
        assets = [{'type': 'collection', 'id': 'unsupported-' + str(i)} for i in range(31)]
        self.client.playlist.return_value = service.catalog_page({'items': assets}, 30)
        entries = self.route({'action': 'playlist', 'playlist': 'synthetic-list',
                              'title': '<b>Public &amp; curated</b>\r\n', 'offset': 30})
        self.assertEqual([entry.query['offset'] for entry in entries], [['0'], ['60']])
        for entry in entries:
            self.assertTrue(entry.folder)
            self.assertEqual(entry.query['action'], ['playlist'])
            self.assertEqual(entry.query['playlist'], ['synthetic-list'])
            self.assertEqual(entry.query['title'], ['Public & curated'])
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(entry.label)
            tag.setPlot.assert_called_once()
            tag.setMediaType.assert_not_called()
        self.directory.setPluginCategory.assert_called_with(1, 'Public & curated — No supported items on this page')
        self.directory.setContent.assert_called_with(1, 'videos')

    def test_untrusted_parent_art_never_becomes_fanart_or_replaces_episode_still(self):
        for url in ('http://assets.tastemadecdn.net/synthetic/background.jpg',
                    BACKGROUND + '?token=SYNTHETIC_PRIVATE', 'https://synthetic.invalid/background.jpg'):
            with self.subTest(url=url):
                self.client.series.return_value = dict(series(), images={'background': [{'url': url}]})
                self.inventory([episode('synthetic-episode')])
                entry, = self.route({'action': 'season_episodes', 'asset': SERIES_ID, 'season': '2'})
                self.directory.setPluginFanart.assert_called_once_with(1)
                entry.item.setArt.assert_called_once_with({
                    'icon': 'DefaultTVShows.png', 'thumb': STILL, 'fanart': STILL})


class PresentationClientTests(unittest.TestCase):
    def setUp(self):
        forbid(self, service, 'fetch')
        forbid(self, service, 'json_request')
        # Bypass bootstrap entirely; only the method under test may use this fake get.
        self.client = object.__new__(service.Client)
        self.client.get = MagicMock()
        for name in ('login', 'post', 'graphql', 'set_token'):
            forbid(self, self.client, name)

    def test_series_requests_encoded_public_path_and_accepts_only_dictionary_responses(self):
        for response in (series(), {}, {'unrecognized': 'synthetic'}):
            with self.subTest(response=response):
                self.client.get.reset_mock()
                self.client.get.return_value = response
                self.assertIs(self.client.series('synthetic/id &?'), response)
                self.client.get.assert_called_once_with('/media/series/synthetic%2Fid%20%26%3F')
        for response in (None, [], 'synthetic-not-an-object', False, 7):
            with self.subTest(response=response):
                self.client.get.return_value = response
                with self.assertRaisesRegex(service.ServiceError, '^Unexpected series response\\.'):
                    self.client.series('synthetic')

    def test_inventory_requests_size_300_and_full_response_is_never_complete(self):
        self.assertEqual(service.SERIES_INVENTORY_LIMIT, 300)
        for count in (0, 1, 299, 300):
            with self.subTest(count=count):
                assets = [episode('synthetic-' + str(i)) for i in range(count)]
                self.client.get.reset_mock()
                self.client.get.return_value = {'items': assets}
                result = self.client.episode_inventory('synthetic/id &?')
                self.client.get.assert_called_once_with(
                    '/media/series/synthetic%2Fid%20%26%3F/episodes', {'offset': 0, 'size': 300})
                self.assertEqual(set(result), {'items', 'complete'})
                self.assertIs(result['items'], assets)
                self.assertIs(result['complete'], count < 300)

    def test_inventory_totals_and_server_caps_prevent_false_completeness(self):
        cases = [
            (20, {'total': 20}, True), (20, {'total': 21}, False),
            (299, {'total': 300}, False), (300, {'total': 300}, False),
            (20, {'size': 20}, False), (20, {'size': 10, 'total': 20}, False),
            (19, {'size': 20}, True), (0, {'size': 20, 'total': 1}, False),
            (20, {'size': 300, 'total': 20}, True),
        ]
        for count, fields, complete in cases:
            with self.subTest(count=count, fields=fields):
                self.client.get.reset_mock()
                self.client.get.return_value = dict(
                    items=[episode('synthetic-' + str(i)) for i in range(count)], **fields)
                result = self.client.episode_inventory('synthetic')
                self.assertIs(result['complete'], complete)
                self.assertEqual(len(result['items']), count)
                self.client.get.assert_called_once_with(
                    '/media/series/synthetic/episodes', {'offset': 0, 'size': 300})

    def test_inventory_never_claims_a_nonzero_or_malformed_offset_complete(self):
        for offset in [30, -1, True, '0', None]:
            with self.subTest(offset=offset):
                self.client.get.return_value = {'items': [episode('synthetic')], 'offset': offset}
                with self.assertRaises(service.ServiceError):
                    self.client.episode_inventory('synthetic')

    def test_inventory_rejects_malformed_shapes_records_and_more_than_300_items(self):
        responses = [None, [], {}, {'items': None}, {'items': {}}, {'items': ()},
                     {'items': [None]}, {'items': [episode('synthetic'), 'not-an-asset']},
                     {'items': [episode('synthetic-' + str(i)) for i in range(301)]}]
        for index, response in enumerate(responses):
            with self.subTest(index=index):
                self.client.get.reset_mock()
                self.client.get.return_value = response
                with self.assertRaisesRegex(service.ServiceError, '^Unexpected episode'):
                    self.client.episode_inventory('synthetic')
                self.client.get.assert_called_once_with(
                    '/media/series/synthetic/episodes', {'offset': 0, 'size': 300})


if __name__ == '__main__':
    unittest.main()
