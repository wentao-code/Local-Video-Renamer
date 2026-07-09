import re

from app.gui.library_sorting import natural_sort_key


_SORTABLE_NAME_PREFIX_RE = re.compile(r'^[^0-9A-Za-z\u3400-\u9fff]+')


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


def sort_queen_rows(rows):
    return sorted(
        list(rows or []),
        key=lambda row: queen_name_sort_key((row or {}).get('queen_name', '')),
    )
