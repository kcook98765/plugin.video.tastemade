"""Pure grouping of complete episode inventories; curated lists stay untouched.

The caller owns inventory completeness and fetching. No inventory cap is applied
here, and missing or malformed raw numbers remain unknown rather than season 0.
"""
from typing import Optional

from service import PAGE_SIZE, ServiceError, catalog_page, page_offset


def _raw_number(value):
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100000:
        return value
    return None


def season_number(value) -> Optional[int]:
    """Parse 'unknown' or up to six ASCII decimal digits in 0..100000.

    Non-boolean integers in the same range are also accepted for internal calls;
    None is not a route value. Leading zeroes are allowed within the digit bound.
    """
    if isinstance(value, str):
        if value == 'unknown':
            return None
        if 1 <= len(value) <= 6 and value.isascii() and value.isdigit():
            number = _raw_number(int(value))
            if number is not None:
                return number
    else:
        number = _raw_number(value)
        if number is not None:
            return number
    raise ServiceError('Invalid catalog season. Return to the previous listing.')


def _number_key(number):
    return number is None, number if number is not None else 0


def season_groups(items) -> list[dict]:
    """Group supported episodes from a list/tuple, stably sorting raw numbers.

    IDs must be nonblank strings or nonnegative, non-boolean integers (no numeric
    ID cap). Assets are preserved verbatim; only new grouping lists are sorted.
    """
    groups: dict[Optional[int], list[dict]] = {}
    for item in items if isinstance(items, (list, tuple)) else ():
        if not isinstance(item, dict) or item.get('type') != 'episode':
            continue
        asset_id = item.get('id')
        if not ((isinstance(asset_id, str) and bool(asset_id.strip())) or
                (isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id >= 0)):
            continue
        number = _raw_number(item.get('seasonNumber'))
        groups.setdefault(number, []).append(item)
    return [
        {'number': number,
         'items': sorted(groups[number],
                         key=lambda item: _number_key(_raw_number(item.get('episodeNumber')))),
         'count': len(groups[number])}
        for number in sorted(groups, key=_number_key)
    ]


def season_page(items, season, offset) -> dict:
    """Select a season route value and use the existing bounded paging contract."""
    number = season_number(season)
    offset = page_offset(offset)
    selected: list[dict] = next((group['items'] for group in season_groups(items)
                     if group['number'] == number), [])
    return catalog_page({'items': selected[offset:offset + PAGE_SIZE + 1],
                         'total': len(selected), 'offset': offset,
                         'size': PAGE_SIZE + 1}, offset)
