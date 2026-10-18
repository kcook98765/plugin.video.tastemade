"""Synthetic catalogue metadata and mocked Kodi; no network/account access."""
from copy import deepcopy
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import test_hardening as fixtures
from catalog_metadata import (
    DEFAULT_ICON, DEFAULT_ICONS, DEFAULT_POSTER, DEFAULT_THUMB, MEDIA_TYPES,
    catalog_metadata, clean_description, clean_label,
)
from service import catalog_page


IMAGE = 'https://assets.tastemadecdn.net/fixture/still.jpg'
POSTER = 'https://assets.tastemadecdn.net/fixture/poster.jpg'
BACKGROUND = 'https://assets.tastemadecdn.net/fixture/background.jpg'
EMPTY_EPISODE_ART = {'icon': 'DefaultTVShows.png', 'thumb': 'DefaultTVShows.png'}


def episode():
    return {
        'id': 'fixture-episode', 'type': 'episode', 'label': 'Fixture episode',
        'description': 'A synthetic full description.',
        'shortDescription': 'A synthetic outline.', 'seriesName': 'Fixture show',
        'seasonNumber': 1, 'episodeNumber': 3, 'year': 2024,
        'releaseDate': '2024-07-04', 'genres': [{'label': 'Food'}],
        'images': {'still': [{'url': IMAGE, 'size': {'width': 1280, 'height': 720}}]},
    }


class CleanTextTests(unittest.TestCase):
    def test_malformed_optional_declaration_cannot_fail_the_directory(self):
        self.assertEqual(clean_description('<![bogus]>'), '')
        self.assertEqual(clean_label('<![bogus]>', 'Fallback'), 'Fallback')
        with patch('catalog_metadata._PlainText.feed', side_effect=AssertionError('synthetic parser failure')):
            self.assertEqual(clean_description('synthetic text'), '')

    def test_label_decodes_entities_strips_markup_and_collapses_whitespace(self):
        self.assertEqual(clean_label(' <b>Food &amp; Travel</b>\r\n\t&nbsp; today '),
                         'Food & Travel today')
        self.assertEqual(clean_label('&lt;b&gt;A&#39;s &quot;show&quot;&lt;/b&gt;'),
                         'A\'s "show"')

    def test_label_fallback_is_also_cleaned_and_bounded(self):
        for value in [None, False, 12, {}, [], '', ' \r\n ', '<br>', '<script>bad</script>']:
            with self.subTest(value=value):
                self.assertEqual(clean_label(value, ' <i>Fallback</i>\r\ntitle '), 'Fallback title')
        self.assertEqual(clean_label(None, None), '')
        self.assertEqual(len(clean_label(None, 'x' * 2000)), 1024)

    def test_controls_removed_including_c1_format_and_surrogates(self):
        value = 'A\x00\x01\x7f\x80\x9f\u200b\u202e\ud800 B'
        self.assertEqual(clean_label(value), 'A B')
        self.assertEqual(clean_description(value), 'A B')
        self.assertEqual(clean_label('A&#9; B&#10;C&#13;D'), 'A B C D')

    def test_description_keeps_paragraphs_and_line_breaks(self):
        self.assertEqual(clean_description('<p>First &amp; best.</p><p>Next<br>line.</p>'),
                         'First & best.\n\nNext\nline.')
        self.assertEqual(clean_description('<div>First</div><div>Second</div>'),
                         'First\n\nSecond')

    def test_description_normalizes_crlf_cr_and_blank_lines(self):
        self.assertEqual(clean_description(' first\r\nsecond\rthird\n\n\n\n last\t word '),
                         'first\nsecond\nthird\n\nlast word')
        self.assertEqual(clean_description('first\u0085second\u2028third\u2029last'),
                         'first\nsecond\nthird\n\nlast')
        self.assertEqual(clean_description('first&#13;&#10;second&#13;third'),
                         'first\nsecond\nthird')

    def test_script_style_comments_and_attributes_are_not_visible_text(self):
        value = ('<p title="not text">Before</p><!-- hidden -->'
                 '<SCRIPT>if (2 < 3) { hidden(); }</SCRIPT>'
                 '<style>body { content: "hidden"; }</style><p>After</p>')
        self.assertEqual(clean_description(value), 'Before\n\nAfter')
        self.assertEqual(clean_label(value), 'Before After')
        self.assertEqual(clean_description('Visible<script>never closed'), 'Visible')
        self.assertEqual(clean_description('Visible<style>never closed'), 'Visible')
        self.assertEqual(clean_label('<script/><style/>Visible'), 'Visible')

    def test_literal_less_than_comparisons_are_not_treated_as_markup(self):
        for value in ['2 < 3 and 5 > 4', '2 &lt; 3 and 5 &gt; 4', 'Cost < 3', '2 < 3\n4 > 1']:
            with self.subTest(value=value):
                expected = value.replace('&lt;', '<').replace('&gt;', '>')
                self.assertEqual(clean_description(value), expected)
                self.assertEqual(clean_label(value), expected.replace('\n', ' '))

    def test_nonstring_descriptions_are_empty(self):
        for value in [None, False, 12, {}, []]:
            with self.subTest(value=value):
                self.assertEqual(clean_description(value), '')

    def test_clean_text_bounds_apply_after_markup_cleanup(self):
        self.assertEqual(clean_label('<b>' + 'x' * 2000 + '</b>'), 'x' * 1024)
        self.assertEqual(clean_description('<p>' + 'x' * 20000 + '</p>'), 'x' * 16384)
        self.assertEqual(clean_label(' <b> </b> ', '<i> </i>'), '')


