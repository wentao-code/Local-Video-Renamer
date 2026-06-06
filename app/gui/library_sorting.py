import re


DEFAULT_SORT_ORDER = 'asc'
SORT_ORDERS = ('asc', 'desc')


def normalize_sort_settings(settings, supported_fields, default_field):
    settings = dict(settings or {}) if isinstance(settings, dict) else {}
    sort_field = str(settings.get('sort_field', default_field) or '').strip()
    sort_order = str(settings.get('sort_order', DEFAULT_SORT_ORDER) or '').strip()
    if sort_field not in supported_fields:
        sort_field = default_field
    if sort_order not in SORT_ORDERS:
        sort_order = DEFAULT_SORT_ORDER
    return {
        'sort_field': sort_field,
        'sort_order': sort_order,
    }


def sort_rows(rows, sort_field, sort_order, field_types=None):
    field_types = dict(field_types or {})
    reverse = sort_order == 'desc'
    rows_with_values = []
    rows_without_values = []

    for row in rows or []:
        sort_value = row_sort_value(row, sort_field, field_types.get(sort_field, 'text'))
        target = rows_without_values if sort_value is None else rows_with_values
        target.append((sort_value, row))

    rows_with_values.sort(key=lambda item: item[0], reverse=reverse)
    return [item[1] for item in rows_with_values] + [item[1] for item in rows_without_values]


def row_sort_value(row, sort_field, field_type):
    value = (row or {}).get(sort_field, '')
    text = str(value or '').strip()
    if not text:
        return None
    if field_type == 'duration':
        return parse_duration_seconds(text)
    if field_type == 'number':
        return parse_number(text)
    if field_type == 'natural':
        return natural_sort_key(text)
    return text


def parse_duration_seconds(text):
    parts = str(text or '').strip().split(':')
    if not parts:
        return None
    try:
        total_seconds = 0
        for part in parts:
            total_seconds = total_seconds * 60 + int(part)
    except ValueError:
        return None
    return total_seconds


def parse_number(text):
    try:
        return float(str(text or '').strip())
    except ValueError:
        return None


def natural_sort_key(text):
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r'(\d+)', str(text or '').strip())
    )
