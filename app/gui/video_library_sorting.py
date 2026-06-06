from app.gui.library_sorting import DEFAULT_SORT_ORDER, SORT_ORDERS, normalize_sort_settings, sort_rows


DEFAULT_VIDEO_SORT_FIELD = 'code'
DEFAULT_VIDEO_SORT_ORDER = DEFAULT_SORT_ORDER
VIDEO_SORT_FIELDS = ('code', 'video_category', 'duration', 'size', 'release_date')
VIDEO_SORT_ORDERS = SORT_ORDERS
VIDEO_SORT_FIELD_TYPES = {
    'code': 'natural',
    'video_category': 'text',
    'duration': 'duration',
    'size': 'number',
    'release_date': 'text',
}


def normalize_video_sort_settings(settings):
    return normalize_sort_settings(settings, VIDEO_SORT_FIELDS, DEFAULT_VIDEO_SORT_FIELD)


def sort_video_rows(rows, sort_field, sort_order):
    normalized_settings = normalize_video_sort_settings({
        'sort_field': sort_field,
        'sort_order': sort_order,
    })
    return sort_rows(
        rows,
        normalized_settings['sort_field'],
        normalized_settings['sort_order'],
        VIDEO_SORT_FIELD_TYPES,
    )
