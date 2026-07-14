from app.gui.library_sorting import DEFAULT_SORT_ORDER, SORT_ORDERS, normalize_sort_settings, sort_rows


DEFAULT_CODE_PREFIX_SORT_FIELD = 'prefix'
DEFAULT_CODE_PREFIX_SORT_ORDER = DEFAULT_SORT_ORDER
CODE_PREFIX_SORT_FIELDS = (
    'prefix',
    'video_count',
    'avfan_total_videos',
    'earliest_release_date',
    'latest_release_date',
)
CODE_PREFIX_SORT_ORDERS = SORT_ORDERS
CODE_PREFIX_SORT_FIELD_TYPES = {
    'prefix': 'natural',
    'video_count': 'number',
    'avfan_total_videos': 'number',
    'earliest_release_date': 'text',
    'latest_release_date': 'text',
}


def normalize_code_prefix_sort_settings(settings):
    return normalize_sort_settings(settings, CODE_PREFIX_SORT_FIELDS, DEFAULT_CODE_PREFIX_SORT_FIELD)


def sort_code_prefix_rows(rows, sort_field, sort_order):
    normalized_settings = normalize_code_prefix_sort_settings({
        'sort_field': sort_field,
        'sort_order': sort_order,
    })
    return sort_rows(
        rows,
        normalized_settings['sort_field'],
        normalized_settings['sort_order'],
        CODE_PREFIX_SORT_FIELD_TYPES,
    )
