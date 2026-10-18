"""Synthetic pure catalogue tests; no Kodi, profiles, or network access."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'resources' / 'lib'))

from catalogue import season_groups, season_number, season_page
from service import ServiceError


def episode(asset_id, season=1, number=1):
    return {'type': 'episode', 'id': asset_id, 'label': 'Synthetic episode',
            'seasonNumber': season, 'episodeNumber': number}


class SeasonNumberTests(unittest.TestCase):
    def test_ascii_routes_and_explicit_unknown(self):
        for value, expected in [('0', 0), ('1', 1), ('2', 2), ('10', 10),
                                ('000002', 2), ('100000', 100000), ('unknown', None)]:
            with self.subTest(value=value):
                self.assertEqual(season_number(value), expected)

    def test_internal_integers_are_supported_but_booleans_are_not(self):
        for value in [0, 1, 2, 10, 100000]:
            with self.subTest(value=value):
                self.assertEqual(season_number(value), value)
        for value in [True, False]:
            with self.subTest(value=value), self.assertRaises(ServiceError):
                season_number(value)

    def test_bad_routes_use_one_fixed_error_without_payloads(self):
        class Unprintable:
            def __str__(self):
                raise AssertionError('Input must not be formatted')

            __repr__ = __str__

        values = [None, -1, 100001, 10 ** 5000, 1.0, [], {}, Unprintable(), '',
                  '-1', '+1', '1.0', ' 1', '1 ', '1\n', '１２', '١', '²',
                  'Unknown', '100001', '1000000', '0000000', '9' * 5000,
                  '<b>SYNTHETIC_PRIVATE</b>']
        for index, value in enumerate(values):
            with self.subTest(index=index), self.assertRaises(ServiceError) as raised:
                season_number(value)
            self.assertEqual(str(raised.exception),
                             'Invalid catalog season. Return to the previous listing.')


class SeasonGroupsTests(unittest.TestCase):
    def test_seasons_and_episodes_are_numeric_not_lexical_or_label_order(self):
        items = [episode('{}-{}'.format(season, number), season, number)
                 for season in [10, 2, 1] for number in [10, 2, 1]]
        groups = season_groups(items)
        self.assertEqual([group['number'] for group in groups], [1, 2, 10])
        for group in groups:
            self.assertEqual(set(group), {'number', 'items', 'count'})
            self.assertEqual(group['count'], 3)
            self.assertEqual([item['episodeNumber'] for item in group['items']], [1, 2, 10])

    def test_missing_and_invalid_raw_seasons_stay_unknown_distinct_from_zero(self):
        invalid = [None, True, False, -1, 100001, '1', 'unknown', 1.0, [], {}]
        unknown = [episode('unknown-' + str(i), value) for i, value in enumerate(invalid)]
        missing = {'id': 'missing', 'type': 'episode', 'label': 'Season 5 Episode 9'}
        groups = season_groups(unknown + [missing, episode('special', 0),
                                         episode('last-number', 100000), episode('first', 1)])
        self.assertEqual([group['number'] for group in groups], [0, 1, 100000, None])
        self.assertEqual(groups[0]['items'][0]['id'], 'special')
        self.assertEqual(groups[-1]['count'], len(unknown) + 1)
        self.assertEqual(groups[-1]['items'], unknown + [missing])

    def test_episode_ties_and_unknown_numbers_keep_original_relative_order(self):
        invalid = [None, True, False, '2', -1, 100001, 2.0, [], {}]
        unknown = [episode('unknown-' + str(i), number=value)
                   for i, value in enumerate(invalid)]
        missing = {'id': 'missing', 'type': 'episode', 'seasonNumber': 1}
        items = [unknown[0], episode('ten', number=10), episode('tie-first', number=2),
                 episode('one', number=1), episode('tie-second', number=2),
                 episode('zero', number=0), episode('maximum', number=100000)]
        items += unknown[1:] + [missing]
        result = season_groups(items)[0]['items']
        self.assertEqual([item['id'] for item in result],
                         ['zero', 'one', 'tie-first', 'tie-second', 'ten', 'maximum'] +
                         [item['id'] for item in unknown] + ['missing'])

    def test_malformed_records_unsupported_types_and_invalid_ids_are_skipped(self):
        valid = [episode('opaque/id'), episode('0'), episode(0), episode(7), episode(10 ** 20)]
        bad_ids = [None, '', '   ', '\t\r\n', True, False, -1, 1.5, [], {}]
        records = [None, False, 3, 'not-a-record', [], {}, {'type': 'episode'}]
        records += [episode(value) for value in bad_ids]
        records += [dict(episode('unsupported'), type=kind)
                    for kind in [None, 'series', 'movie', 'clip', 'channel', 'Episode', [], {}]]
        result = season_groups(records + valid)
        self.assertEqual(result, [{'number': 1, 'items': valid, 'count': len(valid)}])

    def test_empty_or_malformed_inventory_is_empty(self):
        for items in [[], (), None, {}, 'not-an-inventory', False, 7]:
            with self.subTest(items=items):
                self.assertEqual(season_groups(items), [])
        item = episode('tuple')
        self.assertEqual(season_groups((item,))[0]['items'], [item])

    def test_curated_order_and_nested_payloads_are_never_mutated(self):
        curated = [episode('ten', 10, 10), episode('two', 2, 2),
                   episode('one-later', 1, 10), episode('one-first', 1, 1),
                   {'type': 'movie', 'id': 'curated-movie'}]
        curated[0]['extra'] = {'curated': ['z', 'a']}
        original = deepcopy(curated)
        groups = season_groups(curated)
        season_page(curated, '1', 0)
        self.assertEqual(curated, original)
        self.assertIs(groups[-1]['items'][0], curated[0])
        self.assertIsNot(groups[-1]['items'], curated)

    def test_inventory_is_not_capped_and_unknown_episodes_are_not_truncated(self):
        items = [episode(str(i), None, i) for i in reversed(range(335))]
        group = season_groups(items)[0]
        self.assertIsNone(group['number'])
        self.assertEqual(group['count'], 335)
        self.assertEqual([item['episodeNumber'] for item in group['items']], list(range(335)))
        page = season_page(items, 'unknown', 300)
        self.assertEqual([item['episodeNumber'] for item in page['items']], list(range(300, 330)))
        self.assertEqual(page['next_offset'], 330)


class SeasonPageTests(unittest.TestCase):
    def test_sorted_pages_use_lookahead_without_gaps_or_duplicates(self):
        items = [episode(str(i), 2, i) for i in reversed(range(65))]
        items += [episode('other-season', 10), episode('unknown-season', None)]
        pages = [season_page(items, '2', offset) for offset in ['0', '30', '60']]
        self.assertEqual([page['offset'] for page in pages], [0, 30, 60])
        self.assertEqual([page['previous_offset'] for page in pages], [None, 0, 30])
        self.assertEqual([page['next_offset'] for page in pages], [30, 60, None])
        self.assertEqual([len(page['items']) for page in pages], [30, 30, 5])
        self.assertEqual([item['episodeNumber'] for page in pages for item in page['items']],
                         list(range(65)))
        self.assertEqual(set(pages[0]), {'items', 'offset', 'previous_offset', 'next_offset'})

    def test_exact_multiple_has_no_empty_next_page(self):
        for count in [30, 60]:
            with self.subTest(count=count):
                items = [episode(str(i), number=i) for i in reversed(range(count))]
                page = season_page(items, 1, count - 30)
                self.assertEqual(len(page['items']), 30)
                self.assertIsNone(page['next_offset'])

    def test_unknown_route_selects_only_unknown_not_specials(self):
        missing = {'type': 'episode', 'id': 'missing'}
        items = [episode('special', 0), missing, episode('invalid', '0')]
        self.assertEqual(season_page(items, 'unknown', 0)['items'], [items[2], missing])
        self.assertEqual(season_page(items, '0', 0)['items'], [items[0]])

    def test_empty_first_and_later_pages_preserve_previous_links(self):
        for items in [[], [episode('different-season', 2)]]:
            for offset, previous in [(0, None), (5, 0), (30, 0), (60, 30), (1000000, 999970)]:
                with self.subTest(items=items, offset=offset):
                    self.assertEqual(season_page(items, '1', offset),
                                     {'items': [], 'offset': offset,
                                      'previous_offset': previous, 'next_offset': None})
        exhausted = season_page([episode('only')], '1', 60)
        self.assertEqual(exhausted, {'items': [], 'offset': 60,
                                     'previous_offset': 30, 'next_offset': None})

    def test_bad_route_or_offset_fails_before_reading_inventory(self):
        class UnreadableInventory(list):
            def __iter__(self):
                raise AssertionError('Invalid routes must fail before grouping')

        items = UnreadableInventory([episode('unused')])
        for value in [None, True, -1, '１２', '100001', 'SYNTHETIC_PRIVATE']:
            with self.subTest(season=value), self.assertRaises(ServiceError):
                season_page(items, value, 0)
        for offset in [None, True, -1, '-1', '', '1.5', '１２', '1000001', [], {}]:
            with self.subTest(offset=offset), self.assertRaises(ServiceError) as raised:
                season_page(items, '1', offset)
            self.assertEqual(str(raised.exception),
                             'Invalid catalog page. Return to the previous listing.')

    def test_helpers_do_not_fetch_or_report_provider_payloads(self):
        with patch('service.fetch', side_effect=AssertionError('Unexpected fetch')) as fetch, \
                patch('service.report') as report:
            self.assertEqual(season_number('1'), 1)
            self.assertEqual(season_groups([episode('SYNTHETIC_PRIVATE')])[0]['count'], 1)
            self.assertEqual(len(season_page([episode('SYNTHETIC_PRIVATE')], '1', 0)['items']), 1)
        fetch.assert_not_called()
        report.assert_not_called()


if __name__ == '__main__':
    unittest.main()