class MetadataTests(unittest.TestCase):
    def metadata(self, **fields):
        asset = episode()
        asset.update(fields)
        return catalog_metadata(asset, 'Unknown title')

    def test_episode_fields_from_raw_catalogue_not_normalized_title(self):
        result = self.metadata(title='Not the verified field', series='opaque-relationship')
        self.assertEqual(result.title, 'Fixture episode')
        self.assertEqual(result.show_title, 'Fixture show')
        self.assertEqual((result.season, result.episode), (1, 3))
        self.assertEqual(result.genres, ['Food'])

    def test_minimal_asset_has_title_and_correct_media_type(self):
        for kind, expected, icon in [('series', 'tvshow', 'DefaultTVShows.png'),
                                     ('season', 'season', 'DefaultFolderSquare.png'),
                                     ('episode', 'episode', 'DefaultTVShows.png'),
                                     ('movie', 'movie', 'DefaultMovies.png'),
                                     ('clip', 'video', 'DefaultMovies.png'),
                                     ('channel', 'video', 'DefaultMovies.png'),
                                     ('unknown', 'video', 'DefaultMovies.png')]:
            with self.subTest(kind=kind):
                result = catalog_metadata({'type': kind, 'label': 'Fixture'}, 'Unknown title')
                self.assertEqual(result.title, 'Fixture')
                self.assertEqual(result.media_type, expected)
                expected_art = {'icon': icon, 'thumb': 'DefaultTVShows.png'}
                if kind in ('series', 'season'):
                    expected_art['poster'] = 'DefaultVideo.png'
                self.assertEqual(result.art, expected_art)
                self.assertEqual(result.plot, '')
                self.assertIsNone(result.year)

    def test_missing_null_and_nonstring_titles_use_localized_fallback(self):
        for label in [None, '', '  ', [], {}, 12, False]:
            with self.subTest(label=label):
                self.assertEqual(self.metadata(label=label).title, 'Unknown title')

    def test_short_description_is_plot_fallback(self):
        for description in [None, '', [], {}]:
            result = self.metadata(description=description)
            self.assertEqual(result.plot, 'A synthetic outline.')
        self.assertEqual(self.metadata(description=None, shortDescription=None).plot, '')

    def test_text_is_bounded_and_controls_do_not_reach_kodi(self):
        result = self.metadata(label=' A\x00 title\x7f ', description='x' * 20000,
                               shortDescription='line\nsecond\tword\x01')
        self.assertEqual(result.title, 'A title')
        self.assertEqual(len(result.plot), 16384)
        self.assertEqual(result.outline, 'line\nsecond word')
        self.assertEqual(len(self.metadata(label='x' * 2000).title), 1024)
        self.assertEqual(len(self.metadata(shortDescription='x' * 2000).outline), 1024)
        self.assertEqual(len(self.metadata(description=None, shortDescription='x' * 2000).plot), 1024)

    def test_all_public_text_fields_are_cleaned_without_inventing_values(self):
        result = self.metadata(label='<b>A &amp; B</b>\nshow', seriesName=' <i>Parent</i>\r\nshow ',
                               description='<p>2 &lt; 3</p><p>Second</p>',
                               shortDescription='<b>Short</b>\rline',
                               genres=[{'label': '<i>Food</i>'}, {'label': 'Food'},
                                       {'label': 'Food\n&amp;\tTravel'}])
        self.assertEqual(result.title, 'A & B show')
        self.assertEqual(result.show_title, 'Parent show')
        self.assertEqual(result.plot, '2 < 3\n\nSecond')
        self.assertEqual(result.outline, 'Short\nline')
        self.assertEqual(result.genres, ['Food', 'Food & Travel'])
        self.assertEqual(len(self.metadata(genres=[{'label': 'x' * 1000}]).genres[0]), 256)

    def test_optional_integer_fields_never_guess_strings_floats_or_booleans(self):
        for value in [True, False, '3', 3.5, None, [], {}, -1, 100001]:
            with self.subTest(value=value):
                result = self.metadata(seasonNumber=value, episodeNumber=value)
                self.assertIsNone(result.season)
                self.assertIsNone(result.episode)
        result = self.metadata(seasonNumber=0, episodeNumber=0)
        self.assertEqual((result.season, result.episode), (0, 0))
        for value in [True, '2024', 2024.0, -1, 999, 10000]:
            self.assertIsNone(self.metadata(year=value).year)

    def test_only_valid_iso_calendar_dates_are_set(self):
        self.assertEqual(self.metadata(releaseDate='2024-02-29').premiered, '2024-02-29')
        for value in ['2023-02-29', '2024-99-99', '20240704', '2024-7-4',
                      '2024-07-04T00:00:00Z', None, {}, 20240704]:
            with self.subTest(value=value):
                self.assertEqual(self.metadata(releaseDate=value).premiered, '')

    def test_genres_are_typed_deduplicated_and_bounded(self):
        result = self.metadata(genres=[{'label': 'Food'}, {'label': None}, None,
                                       {'label': ' Food '}, 'not-a-record', {'label': 'Travel'}])
        self.assertEqual(result.genres, ['Food', 'Travel'])
        self.assertEqual(len(self.metadata(genres=[{'label': str(i)} for i in range(100)]).genres), 32)
        for value in [None, {}, 'Food']:
            self.assertEqual(self.metadata(genres=value).genres, [])

    def test_non_episode_never_invents_episode_identity(self):
        result = self.metadata(type='movie')
        self.assertEqual(result.show_title, '')
        self.assertIsNone(result.season)
        self.assertIsNone(result.episode)
        self.assertEqual(self.metadata(type='series').show_title, 'Fixture episode')

    def test_duration_and_unknown_fields_are_not_guessed_or_forwarded(self):
        result = self.metadata(duration=2641, Authorization='SYNTHETIC_PRIVATE',
                               url='https://fixture.invalid/private')
        self.assertFalse(hasattr(result, 'duration'))
        self.assertNotIn('SYNTHETIC_PRIVATE', repr(result))
        self.assertNotIn('fixture.invalid', repr(result))

    def test_no_asset_mutation_and_no_shared_defaults(self):
        asset = episode()
        original = deepcopy(asset)
        catalog_metadata(asset, 'Fallback')
        self.assertEqual(asset, original)
        first = catalog_metadata({}, 'Fallback')
        first.art['thumb'] = IMAGE
        first.genres.append('Fixture')
        second = catalog_metadata({}, 'Fallback')
        self.assertEqual(second.art, {'icon': 'DefaultMovies.png', 'thumb': 'DefaultTVShows.png'})
        self.assertEqual(second.genres, [])

    def test_art_layouts_keep_portrait_and_landscape_separate(self):
        result = self.metadata(images={
            'poster': [{'url': POSTER, 'size': {'width': 600, 'height': 900}}],
            'still': [{'url': IMAGE, 'size': {'width': 1280, 'height': 720}}],
            'background': [{'url': BACKGROUND, 'size': {'width': 1920, 'height': 1080}}],
        })
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=IMAGE, poster=POSTER, fanart=BACKGROUND))
        self.assertNotIn('poster', self.metadata().art)

    def test_art_fallbacks_use_observed_layouts(self):
        result = self.metadata(images={
            'poster': [], 'heroPortrait': [{'url': POSTER}],
            'heroLandscape': [{'url': BACKGROUND}],
        })
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=BACKGROUND, poster=POSTER, fanart=BACKGROUND))

    def test_largest_valid_image_within_layout_not_assumed_array_order(self):
        result = self.metadata(images={'still': [
            {'url': IMAGE, 'size': {'width': 640, 'height': 360}},
            {'url': BACKGROUND, 'size': {'width': 1920, 'height': 1080}},
            {'url': POSTER, 'size': {'width': 320, 'height': 180}},
        ]})
        self.assertEqual(result.art['thumb'], BACKGROUND)

    def test_misoriented_image_skipped_for_correct_layout_fallback(self):
        result = self.metadata(images={
            'poster': [{'url': IMAGE, 'size': {'width': 1280, 'height': 720}}],
            'backgroundPortrait': [{'url': POSTER, 'size': {'width': 600, 'height': 900}}],
            'still': [{'url': POSTER, 'size': {'width': 600, 'height': 900}}],
            'background': [{'url': BACKGROUND, 'size': {'width': 1920, 'height': 1080}}],
        })
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=BACKGROUND, poster=POSTER, fanart=BACKGROUND))

    def test_missing_and_malformed_image_shapes_do_not_break_listing(self):
        for images in [None, [], 'not-an-object', {'still': IMAGE},
                       {'still': {'url': IMAGE}}, {'still': [None, 1, {}, {'url': None}]}]:
            with self.subTest(images=images):
                self.assertEqual(self.metadata(images=images).art, EMPTY_EPISODE_ART)
        self.assertEqual(self.metadata(images={'still': [{'url': IMAGE, 'size': None}]}).art['thumb'], IMAGE)

    def test_optional_malformed_dimensions_do_not_invalidate_safe_image_url(self):
        for size in [None, {}, {'width': 1280}, {'height': 720},
                     {'width': True, 'height': 720}, {'width': '1280', 'height': '720'},
                     {'width': 0, 'height': -1}, {'width': 999999, 'height': 720}]:
            with self.subTest(size=size):
                result = self.metadata(images={'still': [{'url': IMAGE, 'size': size}]})
                self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=IMAGE, fanart=IMAGE))

    def test_valid_sized_record_preferred_to_dimensionless_fallback(self):
        result = self.metadata(images={'still': [
            {'url': IMAGE},
            {'url': BACKGROUND, 'size': {'width': 1920, 'height': 1080}},
        ]})
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=BACKGROUND, fanart=BACKGROUND))

    def test_untrusted_secret_or_protocol_option_art_is_never_forwarded(self):
        bad_urls = [
            'http://assets.tastemadecdn.net/fixture.jpg',
            'https://fixture.invalid/image.jpg',
            'https://assets.tastemadecdn.net.evil.invalid/image.jpg',
            'https://assets.tastemadecdn.net@fixture.invalid/image.jpg',
            'https://user:password@assets.tastemadecdn.net/image.jpg',
            IMAGE + '?token=SYNTHETIC_PRIVATE', IMAGE + '?', IMAGE + '#fragment',
            IMAGE + '|Authorization=SYNTHETIC_PRIVATE', IMAGE + '%7cHeader=value',
            IMAGE + '%0d%0aHeader:value', IMAGE + '\\escape', IMAGE + '\n',
            IMAGE + '%20suffix', '//assets.tastemadecdn.net/image.jpg',
            'special://profile/private.jpg', '/storage/private.jpg',
            'https://assets.tastemadecdn.net:8443/image.jpg',
            'https://assets.tastemadecdn.net:bad/image.jpg',
            'https://[invalid/image.jpg', 'https://assets.tastemadecdn.net/',
            'https://assets.tastemadecdn.net/' + 'x' * 4096,
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                self.assertEqual(self.metadata(images={'still': [{'url': url}]}).art, EMPTY_EPISODE_ART)

    def test_invalid_art_skipped_without_discarding_safe_later_record(self):
        result = self.metadata(images={'still': [
            {'url': 'https://fixture.invalid/unsafe.jpg'}, {'url': IMAGE},
        ]})
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=IMAGE, fanart=IMAGE))

    def test_image_records_are_bounded(self):
        result = self.metadata(images={'still': [{}] * 32 + [{'url': IMAGE}]})
        self.assertEqual(result.art, EMPTY_EPISODE_ART)

    def test_builtin_constants_are_verified_estuary_textures(self):
        self.assertEqual(MEDIA_TYPES['season'], 'season')
        self.assertEqual(DEFAULT_THUMB, 'DefaultTVShows.png')
        self.assertEqual(DEFAULT_POSTER, 'DefaultVideo.png')
        self.assertEqual(DEFAULT_ICON, 'DefaultMovies.png')
        self.assertEqual(DEFAULT_ICONS, {'series': 'DefaultTVShows.png',
                                        'season': 'DefaultFolderSquare.png',
                                        'episode': 'DefaultTVShows.png',
                                        'movie': 'DefaultMovies.png'})

    def test_portrait_is_never_a_thumbnail_or_fanart_fallback(self):
        for kind in ['series', 'season', 'episode', 'movie', 'clip', 'channel']:
            with self.subTest(kind=kind):
                result = self.metadata(type=kind, images={'poster': [{'url': POSTER}]})
                self.assertEqual(result.art['poster'], POSTER)
                self.assertEqual(result.art['thumb'], 'DefaultTVShows.png')
                self.assertNotIn('fanart', result.art)

    def test_generic_portrait_only_for_series_and_seasons(self):
        for kind in ['series', 'season', 'episode', 'movie', 'clip', 'channel', 'unknown']:
            with self.subTest(kind=kind):
                result = self.metadata(type=kind, images={})
                self.assertEqual('poster' in result.art, kind in ('series', 'season'))
                self.assertNotIn('fanart', result.art)

    def test_series_uses_own_art_then_fixed_never_parent_art(self):
        parent = {'images': {'background': [{'url': BACKGROUND}], 'poster': [{'url': POSTER}]}}
        result = catalog_metadata({'type': 'series', 'label': 'Own',
                                   'images': {'still': [{'url': IMAGE}]}}, 'Fallback', parent)
        self.assertEqual(result.art, {'icon': 'DefaultTVShows.png', 'thumb': IMAGE,
                                      'poster': 'DefaultVideo.png', 'fanart': IMAGE})
        result = catalog_metadata({'type': 'series'}, 'Fallback', parent)
        self.assertEqual(result.art, {'icon': 'DefaultTVShows.png', 'thumb': 'DefaultTVShows.png',
                                      'poster': 'DefaultVideo.png'})

    def test_season_inherits_parent_art_per_role_after_own_art(self):
        parent = {'type': 'series', 'images': {'background': [{'url': BACKGROUND}],
                                              'poster': [{'url': POSTER}]}}
        asset = {'type': 'season', 'images': {'still': [{'url': IMAGE}]}}
        result = catalog_metadata(asset, 'Season', parent)
        self.assertEqual(result.art, {'icon': 'DefaultFolderSquare.png', 'thumb': IMAGE,
                                      'poster': POSTER, 'fanart': IMAGE})
        result = catalog_metadata({'type': 'season'}, 'Season', parent)
        self.assertEqual(result.art, {'icon': 'DefaultFolderSquare.png', 'thumb': BACKGROUND,
                                      'poster': POSTER, 'fanart': BACKGROUND})
        result = catalog_metadata({'type': 'season', 'images': {'poster': [{'url': IMAGE}]}},
                                  'Season', parent)
        self.assertEqual(result.art['poster'], IMAGE)
        self.assertEqual(result.art['thumb'], BACKGROUND)

    def test_season_parent_portrait_does_not_leak_into_landscape_roles(self):
        result = catalog_metadata({'type': 'season'}, 'Season',
                                  {'images': {'poster': [{'url': POSTER}]}})
        self.assertEqual(result.art, {'icon': 'DefaultFolderSquare.png', 'thumb': 'DefaultTVShows.png',
                                      'poster': POSTER})

    def test_episode_keeps_still_and_prefers_parent_fanart_without_parent_poster(self):
        parent = {'images': {'background': [{'url': BACKGROUND}], 'poster': [{'url': POSTER}]}}
        result = catalog_metadata(episode(), 'Fallback', parent)
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=IMAGE, fanart=BACKGROUND))
        own = episode()
        own['images']['poster'] = [{'url': POSTER}]
        result = catalog_metadata(own, 'Fallback', parent)
        self.assertEqual(result.art['poster'], POSTER)
        self.assertEqual(result.art['thumb'], IMAGE)

    def test_episode_without_parent_background_preserves_own_still_fanart(self):
        for parent in [None, {}, {'images': {'poster': [{'url': POSTER}]}},
                       {'images': {'background': [{'url': 'https://fixture.invalid/unsafe.jpg'}]}}]:
            with self.subTest(parent=parent):
                result = catalog_metadata(episode(), 'Fallback', parent)
                self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, thumb=IMAGE, fanart=IMAGE))

    def test_parent_never_substitutes_for_missing_episode_thumbnail(self):
        result = catalog_metadata({'type': 'episode'}, 'Episode',
                                  {'images': {'background': [{'url': BACKGROUND}]}})
        self.assertEqual(result.art, dict(EMPTY_EPISODE_ART, fanart=BACKGROUND))
        self.assertNotIn('poster', result.art)

    def test_untrusted_parent_art_gets_same_security_checks_and_limits(self):
        for images in [{'background': [{'url': BACKGROUND + '?token=SYNTHETIC_PRIVATE'}]},
                       {'background': [{}] * 32 + [{'url': BACKGROUND}]},
                       {'poster': [{'url': 'special://profile/private.jpg'}]}, []]:
            with self.subTest(images=images):
                result = catalog_metadata({'type': 'season'}, 'Season', {'images': images})
                self.assertEqual(result.art, {'icon': 'DefaultFolderSquare.png',
                                              'thumb': 'DefaultTVShows.png', 'poster': 'DefaultVideo.png'})

    def test_malformed_optional_parent_is_ignored(self):
        for parent in [None, [], '', False, 123]:
            with self.subTest(parent=parent):
                result = catalog_metadata({'type': 'season'}, 'Season', parent)
                self.assertEqual(result.show_title, '')
                self.assertEqual(result.plot, '')
                self.assertNotIn('fanart', result.art)

    def test_season_identity_and_overview_can_use_raw_parent(self):
        parent = {'label': '<b>Parent</b>\nshow', 'description': '<p>Series &amp; overview.</p>',
                  'shortDescription': 'Short parent', 'year': 2020, 'releaseDate': '2020-01-01',
                  'seasonNumber': 9, 'episodeNumber': 8, 'duration': 999, 'genres': [{'label': 'Food'}]}
        result = catalog_metadata({'type': 'season', 'label': 'Second season', 'seasonNumber': 2},
                                  'Fallback', parent)
        self.assertEqual(result.show_title, 'Parent show')
        self.assertEqual(result.media_type, 'season')
        self.assertEqual(result.season, 2)
        self.assertEqual(result.plot, 'Series & overview.')
        self.assertEqual(result.outline, '')
        self.assertIsNone(result.episode)
        self.assertIsNone(result.year)
        self.assertEqual(result.premiered, '')
        self.assertEqual(result.genres, [])
        self.assertFalse(hasattr(result, 'duration'))

    def test_season_own_fields_take_precedence_and_are_not_guessed(self):
        parent = {'label': 'Parent', 'description': 'Parent overview', 'seasonNumber': 7}
        asset = {'type': 'season', 'seriesName': '<b>Own</b>\rseries', 'seasonNumber': 0,
                 'description': '<p>Own overview</p>', 'year': 2024, 'releaseDate': '2024-02-29',
                 'episodeNumber': 3}
        result = catalog_metadata(asset, 'Season', parent)
        self.assertEqual((result.show_title, result.season), ('Own series', 0))
        self.assertEqual(result.plot, 'Own overview')
        self.assertEqual((result.year, result.premiered), (2024, '2024-02-29'))
        self.assertIsNone(result.episode)
        for value in [None, True, '2', 2.5, -1, 100001]:
            with self.subTest(value=value):
                result = catalog_metadata(dict(asset, seasonNumber=value), 'Season', parent)
                self.assertIsNone(result.season)

    def test_season_short_description_precedes_parent_and_parent_short_is_last_resort(self):
        result = catalog_metadata({'type': 'season', 'shortDescription': '<i>Own short</i>'},
                                  'Season', {'description': 'Parent overview'})
        self.assertEqual(result.plot, 'Own short')
        result = catalog_metadata({'type': 'season'}, 'Season',
                                  {'description': '<style>hidden</style>', 'shortDescription': 'Parent &amp; short'})
        self.assertEqual(result.plot, 'Parent & short')

    def test_parent_does_not_invent_episode_identity_or_dates(self):
        parent = {'label': 'Parent', 'seriesName': 'Other', 'seasonNumber': 5, 'episodeNumber': 6,
                  'year': 2020, 'releaseDate': '2020-01-01', 'description': 'Parent plot'}
        result = catalog_metadata({'type': 'episode'}, 'Episode', parent)
        self.assertEqual(result.show_title, '')
        self.assertEqual(result.plot, '')
        self.assertIsNone(result.season)
        self.assertIsNone(result.episode)
        self.assertIsNone(result.year)
        self.assertEqual(result.premiered, '')

    def test_parent_and_asset_are_not_mutated_by_inheritance(self):
        asset = episode()
        parent = {'type': 'series', 'label': 'Parent', 'images': {'background': [{'url': BACKGROUND}]}}
        original_asset, original_parent = deepcopy(asset), deepcopy(parent)
        for kind in ['series', 'season', 'episode']:
            catalog_metadata(dict(asset, type=kind), 'Fallback', parent)
        self.assertEqual(asset, original_asset)
        self.assertEqual(parent, original_parent)


class MetadataRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.NavigationTests.setUp(self)
        self.listed = []
        self.modules['xbmcgui'].ListItem.side_effect = self.new_item
        self.modules['xbmcplugin'].addDirectoryItem.side_effect = self.capture

    def new_item(self, **kwargs):
        item = MagicMock(spec=['getVideoInfoTag', 'setArt', 'setProperty', 'setLabel2'])
        item.getVideoInfoTag.return_value = MagicMock(spec=[
            'setTitle', 'setMediaType', 'setPlot', 'setPlotOutline', 'setTvShowTitle',
            'setSeason', 'setEpisode', 'setYear', 'setPremiered', 'setGenres', 'setDuration',
        ])
        return item

    def capture(self, handle, url, item, isFolder):
        # Snapshot method calls at insertion, not after the route completes.
        self.listed.append((url, item, isFolder, list(item.mock_calls)))

    def route(self, assets, action='episodes', offset=0):
        with patch.object(self.plugin, 'Client') as client, \
                patch.object(self.plugin, 'SessionStore') as store, \
                patch.object(self.plugin, 'authenticated_client') as login, \
                patch.object(sys, 'argv', ['plugin://fixture/', '1',
                                          '?action={}&asset=fixture-series&playlist=fixture-list&offset={}'.format(action, offset)]):
            method = getattr(client.return_value, action)
            method.return_value = catalog_page({'items': assets}, offset)
            self.plugin.run()
        store.assert_not_called()
        login.assert_not_called()
        self.addon.getSetting.assert_not_called()
        self.modules['xbmcplugin'].setResolvedUrl.assert_not_called()
        self.modules['xbmcplugin'].endOfDirectory.assert_called_once_with(
            1, succeeded=True, cacheToDisc=False)
        return client

    def test_episode_info_and_art_exist_before_listing_without_resolving(self):
        client = self.route([episode()])
        url, item, folder, inserted_calls = self.listed[0]
        self.assertFalse(folder)
        tag = item.getVideoInfoTag.return_value
        tag.setTitle.assert_called_once_with('Fixture episode')
        tag.setMediaType.assert_called_once_with('episode')
        tag.setPlot.assert_called_once_with('A synthetic full description.')
        tag.setPlotOutline.assert_called_once_with('A synthetic outline.')
        tag.setTvShowTitle.assert_called_once_with('Fixture show')
        tag.setSeason.assert_called_once_with(1)
        tag.setEpisode.assert_called_once_with(3)
        tag.setYear.assert_called_once_with(2024)
        tag.setPremiered.assert_called_once_with('2024-07-04')
        tag.setGenres.assert_called_once_with(['Food'])
        item.setArt.assert_called_once_with(dict(EMPTY_EPISODE_ART, thumb=IMAGE, fanart=IMAGE))
        self.assertIn('getVideoInfoTag().setPlot', [call[0] for call in inserted_calls])
        self.assertIn('setArt', [call[0] for call in inserted_calls])
        item.setProperty.assert_called_once_with('IsPlayable', 'true')
        self.assertEqual(parse_qs(urlsplit(url).query), {
            'action': ['play'], 'asset': ['fixture-episode'], 'kind': ['episode']})
        self.assertEqual(client.return_value.method_calls[0][0], 'episodes')
        self.assertEqual(len(client.return_value.method_calls), 1)
        self.assertEqual(self.modules['xbmcplugin'].setContent.call_args.args, (1, 'episodes'))
        self.modules['xbmc'].executebuiltin.assert_not_called()

    def test_minimal_episode_still_has_native_info_title_and_no_fake_fields(self):
        self.route([{'id': 'fixture', 'type': 'episode', 'label': 'Minimal'}])
        tag = self.listed[0][1].getVideoInfoTag.return_value
        tag.setTitle.assert_called_once_with('Minimal')
        tag.setMediaType.assert_called_once_with('episode')
        self.assertEqual(len(tag.method_calls), 2)
        self.listed[0][1].setArt.assert_called_once_with(EMPTY_EPISODE_ART)

    def test_series_stays_browsable_movie_clip_and_channel_stay_playable(self):
        assets = [dict(episode(), type=kind, id='fixture-' + kind)
                  for kind in ['series', 'movie', 'clip', 'channel']]
        self.route(assets, action='playlist')
        for (url, item, folder, _), media_type in zip(self.listed, ['tvshow', 'movie', 'video', 'video']):
            item.getVideoInfoTag.return_value.setMediaType.assert_called_once_with(media_type)
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(set(query), {'action', 'asset', 'title'} if folder else {'action', 'asset', 'kind'})
            self.assertEqual(folder, media_type == 'tvshow')
            if folder:
                self.assertEqual(query['action'], ['seasons'])
                item.setProperty.assert_not_called()
            else:
                item.setProperty.assert_called_once_with('IsPlayable', 'true')
        self.assertEqual(self.modules['xbmcplugin'].setContent.call_args.args, (1, 'videos'))

    def test_pagination_controls_have_generic_icons_and_untyped_help(self):
        self.route([dict(episode(), id='fixture-' + str(i)) for i in range(31)], offset=30)
        self.assertEqual(len(self.listed), 32)
        for (url, item, folder, _), icon in zip((self.listed[0], self.listed[-1]),
                                               ('DefaultFolderBack.png', 'DefaultFolder.png')):
            self.assertTrue(folder)
            self.assertEqual(parse_qs(urlsplit(url).query)['action'], ['episodes'])
            tag = item.getVideoInfoTag.return_value
            tag.setPlot.assert_called_once()
            tag.setMediaType.assert_not_called()
            item.setProperty.assert_not_called()
            item.setArt.assert_called_once_with({'icon': icon, 'thumb': icon})

    def test_root_remains_offline_with_untyped_help_not_playable_video_metadata(self):
        with patch.object(self.plugin, 'Client') as client, \
                patch.object(self.plugin, 'SessionStore') as store, \
                patch.object(self.plugin, 'authenticated_client') as login, \
                patch.object(sys, 'argv', ['plugin://fixture/', '1', '']):
            self.plugin.run()
        client.assert_not_called()
        store.assert_not_called()
        login.assert_not_called()
        self.assertEqual(len(self.listed), 4)
        icons = {'settings': 'icons/settings.png', 'login': 'icons/settings/profiles.png',
                 'browse': 'DefaultAddonVideo.png', 'logout': 'DefaultUser.png'}
        for url, item, folder, _ in self.listed:
            self.assertTrue(folder)
            tag = item.getVideoInfoTag.return_value
            tag.setTitle.assert_called_once()
            tag.setPlot.assert_called_once()
            tag.setMediaType.assert_not_called()
            item.setProperty.assert_not_called()
            icon = icons[parse_qs(urlsplit(url).query)['action'][0]]
            item.setArt.assert_called_once_with({'icon': icon, 'thumb': icon})
        self.addon.getSetting.assert_not_called()
        self.modules['xbmc'].executebuiltin.assert_not_called()

    def test_optional_malformed_metadata_does_not_fail_directory_completion(self):
        asset = episode()
        asset.update(label=None, images=[], description={}, shortDescription=None,
                     genres=False, year=True, seasonNumber='1', releaseDate='invalid')
        self.route([asset])
        self.listed[0][1].getVideoInfoTag.return_value.setTitle.assert_called_once_with('label-30008')
        self.dialog.ok.assert_not_called()

    def test_duration_is_not_sent_to_kodi_until_its_units_are_verified(self):
        self.route([dict(episode(), duration=2641)])
        self.listed[0][1].getVideoInfoTag.return_value.setDuration.assert_not_called()


if __name__ == '__main__':
    unittest.main()
