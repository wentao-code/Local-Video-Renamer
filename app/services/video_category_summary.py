from app.services.video_category_service import (
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_SINGLE,
    normalize_video_category,
)


UNCATEGORIZED_VIDEO_LABEL = '暂无分类信息'

_ORDERED_VIDEO_CATEGORY_NAMES = (
    VIDEO_CATEGORY_SINGLE,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_COLLECTION,
    UNCATEGORIZED_VIDEO_LABEL,
)


def build_video_category_distribution(rows):
    counts = {name: 0 for name in _ORDERED_VIDEO_CATEGORY_NAMES}

    for row in rows or []:
        category = normalize_video_category((row or {}).get('video_category', ''))
        counts[category or UNCATEGORIZED_VIDEO_LABEL] += 1

    return [
        {'name': name, 'video_count': counts[name]}
        for name in _ORDERED_VIDEO_CATEGORY_NAMES
        if counts[name] > 0
    ]


def count_uncategorized_video_rows(rows):
    return sum(
        1
        for row in (rows or [])
        if not normalize_video_category((row or {}).get('video_category', ''))
    )
