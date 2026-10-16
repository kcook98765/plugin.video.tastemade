"""Synthetic catalog and mocked Kodi routing; no account or network access."""
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import test_hardening as fixtures
from service import Client, PAGE_SIZE, ServiceError, catalog_page, page_offset


def items(start, count, kind='episode'):
    return [{'id': str(i), 'type': kind, 'label': 'Fixture ' + str(i)}
            for i in range(start, start + count)]


class PaginationTests(unittest.TestCase):
    def test_unknown_total_lookahead_is_not_consumed(self):
        first = catalog_page({'items': items(0, 31)}, 0)
        second = catalog_page({'items': items(30, 31)}, 30)
        self.assertEqual(len(first['items']), 30)
        self.assertEqual(first['next_offset'], 30)
        self.assertEqual(second['items'][0]['id'], '30')
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
        self.assertIsNone(first['previous_offset'])
        self.assertEqual(second['previous_offset'], 0)
        self.assertEqual(second['next_offset'], 60)

    def test_exact_multiple_final_page_without_total(self):
        result = catalog_page({'items': items(30, 30)}, 30)
        self.assertIsNone(result['next_offset'])
        self.assertEqual(len(result['items']), 30)

    def test_short_final_page_without_total(self):
        result = catalog_page({'items': items(60, 5)}, 60)
        self.assertIsNone(result['next_offset'])
        self.assertEqual(result['previous_offset'], 30)

    def test_empty_first_and_later_pages_never_loop(self):
        first = catalog_page({'items': [], 'total': 999}, 0)
        later = catalog_page({'items': [], 'total': 999}, 60)
        self.assertIsNone(first['next_offset'])
        self.assertIsNone(first['previous_offset'])
        self.assertIsNone(later['next_offset'])
        self.assertEqual(later['previous_offset'], 30)

    def test_playlist_total_and_server_page_cap(self):
        result = catalog_page({'items': items(20, 20), 'total': 97, 'size': 20, 'offset': 20}, 20)
        self.assertEqual(result['next_offset'], 40)
        self.assertEqual(result['previous_offset'], 0)

    def test_known_total_final_page(self):
        result = catalog_page({'items': items(90, 7), 'total': 97, 'size': 31, 'offset': 90}, 90)
        self.assertIsNone(result['next_offset'])
        self.assertEqual(result['previous_offset'], 60)

    def test_stale_low_total_does_not_discard_lookahead(self):
        self.assertEqual(catalog_page({'items': items(0, 31), 'total': 9}, 0)['next_offset'], 30)

    def test_invalid_offsets_fail_before_catalog_request(self):
        for offset in [-1, '-1', 'wrong', '1.5', '1000001', True, None, '１２', '']:
            with self.subTest(offset=offset), self.assertRaises(ServiceError):
                page_offset(offset)
        self.assertEqual(page_offset('30'), 30)
        client = object.__new__(Client)
        client.get = MagicMock()
        with self.assertRaises(ServiceError):
            client.episodes('fixture', -1)
        client.get.assert_not_called()

    def test_malformed_response_and_wrong_offset_rejected(self):
        for response in [None, [], {}, {'items': None}, {'items': ['not-an-asset']},
                         {'items': items(0, 32)}, {'items': [], 'offset': 0},
                         {'items': [], 'size': -1}, {'items': [], 'size': True}]:
            with self.subTest(response_type=type(response).__name__), self.assertRaises(ServiceError):
                catalog_page(response, 30)

    def test_playlist_and_episode_requests_are_bounded_and_paginated(self):
        client = object.__new__(Client)
        client.get = MagicMock(return_value={'items': items(300, 31)})
        result = client.episodes('fixture', 300)
        self.assertEqual(result['next_offset'], 330)
        self.assertEqual(client.get.call_args.args, ('/media/series/fixture/episodes', {'offset': 300, 'size': PAGE_SIZE + 1}))
        client.get.reset_mock()
        client.get.return_value = {'items': items(30, 31)}
        client.playlist('fixture', 30)
        self.assertEqual(client.get.call_args.args, ('/playlists/fixture', {'offset': 30, 'size': PAGE_SIZE + 1}))


class PaginationRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)

    def route(self, query):
        with patch.object(sys, 'argv', ['plugin://fixture/', '1', query]):
            self.plugin.run()

    def urls(self):
        return [parse_qs(urlsplit(call.args[1]).query)
                for call in self.modules['xbmcplugin'].addDirectoryItem.call_args_list]

    def test_playlist_links_keep_playlist_identity_and_offset(self):
        result = catalog_page({'items': items(30, 31, 'series')}, 30)
        with patch.object(self.plugin, 'Client') as client:
            client.return_value.playlist.return_value = result
            self.route('?action=playlist&playlist=fixture-list&offset=30')
        urls = self.urls()
        self.assertEqual(len(urls), 32)
        self.assertEqual(urls[0], {'action': ['playlist'], 'playlist': ['fixture-list'], 'offset': ['0']})
        self.assertEqual(urls[-1], {'action': ['playlist'], 'playlist': ['fixture-list'], 'offset': ['60']})
        client.return_value.playlist.assert_called_once_with('fixture-list', 30)
        self.addon.getSetting.assert_not_called()

    def test_episode_links_keep_series_and_lookahead_boundary(self):
        result = catalog_page({'items': items(300, 31)}, 300)
        with patch.object(self.plugin, 'Client') as client:
            client.return_value.episodes.return_value = result
            self.route('?action=episodes&asset=fixture-series&offset=300')
        urls = self.urls()
        self.assertEqual(urls[0], {'action': ['episodes'], 'asset': ['fixture-series'], 'offset': ['270']})
        self.assertEqual(urls[-1], {'action': ['episodes'], 'asset': ['fixture-series'], 'offset': ['330']})
        self.assertEqual(urls[1]['asset'], ['300'])
        self.assertEqual(urls[-2]['asset'], ['329'])
        client.return_value.episodes.assert_called_once_with('fixture-series', 300)
        self.modules['xbmc'].executebuiltin.assert_not_called()

    def test_empty_page_preserves_previous_and_shows_safe_notification(self):
        with patch.object(self.plugin, 'Client') as client:
            client.return_value.episodes.return_value = catalog_page({'items': []}, 60)
            self.route('?action=episodes&asset=fixture-series&offset=60')
        self.assertEqual(len(self.urls()), 1)
        self.assertEqual(self.urls()[0]['offset'], ['30'])
        self.dialog.notification.assert_called_once_with('Fixture', 'No items on this page.')
        self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(1, succeeded=True, cacheToDisc=False)

    def test_bad_route_offset_does_not_request_network(self):
        with patch.object(self.plugin, 'Client') as client:
            self.route('?action=episodes&asset=fixture-series&offset=-1')
        client.assert_not_called()
        self.assertIn('Invalid catalog page', self.dialog.ok.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
