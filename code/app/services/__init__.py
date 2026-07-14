"""Top-level service entrypoints.

Import common cross-package services from here first; drop to subpackages only
when you need a narrower or internal implementation detail.
"""

from importlib import import_module


__all__ = [
    'ActorDetailLibrary',
    'AutoLoginService',
    'CodePrefixDetailLibrary',
    'CodePrefixLibrary',
    'ComboEnrichmentService',
    'LadderBoardService',
    'LibraryAdminService',
    'LibraryEnrichmentService',
    'LocalVideoLibraryService',
    'NetworkGuardService',
    'VideoFilterService',
    'extract_code_prefix',
    'split_actor_names',
]

_EXPORT_MAP = {
    'ActorDetailLibrary': ('app.services.detail', 'ActorDetailLibrary'),
    'AutoLoginService': ('app.services.auth', 'AutoLoginService'),
    'CodePrefixDetailLibrary': ('app.services.detail', 'CodePrefixDetailLibrary'),
    'CodePrefixLibrary': ('app.services.library', 'CodePrefixLibrary'),
    'ComboEnrichmentService': ('app.services.enrichment', 'ComboEnrichmentService'),
    'LadderBoardService': ('app.services.ladder', 'LadderBoardService'),
    'LibraryAdminService': ('app.services.library', 'LibraryAdminService'),
    'LibraryEnrichmentService': ('app.services.enrichment', 'LibraryEnrichmentService'),
    'LocalVideoLibraryService': ('app.services.local_video', 'LocalVideoLibraryService'),
    'NetworkGuardService': ('app.services.system', 'NetworkGuardService'),
    'VideoFilterService': ('app.services.video', 'VideoFilterService'),
    'extract_code_prefix': ('app.services.library', 'extract_code_prefix'),
    'split_actor_names': ('app.services.identity', 'split_actor_names'),
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
