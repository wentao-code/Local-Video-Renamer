from app.gui.library_sorting import DEFAULT_SORT_ORDER, SORT_ORDERS, normalize_sort_settings, sort_rows


DEFAULT_ACTOR_SORT_FIELD = 'name'
DEFAULT_ACTOR_SORT_ORDER = DEFAULT_SORT_ORDER
ACTOR_SORT_FIELDS = ('name', 'birthday', 'age')
ACTOR_SORT_ORDERS = SORT_ORDERS
ACTOR_SORT_FIELD_TYPES = {
    'name': 'natural',
    'birthday': 'text',
    'age': 'number',
}


def normalize_actor_sort_settings(settings):
    return normalize_sort_settings(settings, ACTOR_SORT_FIELDS, DEFAULT_ACTOR_SORT_FIELD)


def sort_actor_rows(rows, sort_field, sort_order):
    normalized_settings = normalize_actor_sort_settings({
        'sort_field': sort_field,
        'sort_order': sort_order,
    })
    return sort_rows(
        rows,
        normalized_settings['sort_field'],
        normalized_settings['sort_order'],
        ACTOR_SORT_FIELD_TYPES,
    )
