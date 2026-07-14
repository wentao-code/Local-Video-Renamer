MEDAL_TYPE_AGE = 'age'
MEDAL_TYPE_BODY = 'body'
MEDAL_TYPE_SKIN_TONE = 'skin_tone'
MEDAL_TYPE_HAIRSTYLE = 'hairstyle'
MEDAL_TYPE_SPECIAL = 'special'

MEDAL_TYPE_ORDER = (
    MEDAL_TYPE_AGE,
    MEDAL_TYPE_BODY,
    MEDAL_TYPE_SKIN_TONE,
    MEDAL_TYPE_HAIRSTYLE,
    MEDAL_TYPE_SPECIAL,
)

MEDAL_TYPE_LABELS = {
    MEDAL_TYPE_AGE: '年龄',
    MEDAL_TYPE_BODY: '身材',
    MEDAL_TYPE_SKIN_TONE: '肤色',
    MEDAL_TYPE_HAIRSTYLE: '发型',
    MEDAL_TYPE_SPECIAL: '特殊',
}

_MEDAL_TYPE_RANKS = {medal_type: index for index, medal_type in enumerate(MEDAL_TYPE_ORDER)}


def normalize_medal_type(medal_type):
    normalized = str(medal_type or '').strip().lower()
    return normalized if normalized in _MEDAL_TYPE_RANKS else MEDAL_TYPE_SPECIAL


def medal_type_label(medal_type):
    return MEDAL_TYPE_LABELS[normalize_medal_type(medal_type)]


def medal_type_sort_key(medal_type):
    return _MEDAL_TYPE_RANKS[normalize_medal_type(medal_type)]


def sort_medal_rows(rows):
    normalized_rows = [dict(row or {}) for row in rows or []]
    for row in normalized_rows:
        row['medal_type'] = normalize_medal_type(row.get('medal_type', ''))
    return sorted(
        normalized_rows,
        key=lambda row: medal_type_sort_key(row.get('medal_type', '')),
    )


def sort_medal_names(medal_names, medal_types_by_name=None):
    type_map = dict(medal_types_by_name or {})
    unique_names = []
    seen = set()
    for medal_name in medal_names or []:
        normalized_name = str(medal_name or '').strip()
        if not normalized_name or normalized_name in seen:
            continue
        seen.add(normalized_name)
        unique_names.append(normalized_name)
    return [
        medal_name
        for _index, medal_name in sorted(
            enumerate(unique_names),
            key=lambda item: medal_type_sort_key(type_map.get(item[1], MEDAL_TYPE_SPECIAL)),
        )
    ]
