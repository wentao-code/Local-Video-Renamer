"""Resolver entrypoints.

Import from here for JAVTXT-backed author resolution helpers and specialized
resolver variants.
"""

from importlib import import_module


__all__ = [
    'ActorMovieAuthorResolver',
    'MovieAuthorResolver',
]

_EXPORT_MAP = {
    'ActorMovieAuthorResolver': ('app.services.resolvers.actor_movie_author_resolver', 'ActorMovieAuthorResolver'),
    'MovieAuthorResolver': ('app.services.resolvers.movie_author_resolver', 'MovieAuthorResolver'),
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
