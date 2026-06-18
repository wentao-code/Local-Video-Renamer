"""Search-card and listing parser entrypoints.

Use this package for AVFan-style card parsing helpers before reaching into the
individual parser modules.
"""

from importlib import import_module


__all__ = [
    'extract_code',
    'extract_release_date',
    'extract_title_line',
    'parse_actor_search_card',
    'parse_code_prefix_card',
    'split_title_and_author',
]

_EXPORT_MAP = {
    'parse_actor_search_card': ('app.services.parsers.actor_search_entry_parser', 'parse_actor_search_card'),
    'extract_code': ('app.services.parsers.code_prefix_entry_parser', 'extract_code'),
    'extract_release_date': ('app.services.parsers.code_prefix_entry_parser', 'extract_release_date'),
    'extract_title_line': ('app.services.parsers.code_prefix_entry_parser', 'extract_title_line'),
    'parse_code_prefix_card': ('app.services.parsers.code_prefix_entry_parser', 'parse_code_prefix_card'),
    'split_title_and_author': ('app.services.parsers.code_prefix_entry_parser', 'split_title_and_author'),
}


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
