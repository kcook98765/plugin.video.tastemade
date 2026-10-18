"""Navigation contract regressions; synthetic catalogues and mocked Kodi only."""
from copy import deepcopy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.parse import parse_qs, urlencode, urlsplit

import test_hardening as fixtures
import service


LABELS = {
    30003: 'Settings', 30004: 'Verify login', 30005: 'Browse',
    30007: 'Next page', 30008: 'Untitled', 30009: 'Unable to load this page.',
    30013: 'Sign out', 30014: 'Previous page',
    30015: 'No items on this page', 30016: 'No supported items on this page',
    30017: 'Seasons', 30018: 'Season {}', 30019: 'Other episodes',
    30020: 'All episodes', 30021: 'Browse all episodes by page', 30024: 'Specials',
    30025: 'VOD', 30026: 'Live TV',
    30027: 'Browse the video-on-demand catalogue.',
    30028: 'Choose a live channel to watch.',
    30029: 'Browse the public catalogue without signing in.',
    30030: 'Open add-on settings.',
    30031: 'Verify your existing account login.',
    30032: 'Sign out of this Kodi profile.',
    30033: 'Browse {}.', 30034: '{} episodes',
    30035: 'Browse all episodes when a complete season list is unavailable.',
    30036: 'Return to the previous page.', 30037: 'Continue to the next page.',
    30038: '1 episode', 30039: 'Browse seasons and episodes.',
}
LIVE_LAYOUT_ERROR = 'Live TV channel layout changed. Try Browse again.'
PAGE_ERROR = 'Invalid catalog page. Return to the previous listing.'
LIVE_PAGE = 'synthetic/live-page'
LIVE_PLAYLIST = 'synthetic/live-playlist'
SERIES_ID = 'synthetic/series'
SERIES_TITLE = 'Public & Travel'
BACKGROUND = 'https://assets.tastemadecdn.net/synthetic/navigation/background.jpg'
POSTER = 'https://assets.tastemadecdn.net/synthetic/navigation/poster.jpg'
STILL = 'https://assets.tastemadecdn.net/synthetic/navigation/channel.jpg'


def forbid(test, target, name):
    """Also detect prohibited calls swallowed by plugin.run's error handler."""
    patcher = patch.object(target, name, side_effect=AssertionError('Unexpected ' + name))
    mocked = patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(mocked.assert_not_called)
    return mocked


def series():
    return {
        'id': SERIES_ID, 'type': 'series', 'label': '<b>Public &amp; Travel</b>\r\n',
        'description': '<p>Series &amp; overview.</p>',
        'year': 2020, 'releaseDate': '2020-01-01',
        'seasonNumber': 9, 'episodeNumber': 8,
        'images': {'background': [{'url': BACKGROUND}], 'poster': [{'url': POSTER}]},
    }


def episode(asset_id, season=2, number=1):
    return {
        'id': asset_id, 'type': 'episode',
        'label': '<b>Episode &amp; {}</b>\r\n'.format(number),
        'seasonNumber': season, 'episodeNumber': number,
    }


def four_channels():
    """Observed page -> one playlist -> four channel types; all values synthetic."""
    return [
        {
            'id': 'synthetic-channel-' + str(number), 'type': 'channel',
            'label': '<b>Channel &amp; {}</b>\r\n'.format(number),
            'description': '<p>Live &amp; public channel {}.</p>'.format(number),
            'images': {'still': [{'url': STILL}], 'background': [{'url': BACKGROUND}]},
        }
        for number in range(1, 5)
    ]


class NavigationRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)
        self.labels = dict(LABELS)
        self.addon.getLocalizedString.side_effect = lambda number: self.labels.get(
            number, 'label-' + str(number))
        self.directory = self.modules['xbmcplugin']
        self.modules['xbmc'].log = MagicMock()
        self.modules['xbmc'].LOGWARNING = object()
        for name in ('fetch', 'json_request', 'build_opener'):
            forbid(self, service, name)
        for name in ('SessionStore', 'authenticated_client', 'ensure_inputstream',
                     'checked_live_url', 'vod_playback_path'):
            forbid(self, self.plugin, name)
        forbid(self, self.modules['xbmcvfs'], 'translatePath')
        for name in ('getSetting', 'getSettingBool', 'openSettings'):
            forbid(self, self.addon, name)
        self.client = MagicMock(spec=service.Client)
        for name in ('get', 'request', '_request', 'post', 'graphql', 'login',
                     'set_token', 'resolve'):
            forbid(self, self.client, name)
        self.client.series.return_value = series()
        self.client.episode_inventory.return_value = {'items': [], 'complete': True}
        factory = patch.object(self.plugin, 'Client', return_value=self.client)
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.modules['xbmcgui'].ListItem.side_effect = self.new_item
        self.directory.addDirectoryItem.side_effect = self.capture

    def tearDown(self):
        self.modules['xbmc'].executebuiltin.assert_not_called()
        self.directory.setResolvedUrl.assert_not_called()
        self.dialog.yesno.assert_not_called()
        self.assertNotIn(call('profile'), self.addon.getAddonInfo.call_args_list)

    def new_item(self, label):
        item = MagicMock(spec=['getVideoInfoTag', 'setArt', 'setProperty', 'setLabel2'])
        item.label = label
        item.getVideoInfoTag.return_value = MagicMock(spec=[
            'setTitle', 'setPlot', 'setMediaType', 'setPlotOutline', 'setTvShowTitle',
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

    def assert_help_folder(self, entry, summary, icon='DefaultFolder.png'):
        self.assertTrue(entry.folder)
        tag = entry.item.getVideoInfoTag.return_value
        self.assertCountEqual(tag.method_calls, [call.setTitle(entry.label), call.setPlot(summary)])
        entry.item.setProperty.assert_not_called()
        entry.item.setLabel2.assert_not_called()
        entry.item.setArt.assert_called_once_with({'icon': icon, 'thumb': icon})
        self.assertIn(call.getVideoInfoTag().setTitle(entry.label), entry.inserted)
        self.assertIn(call.getVideoInfoTag().setPlot(summary), entry.inserted)

    def test_root_keeps_four_offline_rows_with_help_and_native_folder_icons(self):
        entries = self.route()
        self.assertEqual([entry.label for entry in entries],
                         ['Settings', 'Verify login', 'Browse', 'Sign out'])
        for entry, action, summary_id, icon in zip(entries,
                ['settings', 'login', 'browse', 'logout'], [30030, 30031, 30029, 30032],
                ['icons/settings.png', 'icons/settings/profiles.png',
                 'DefaultAddonVideo.png', 'DefaultUser.png']):
            self.assertEqual(entry.query, {'action': [action]})
            self.assert_help_folder(entry, LABELS[summary_id], icon)
        self.factory.assert_not_called()
        self.assertEqual(self.client.method_calls, [])
        self.directory.setContent.assert_called_once_with(1, 'files')

    def test_browse_aliases_clean_english_labels_with_localized_titles_and_no_discovery(self):
        self.labels.update({30025: 'Catalogue VOD', 30026: 'Télévision en direct'})
        menus = [
            None, {'reference': False, 'label': 'Home'},
            {'reference': 'synthetic/menu-live', 'label': ' <b>hOmE</b>\r\n'},
            {'reference': 'synthetic/menu-home', 'label': ' <i>lIvE&nbsp; nOw</i>\n'},
            {'reference': 'Home', 'label': '<b>Food &amp; Travel</b>\t menu'},
            {'reference': 'synthetic/extra-home', 'label': 'Home recipes'},
            {'reference': 'synthetic/extra-live', 'label': 'Live Now highlights'},
        ]
        original = deepcopy(menus)
        self.client.menus.return_value = menus
        entries = self.route({'action': 'browse'})
        expected = [
            ('Catalogue VOD', 'page', 'synthetic/menu-live', LABELS[30027]),
            ('Télévision en direct', 'live', 'synthetic/menu-home', LABELS[30028]),
            ('Food & Travel menu', 'page', 'Home', 'Browse Food & Travel menu.'),
            ('Home recipes', 'page', 'synthetic/extra-home', 'Browse Home recipes.'),
            ('Live Now highlights', 'page', 'synthetic/extra-live', 'Browse Live Now highlights.'),
        ]
        self.assertEqual(len(entries), len(expected))
        for entry, (label, action, page, summary) in zip(entries, expected):
            self.assertEqual(entry.label, label)
            self.assertEqual(entry.query, {'action': [action], 'page': [page], 'title': [label]})
            self.assert_help_folder(entry, summary)
        self.assertEqual(self.client.method_calls, [call.menus()])
        self.factory.assert_called_once_with()
        self.directory.setContent.assert_called_once_with(1, 'files')
        self.assertEqual(menus, original)

    def test_page_section_folders_have_clean_localized_help_without_playlist_fetches(self):
        self.client.sections.return_value = [
            {'playlistId': None},
            {'playlistId': 'synthetic/curated', 'label': '<i>Curated &amp; new</i>\r\n'},
            {'playlistId': 0, 'label': ' <b>Zero</b> '},
        ]
        entries = self.route({'action': 'page', 'page': 'synthetic/vod-page', 'title': 'VOD'})
        self.assertEqual([entry.label for entry in entries], ['Curated & new', 'Zero'])
        for entry, identifier in zip(entries, ['synthetic/curated', '0']):
            self.assertEqual(entry.query, {
                'action': ['playlist'], 'playlist': [identifier], 'title': [entry.label]})
            self.assert_help_folder(entry, LABELS[30033].format(entry.label))
        self.assertEqual(self.client.method_calls, [call.sections('synthetic/vod-page')])
        self.directory.setPluginCategory.assert_called_with(1, 'VOD')

    def test_live_route_lists_four_playable_channels_directly_with_metadata_and_art(self):
        assets = four_channels()
        original = deepcopy(assets)
        self.client.live_channels.return_value = service.catalog_page({'items': assets}, 0)
        entries = self.route({'action': 'live', 'page': LIVE_PAGE, 'title': 'Stale heading'})
        self.assertEqual(len(entries), 4)
        self.assertEqual([entry.label for entry in entries],
                         ['Channel & ' + str(number) for number in range(1, 5)])
        for entry, asset in zip(entries, assets):
            self.assertFalse(entry.folder)
            self.assertEqual(entry.query, {
                'action': ['play'], 'asset': [asset['id']], 'kind': ['channel']})
            entry.item.setProperty.assert_called_once_with('IsPlayable', 'true')
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(entry.label)
            tag.setPlot.assert_called_once_with(
                'Live & public channel {}.'.format(asset['id'].rsplit('-', 1)[1]))
            tag.setMediaType.assert_called_once_with('video')
            for name in ('setSeason', 'setEpisode', 'setYear', 'setPremiered', 'setDuration'):
                getattr(tag, name).assert_not_called()
            entry.item.setArt.assert_called_once_with({
                'icon': 'DefaultMovies.png', 'thumb': STILL, 'fanart': BACKGROUND})
            self.assertIn(call.setProperty('IsPlayable', 'true'), entry.inserted)
            self.assertIn(call.getVideoInfoTag().setTitle(entry.label), entry.inserted)
        self.assertEqual(self.client.method_calls, [call.live_channels(LIVE_PAGE, 0)])
        self.directory.setContent.assert_called_with(1, 'videos')
        self.directory.setPluginCategory.assert_called_with(1, LABELS[30026])
        self.assertEqual(assets, original)

    def test_live_filters_nonchannels_but_round_trips_raw_offsets_page_and_title(self):
        assets = [{'id': 'unsupported-' + str(number), 'type': kind}
                  for number, kind in enumerate(
                      ['series', 'episode', 'movie', 'clip', 'collection', 'future'] * 5 + ['channel'])]
        assets[1] = four_channels()[0]
        assets[29] = four_channels()[1]
        assets[30] = four_channels()[2]  # Lookahead must not be rendered on this page.
        assets[8] = {'id': False, 'type': 'channel', 'label': 'Invalid identity'}
        first = service.catalog_page({'items': assets}, 30)
        last = service.catalog_page({'items': [assets[30]]}, 60)
        original = deepcopy(assets)
        self.client.live_channels.side_effect = [first, last, first]
        entries = self.route({'action': 'live', 'page': LIVE_PAGE, 'title': LABELS[30026], 'offset': 30})
        self.assertEqual([entry.query['asset'][0] for entry in entries if not entry.folder],
                         ['synthetic-channel-1', 'synthetic-channel-2'])
        controls = [entry for entry in entries if entry.folder]
        self.assertEqual([entry.query['offset'] for entry in controls], [['0'], ['60']])
        for entry, offset, summary, icon in zip(controls, ['0', '60'],
                [LABELS[30036], LABELS[30037]], ['DefaultFolderBack.png', 'DefaultFolder.png']):
            self.assertEqual(entry.query, {
                'action': ['live'], 'page': [LIVE_PAGE], 'title': [LABELS[30026]], 'offset': [offset]})
            self.assert_help_folder(entry, summary, icon)
        later = self.route(controls[-1].url)
        self.assertEqual([entry.query['asset'][0] for entry in later if not entry.folder],
                         ['synthetic-channel-3'])
        previous, = [entry for entry in later if entry.folder]
        self.assertEqual(previous.query, {
            'action': ['live'], 'page': [LIVE_PAGE], 'title': [LABELS[30026]], 'offset': ['30']})
        back = self.route(previous.url)
        self.assertEqual([entry.url for entry in back], [entry.url for entry in entries])
        self.assertEqual(self.client.method_calls, [
            call.live_channels(LIVE_PAGE, 30), call.live_channels(LIVE_PAGE, 60),
            call.live_channels(LIVE_PAGE, 30)])
        self.assertEqual(assets, original)

    def test_live_unsupported_and_empty_pages_keep_controls_and_explain_the_empty_heading(self):
        unsupported = [{'id': 'synthetic-' + str(number), 'type': 'series'} for number in range(31)]
        self.client.live_channels.side_effect = [
            service.catalog_page({'items': unsupported}, 30),
            service.catalog_page({'items': []}, 60),
        ]
        entries = self.route({'action': 'live', 'page': LIVE_PAGE, 'title': LABELS[30026], 'offset': 30})
        self.assertEqual([entry.query['offset'] for entry in entries], [['0'], ['60']])
        for entry, summary, icon in zip(entries, [LABELS[30036], LABELS[30037]],
                                       ['DefaultFolderBack.png', 'DefaultFolder.png']):
            self.assert_help_folder(entry, summary, icon)
            self.assertEqual(entry.query['action'], ['live'])
            self.assertEqual(entry.query['page'], [LIVE_PAGE])
            self.assertEqual(entry.query['title'], [LABELS[30026]])
        self.directory.setPluginCategory.assert_called_with(
            1, 'Live TV — No supported items on this page')
        previous, = self.route(entries[-1].url)
        self.assertEqual(previous.query['offset'], ['30'])
        self.assert_help_folder(previous, LABELS[30036], 'DefaultFolderBack.png')
        self.directory.setPluginCategory.assert_called_with(1, 'Live TV — No items on this page')
        self.directory.setContent.assert_called_with(1, 'videos')
        self.assertEqual(self.client.method_calls,
                         [call.live_channels(LIVE_PAGE, 30), call.live_channels(LIVE_PAGE, 60)])

    def test_live_invalid_route_offsets_fail_before_constructing_the_client(self):
        for offset in ['-1', '+1', '1.5', ' 1', '1 ', '１２', '1000001', '9' * 40]:
            with self.subTest(offset=offset):
                self.factory.reset_mock()
                self.assertEqual(self.route(
                    {'action': 'live', 'page': LIVE_PAGE, 'offset': offset}, succeeds=False), [])
                self.factory.assert_not_called()
                self.assertEqual(self.client.method_calls, [])
                self.dialog.ok.assert_called_once_with('Fixture', PAGE_ERROR)

    def test_metadata_series_folders_keep_existing_plot_or_receive_generic_season_help(self):
        assets = [series(), dict(series(), id='synthetic/no-description', description='', shortDescription='')]
        original = deepcopy(assets)
        self.client.playlist.return_value = service.catalog_page({'items': assets}, 0)
        entries = self.route({'action': 'playlist', 'playlist': 'synthetic/vod'})
        self.assertEqual(len(entries), 2)
        for entry, asset, plot in zip(entries, assets, ['Series & overview.', LABELS[30039]]):
            self.assertTrue(entry.folder)
            self.assertEqual(entry.label, SERIES_TITLE)
            self.assertEqual(entry.query, {
                'action': ['seasons'], 'asset': [asset['id']], 'title': [SERIES_TITLE]})
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(SERIES_TITLE)
            tag.setPlot.assert_called_once_with(plot)
            tag.setMediaType.assert_called_once_with('tvshow')
            tag.setEpisode.assert_not_called()
            entry.item.setProperty.assert_not_called()
            entry.item.setArt.assert_called_once_with({
                'icon': 'DefaultTVShows.png', 'thumb': BACKGROUND, 'poster': POSTER, 'fanart': BACKGROUND})
            self.assertIn(call.getVideoInfoTag().setPlot(plot), entry.inserted)
        self.assertEqual(self.client.method_calls, [call.playlist('synthetic/vod', 0)])
        self.assertEqual(assets, original)

    def test_season_counts_use_actual_group_sizes_as_secondary_labels_not_episode_metadata(self):
        assets = [episode('ten-a', 10, 2), episode('two-a', 2, 99), episode('unknown-a', None, 3),
                  episode('one', 1, 999), episode('special', 0, 8), episode('two-b', 2, 70),
                  episode('unknown-b', '2', 1), episode('ten-b', 10, 10), episode('two-c', 2, 2),
                  episode(False, 2, 1000), {'type': 'movie', 'id': 'not-an-episode'}, None]
        original = deepcopy(assets)
        self.client.episode_inventory.return_value = {'items': assets, 'complete': True}
        entries = self.route({'action': 'seasons', 'asset': SERIES_ID, 'title': 'Stale title'})
        self.assertEqual([entry.label for entry in entries],
                         ['Specials', 'Season 1', 'Season 2', 'Season 10', 'Other episodes'])
        for entry, number, count in zip(entries, [0, 1, 2, 10, None], [1, 1, 3, 2, 2]):
            self.assertTrue(entry.folder)
            self.assertEqual(entry.query, {
                'action': ['season_episodes'], 'asset': [SERIES_ID],
                'season': ['unknown' if number is None else str(number)], 'title': [SERIES_TITLE]})
            secondary = LABELS[30038] if count == 1 else LABELS[30034].format(count)
            entry.item.setLabel2.assert_called_once_with(secondary)
            tag = entry.item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once_with(entry.label)
            tag.setTvShowTitle.assert_called_once_with(SERIES_TITLE)
            tag.setMediaType.assert_called_once_with('season')
            tag.setPlot.assert_called_once_with('Series & overview.')
            if number is None:
                tag.setSeason.assert_not_called()
            else:
                tag.setSeason.assert_called_once_with(number)
            for name in ('setEpisode', 'setYear', 'setPremiered', 'setDuration'):
                getattr(tag, name).assert_not_called()
            entry.item.setProperty.assert_not_called()
            entry.item.setArt.assert_called_once_with({
                'icon': 'DefaultFolderSquare.png', 'thumb': BACKGROUND, 'poster': POSTER, 'fanart': BACKGROUND})
            self.assertIn(call.setLabel2(secondary), entry.inserted)
        self.assertEqual(self.client.method_calls,
                         [call.series(SERIES_ID), call.episode_inventory(SERIES_ID)])
        self.directory.setPluginCategory.assert_called_with(1, SERIES_TITLE + ' — Seasons')
        self.assertEqual(assets, original)

    def test_season_episode_numbering_keeps_clean_native_titles_and_pagination_help(self):
        assets = [episode('synthetic-episode-' + str(number), number=number)
                  for number in reversed(range(1, 66))]
        self.client.episode_inventory.return_value = {'items': assets, 'complete': True}
        entries = self.route({'action': 'season_episodes', 'asset': SERIES_ID, 'season': '2', 'offset': 30})
        playable = [entry for entry in entries if not entry.folder]
        self.assertEqual(len(playable), 30)
        for entry, number in zip(playable, range(31, 61)):
            title = 'Episode & ' + str(number)
            self.assertEqual(entry.label, '{:02d}. {}'.format(number, title))
            entry.item.getVideoInfoTag.return_value.setTitle.assert_called_once_with(title)
            entry.item.getVideoInfoTag.return_value.setEpisode.assert_called_once_with(number)
            entry.item.setLabel2.assert_not_called()
            self.assertEqual(entry.query, {
                'action': ['play'], 'asset': ['synthetic-episode-' + str(number)], 'kind': ['episode']})
        controls = [entry for entry in entries if entry.folder]
        self.assertEqual(len(controls), 2)
        for entry, offset, summary, icon in zip(controls, ['0', '60'],
                [LABELS[30036], LABELS[30037]], ['DefaultFolderBack.png', 'DefaultFolder.png']):
            self.assertEqual(entry.query, {
                'action': ['season_episodes'], 'asset': [SERIES_ID], 'season': ['2'],
                'title': [SERIES_TITLE], 'offset': [offset]})
            self.assert_help_folder(entry, summary, icon)
        self.assertEqual(self.client.method_calls,
                         [call.series(SERIES_ID), call.episode_inventory(SERIES_ID)])

    def test_incomplete_inventory_all_episodes_fallback_has_help_on_both_season_routes(self):
        self.client.episode_inventory.return_value = {
            'items': [episode('synthetic-' + str(number), number=number) for number in range(300)],
            'complete': False,
        }
        for action in ('seasons', 'season_episodes'):
            with self.subTest(action=action):
                entry, = self.route({'action': action, 'asset': SERIES_ID, 'season': '2'})
                self.assertEqual(entry.label, LABELS[30020])
                self.assertEqual(entry.query, {
                    'action': ['episodes'], 'asset': [SERIES_ID], 'title': [SERIES_TITLE]})
                self.assert_help_folder(entry, LABELS[30035])
                self.directory.setPluginCategory.assert_called_with(
                    1, SERIES_TITLE + ' — ' + LABELS[30021])
        self.assertEqual(self.client.method_calls,
                         [call.series(SERIES_ID), call.episode_inventory(SERIES_ID)] * 2)


class LiveChannelClientTests(unittest.TestCase):
    def setUp(self):
        for name in ('fetch', 'json_request', 'build_opener'):
            forbid(self, service, name)
        # Never bootstrap the public client or load account/profile state.
        self.client = object.__new__(service.Client)
        self.client.get = MagicMock()
        for name in ('request', '_request', 'login', 'post', 'graphql', 'set_token', 'resolve'):
            forbid(self, self.client, name)

    def assert_layout_error(self):
        with self.assertRaises(service.ServiceError) as raised:
            self.client.live_channels(LIVE_PAGE)
        self.assertEqual(str(raised.exception), LIVE_LAYOUT_ERROR)

    def test_discovery_deduplicates_identical_valid_ids_and_calls_one_playlist_at_validated_offset(self):
        result = service.catalog_page({'items': four_channels()}, 30)
        for identifier in [LIVE_PLAYLIST, 0, 7]:
            with self.subTest(identifier=identifier), \
                    patch.object(self.client, 'sections', return_value=[
                        {'playlistId': identifier, 'label': 'Live Channels'},
                        {'playlistId': identifier, 'label': 'Same playlist, different presentation'},
                    ]) as sections, \
                    patch.object(self.client, 'playlist', return_value=result) as playlist:
                order = MagicMock()
                order.attach_mock(sections, 'sections')
                order.attach_mock(playlist, 'playlist')
                self.assertIs(self.client.live_channels(LIVE_PAGE, '000030'), result)
                self.assertEqual(order.mock_calls,
                                 [call.sections(LIVE_PAGE), call.playlist(identifier, 30)])
                self.client.get.assert_not_called()

    def test_real_section_discovery_and_playlist_keep_four_channels_and_existing_page_caps(self):
        cases = [
            (LIVE_PLAYLIST, 0, {'items': four_channels(), 'total': 4, 'offset': 0, 'size': 31}),
            (0, 0, {'items': four_channels()}),
            (LIVE_PLAYLIST, 40, {'items': [{'id': str(i), 'type': 'channel'} for i in range(20)],
                                   'size': 20, 'offset': 40, 'total': 95}),
            (LIVE_PLAYLIST, 30, {'items': [{'id': str(i), 'type': 'channel'} for i in range(31)]}),
            (LIVE_PLAYLIST, 30, {'items': [{'id': str(i), 'type': 'channel'} for i in range(30)]}),
            (LIVE_PLAYLIST, 60, {'items': [], 'total': 95}),
        ]
        for identifier, offset, response in cases:
            with self.subTest(identifier=identifier, offset=offset, count=len(response['items'])):
                raw_sections = [{'type': 'playlist', 'label': 'Live Channels', 'playlistId': identifier}]
                self.client.get.reset_mock()
                self.client.get.side_effect = [raw_sections, response]
                original = deepcopy((raw_sections, response))
                result = self.client.live_channels(LIVE_PAGE, offset)
                self.assertEqual(result, service.catalog_page(response, offset))
                path = '/playlists/' + ('synthetic%2Flive-playlist' if identifier == LIVE_PLAYLIST else '0')
                self.assertEqual(self.client.get.call_args_list, [
                    call('/pages/synthetic%2Flive-page', {'includeItems': 'false'}),
                    call(path, {'offset': offset, 'size': service.PAGE_SIZE + 1}),
                ])
                self.assertEqual((raw_sections, response), original)

    def test_missing_multiple_or_malformed_section_layouts_use_one_fixed_error_without_crawling(self):
        valid = {'playlistId': LIVE_PLAYLIST}
        layouts = [None, {}, '', False, (), [None], ['not-a-section'], [False], [7], [[]], [{}],
                   [valid, {'playlistId': 'synthetic/another-playlist'}]]
        for identifier in [None, '', ' \t ', True, False, -1, 1.5, [], {}]:
            layouts.append([{'playlistId': identifier}])
            layouts.append([valid, {'playlistId': identifier}])
        with patch.object(self.client, 'sections') as sections, \
                patch.object(self.client, 'playlist') as playlist:
            for index, layout in enumerate(layouts):
                with self.subTest(source='sections', case=index):
                    sections.reset_mock()
                    sections.return_value = layout
                    self.assert_layout_error()
                    sections.assert_called_once_with(LIVE_PAGE)
                    playlist.assert_not_called()
                    self.client.get.assert_not_called()
        # Exercise the real sections() adapter too: malformed get() responses
        # must not leak AttributeError/TypeError past the advertised ServiceError.
        raw_layouts = [None, {}, 'not-a-page', False, [], [None], ['not-a-section'],
                       [{'playlistId': []}], [{'playlistId': {}}]]
        with patch.object(self.client, 'playlist') as playlist:
            for index, layout in enumerate(raw_layouts):
                with self.subTest(source='get', case=index):
                    self.client.get.reset_mock()
                    self.client.get.return_value = layout
                    self.assert_layout_error()
                    self.client.get.assert_called_once_with(
                        '/pages/synthetic%2Flive-page', {'includeItems': 'false'})
                    playlist.assert_not_called()

    def test_playlist_shape_size_and_offset_errors_are_bounded_service_failures(self):
        responses = [None, [], {}, {'items': None}, {'items': ['not-an-asset']},
                     {'items': [{'id': str(i), 'type': 'channel'} for i in range(32)]},
                     {'items': [], 'offset': 0}, {'items': [], 'size': -1}, {'items': [], 'size': True}]
        with patch.object(self.client, 'sections', return_value=[{'playlistId': LIVE_PLAYLIST}]) as sections, \
                patch.object(self.client, 'playlist', wraps=self.client.playlist) as playlist:
            for index, response in enumerate(responses):
                with self.subTest(case=index):
                    sections.reset_mock()
                    playlist.reset_mock()
                    self.client.get.reset_mock()
                    self.client.get.return_value = response
                    with self.assertRaises(service.ServiceError):
                        self.client.live_channels(LIVE_PAGE, 30)
                    sections.assert_called_once_with(LIVE_PAGE)
                    playlist.assert_called_once_with(LIVE_PLAYLIST, 30)
                    self.client.get.assert_called_once_with(
                        '/playlists/synthetic%2Flive-playlist', {'offset': 30, 'size': service.PAGE_SIZE + 1})

    def test_invalid_offsets_fail_before_sections_playlist_or_any_request(self):
        offsets = [None, True, False, -1, 1000001, 1.5, [], {}, '', '-1', '+1',
                   '1.5', ' 1', '1 ', '１２', '1000001', '9' * 40]
        with patch.object(self.client, 'sections') as sections, \
                patch.object(self.client, 'playlist') as playlist:
            for index, offset in enumerate(offsets):
                with self.subTest(case=index), self.assertRaises(service.ServiceError) as raised:
                    self.client.live_channels(LIVE_PAGE, offset)
                self.assertEqual(str(raised.exception), PAGE_ERROR)
                sections.assert_not_called()
                playlist.assert_not_called()
                self.client.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
