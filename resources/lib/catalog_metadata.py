"""Bounded public catalogue metadata; no requests, credentials or Kodi imports."""
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from html.parser import HTMLParser
import re
from typing import Dict, List, Optional
from unicodedata import category
from urllib.parse import unquote, urlsplit


MEDIA_TYPES = {'series': 'tvshow', 'season': 'season', 'episode': 'episode', 'movie': 'movie',
               'clip': 'video', 'channel': 'video'}
ART_LAYOUTS = {
    'thumb': ('still', 'heroLandscape', 'background'),
    'poster': ('poster', 'heroPortrait', 'backgroundPortrait'),
    'fanart': ('background', 'heroLandscape', 'still'),
}
# Verified Estuary textures on Nexus 20.5 and Omega 21.3, not add-on assets.
DEFAULT_ICON = 'DefaultMovies.png'
DEFAULT_ICONS = {
    'series': 'DefaultTVShows.png',
    'season': 'DefaultFolderSquare.png',
    'episode': 'DefaultTVShows.png',
    'movie': DEFAULT_ICON,
}
DEFAULT_THUMB = 'DefaultTVShows.png'
DEFAULT_POSTER = 'DefaultVideo.png'
LABEL_LIMIT = 1024
DESCRIPTION_LIMIT = 16384
OUTLINE_LIMIT = 1024
TEXT_INPUT_LIMIT = 65536


