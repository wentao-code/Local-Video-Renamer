import re

from app.gui.library_sorting import natural_sort_key


_SORTABLE_NAME_PREFIX_RE = re.compile(r'^[^0-9A-Za-z\u3400-\u9fff]+')
_LIKE_LEVEL_ORDER = {'A': 0, 'B': 1, 'C': 2, 'D': 3}


def normalize_queen_name_for_sort(queen_name):
    raw_name = str(queen_name or '').strip()
    if not raw_name:
        return ''
    normalized_name = _SORTABLE_NAME_PREFIX_RE.sub('', raw_name)
    return normalized_name or raw_name


def queen_name_sort_key(queen_name):
    normalized_name = normalize_queen_name_for_sort(queen_name)
    if not normalized_name:
        return (2, (), '')
    if normalized_name[0].isascii():
        return (0, natural_sort_key(normalized_name), normalized_name.lower())
    return (1, tuple(normalized_name.encode('gb18030', errors='ignore')), normalized_name)


def queen_row_sort_key(row):
    payload = dict(row or {})
    like_level = str(payload.get('like_level', '') or '').strip().upper()
    name_key = queen_name_sort_key(payload.get('queen_name', ''))
    if like_level not in _LIKE_LEVEL_ORDER:
        return (0, -1, name_key)
    return (1, _LIKE_LEVEL_ORDER[like_level], name_key)


def sort_queen_rows(rows):
    return sorted(
        list(rows or []),
        key=queen_row_sort_key,
    )
