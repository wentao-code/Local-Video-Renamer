"""Local-video service entrypoints.

Import from here for scan/import/rename orchestration and local media-info
helpers.
"""

from importlib import import_module


__all__ = [
    'LocalVideoImportService',
    'LocalVideoLibraryService',
    'LocalVideoMediaInfo',
    'LocalVideoRenameService',
    'LocalVideoScanService',
    'format_duration_seconds',
    'format_size_gb',
    'probe_video_duration_seconds',
    'read_local_video_media_info',
]

_EXPORT_MAP = {
    'LocalVideoImportService': ('app.services.local_video.local_video_import_service', 'LocalVideoImportService'),
    'LocalVideoLibraryService': ('app.services.local_video.local_video_library_service', 'LocalVideoLibraryService'),
    'LocalVideoMediaInfo': ('app.services.local_video.local_video_media_info', 'LocalVideoMediaInfo'),
    'LocalVideoRenameService': ('app.services.local_video.local_video_rename_service', 'LocalVideoRenameService'),
    'LocalVideoScanService': ('app.services.local_video.local_video_scan_service', 'LocalVideoScanService'),
    'format_duration_seconds': ('app.services.local_video.local_video_media_info', 'format_duration_seconds'),
    'format_size_gb': ('app.services.local_video.local_video_media_info', 'format_size_gb'),
    'probe_video_duration_seconds': ('app.services.local_video.local_video_media_info', 'probe_video_duration_seconds'),
    'read_local_video_media_info': ('app.services.local_video.local_video_media_info', 'read_local_video_media_info'),
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
