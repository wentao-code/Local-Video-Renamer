"""Library management entrypoints.

Use this package for actor/code library views, admin updates, sync services,
and path-library helpers.
"""

from importlib import import_module


__all__ = [
    'CanglanggeCandidateService',
    'ActorLibrarySyncService',
    'ActorProfileUpdateService',
    'CodePrefixLibrary',
    'CodePrefixVideoCategoryBulkService',
    'DataCenterService',
    'LibraryAdminService',
    'LibraryStatusSyncService',
    'PathLibrary',
    'build_merged_movie_snapshot',
    'extract_code_prefix',
    'get_storage_location_name',
    'summarize_paths',
]

_EXPORT_MAP = {
    'CanglanggeCandidateService': (
        'app.services.library.canglangge_candidate_service',
        'CanglanggeCandidateService',
    ),
    'ActorLibrarySyncService': ('app.services.library.actor_library_sync_service', 'ActorLibrarySyncService'),
    'ActorProfileUpdateService': ('app.services.library.actor_profile_update_service', 'ActorProfileUpdateService'),
    'CodePrefixLibrary': ('app.services.library.code_prefix_library', 'CodePrefixLibrary'),
    'extract_code_prefix': ('app.services.library.code_prefix_library', 'extract_code_prefix'),
    'CodePrefixVideoCategoryBulkService': (
        'app.services.library.code_prefix_video_category_bulk_service',
        'CodePrefixVideoCategoryBulkService',
    ),
    'DataCenterService': ('app.services.library.data_center_service', 'DataCenterService'),
    'LibraryAdminService': ('app.services.library.library_admin_service', 'LibraryAdminService'),
    'build_merged_movie_snapshot': (
        'app.services.library.library_status_sync_merger',
        'build_merged_movie_snapshot',
    ),
    'LibraryStatusSyncService': ('app.services.library.library_status_sync_service', 'LibraryStatusSyncService'),
    'PathLibrary': ('app.services.library.path_library', 'PathLibrary'),
    'get_storage_location_name': ('app.services.library.path_library', 'get_storage_location_name'),
    'summarize_paths': ('app.services.library.path_library', 'summarize_paths'),
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