class _PlainText(HTMLParser):
    """Keep text/paragraph boundaries, omitting executable and style content."""

    _BLOCKS = frozenset(('p', 'div', 'section', 'article', 'blockquote', 'pre',
                         'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
                         'table', 'tr'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = ''

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            return
        if tag in ('script', 'style'):
            self.hidden = tag
        elif tag == 'br':
            self.parts.append('\n')
        elif tag in self._BLOCKS:
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden:
                self.hidden = ''
        elif tag in self._BLOCKS:
            self.parts.append('\n\n')

    def handle_startendtag(self, tag, attrs):
        if tag not in ('script', 'style'):
            self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain_text(value):
    if not isinstance(value, str):
        return ''
    # Bound parsing as well as output; decode encoded markup before parsing it.
    value = unescape(value[:TEXT_INPUT_LIMIT])
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    value = value.replace('\u0085', '\n').replace('\u2028', '\n').replace('\u2029', '\n\n')
    value = ''.join(c for c in value
                    if c in '\n\t' or category(c) not in ('Cc', 'Cf', 'Cs'))
    parser = _PlainText()
    try:
        parser.feed(value)
        parser.close()
    except (AssertionError, ValueError):
        # Malformed optional HTML must not invalidate the directory. Older
        # Kodi Python parsers can assert on unsupported declarations.
        return ''
    return ''.join(c for c in ''.join(parser.parts)
                   if c in '\n\t' or category(c) not in ('Cc', 'Cf', 'Cs'))


def clean_label(value, fallback='') -> str:
    """Return bounded single-line public text, including a cleaned fallback."""
    label = ' '.join(_plain_text(value).split())[:LABEL_LIMIT].rstrip()
    return label or ' '.join(_plain_text(fallback).split())[:LABEL_LIMIT].rstrip()


def clean_description(value) -> str:
    """Normalize HTML and CR/LF without losing literal comparisons/paragraphs."""
    lines = [' '.join(line.split()) for line in _plain_text(value).split('\n')]
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    return text[:DESCRIPTION_LIMIT].rstrip()


@dataclass
class CatalogMetadata:
    title: str
    media_type: str
    plot: str = ''
    outline: str = ''
    show_title: str = ''
    season: Optional[int] = None
    episode: Optional[int] = None
    year: Optional[int] = None
    premiered: str = ''
    genres: List[str] = field(default_factory=list)
    art: Dict[str, str] = field(default_factory=dict)


def _integer(value, minimum=0, maximum=100000):
    # JSON booleans are not episode numbers or years. Do not guess conversions.
    return value if type(value) is int and minimum <= value <= maximum else None


def _premiered(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return ''
    try:
        date.fromisoformat(value)
    except ValueError:
        return ''
    return value


def _image_url(value):
    """Only observed public artwork CDN URLs may reach Kodi's image loader.

    Never forward API headers or accept native protocol options, signed/query
    URLs, account URLs, local paths, or arbitrary provider-returned hosts.
    """
    if not isinstance(value, str) or not value or len(value) > 4096:
        return ''
    decoded = unquote(value)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '|\\' for c in decoded):
        return ''
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or parts.hostname != 'assets.tastemadecdn.net'
                or parts.port not in (None, 443) or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or parts.path in ('', '/') or '?' in value or '#' in value):
            return ''
    except ValueError:
        return ''
    return value


def _layout_image(images, layout):
    records = images.get(layout)
    if not isinstance(records, list):
        return ''
    best_url = ''
    best_area = -1
    for record in records[:32]:
        if not isinstance(record, dict):
            continue
        url = _image_url(record.get('url'))
        if not url:
            continue
        size = record.get('size')
        width = _integer(size.get('width'), 1, 32768) if isinstance(size, dict) else None
        height = _integer(size.get('height'), 1, 32768) if isinstance(size, dict) else None
        area = 0
        if width is not None and height is not None:
            portrait = layout in ('poster', 'heroPortrait', 'backgroundPortrait')
            if portrait != (height > width):
                continue
            area = width * height
        if area > best_area:
            best_url, best_area = url, area
    return best_url


def _asset_art(asset):
    art = {}
    images = asset.get('images')
    if isinstance(images, dict):
        for role, layouts in ART_LAYOUTS.items():
            for layout in layouts:
                url = _layout_image(images, layout)
                if url:
                    art[role] = url
                    break
    return art


def catalog_metadata(asset, fallback_title, parent=None):
    """Use verified raw fields already present in playlist/episode responses.

    Optional parent is an already available raw series asset, never fetched here.
    Fixed art handles missing URLs, not remote 404s. Icons help native controls;
    skin views differ. There is no bundled fanart: omit it for native backgrounds.
    No stream resolution or duration-unit assumption is made.
    """
    kind = clean_label(asset.get('type'))
    parent = parent if isinstance(parent, dict) else {}
    outline = clean_description(asset.get('shortDescription'))[:OUTLINE_LIMIT].rstrip()
    result = CatalogMetadata(
        title=clean_label(asset.get('label'), fallback_title),
        media_type=MEDIA_TYPES.get(kind, 'video'),
        plot=clean_description(asset.get('description')) or outline,
        outline=outline,
        year=_integer(asset.get('year'), 1000, 9999),
        premiered=_premiered(asset.get('releaseDate')),
    )
    if kind == 'episode':
        result.show_title = clean_label(asset.get('seriesName'))
        result.season = _integer(asset.get('seasonNumber'))
        result.episode = _integer(asset.get('episodeNumber'))
    elif kind == 'season':
        result.show_title = clean_label(asset.get('seriesName'), parent.get('label'))
        result.season = _integer(asset.get('seasonNumber'))
        if not result.plot:
            result.plot = (clean_description(parent.get('description'))
                           or clean_description(parent.get('shortDescription'))[:OUTLINE_LIMIT].rstrip())
    elif kind == 'series':
        result.show_title = result.title
    genres = asset.get('genres')
    if isinstance(genres, list):
        for genre in genres[:32]:
            label = clean_label(genre.get('label'))[:256].rstrip() if isinstance(genre, dict) else ''
            if label and label not in result.genres:
                result.genres.append(label)
    own_art = _asset_art(asset)
    parent_art = _asset_art(parent) if kind in ('season', 'episode') else {}
    result.art = {'icon': DEFAULT_ICONS.get(kind, DEFAULT_ICON)}
    if kind == 'season':
        result.art.update(parent_art)
    result.art.update(own_art)
    if kind == 'episode' and parent_art.get('fanart'):
        result.art['fanart'] = parent_art['fanart']
    result.art.setdefault('thumb', DEFAULT_THUMB)
    if kind in ('series', 'season'):
        result.art.setdefault('poster', DEFAULT_POSTER)
    return result
