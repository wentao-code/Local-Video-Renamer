"""Enrichment workflow entrypoints.

Import from here for batch/combo enrichment runners, progress trackers, and
task logging helpers.
"""

from importlib import import_module


__all__ = [
    'ActorEnrichmentService',
    'ActorBinghuoEnrichmentService',
    'ActorBaomuEnrichmentService',
    'ActorJavtxtEnrichmentService',
    'CodePrefixEnrichmentService',
    'CodePrefixJavtxtEnrichmentService',
    'ComboEnrichmentService',
    'ComboProgressService',
    'ComboSubtaskProgressTracker',
    'ComboTaskLogger',
    'EnrichmentProgressService',
    'EnrichmentTaskState',
    'LibraryEnrichmentService',
    'TaskTraceLogger',
    'VideoEnrichmentService',
    'VideoSourceEnrichmentService',
    'start_progress_tracker',
]

_EXPORT_MAP = {
    'ActorEnrichmentService': ('app.services.enrichment.actor_enrichment', 'ActorEnrichmentService'),
    'ActorBinghuoEnrichmentService': (
        'app.services.enrichment.actor_binghuo_enrichment',
        'ActorBinghuoEnrichmentService',
    ),
    'ActorBaomuEnrichmentService': (
        'app.services.enrichment.actor_baomu_enrichment',
        'ActorBaomuEnrichmentService',
    ),
    'ActorJavtxtEnrichmentService': ('app.services.enrichment.actor_javtxt_enrichment', 'ActorJavtxtEnrichmentService'),
    'CodePrefixEnrichmentService': ('app.services.enrichment.code_prefix_enrichment', 'CodePrefixEnrichmentService'),
    'CodePrefixJavtxtEnrichmentService': (
        'app.services.enrichment.code_prefix_javtxt_enrichment',
        'CodePrefixJavtxtEnrichmentService',
    ),
    'ComboEnrichmentService': ('app.services.enrichment.combo_enrichment_service', 'ComboEnrichmentService'),
    'ComboProgressService': ('app.services.enrichment.combo_progress_service', 'ComboProgressService'),
    'ComboSubtaskProgressTracker': (
        'app.services.enrichment.combo_progress_service',
        'ComboSubtaskProgressTracker',
    ),
    'ComboTaskLogger': ('app.services.enrichment.combo_task_logger', 'ComboTaskLogger'),
    'EnrichmentProgressService': (
        'app.services.enrichment.enrichment_progress_service',
        'EnrichmentProgressService',
    ),
    'EnrichmentTaskState': ('app.services.enrichment.enrichment_task_state', 'EnrichmentTaskState'),
    'LibraryEnrichmentService': (
        'app.services.enrichment.library_enrichment_service',
        'LibraryEnrichmentService',
    ),
    'TaskTraceLogger': ('app.services.enrichment.task_trace_logger', 'TaskTraceLogger'),
    'VideoEnrichmentService': ('app.services.enrichment.video_enrichment', 'VideoEnrichmentService'),
    'VideoSourceEnrichmentService': (
        'app.services.enrichment.video_source_enrichment_service',
        'VideoSourceEnrichmentService',
    ),
    'start_progress_tracker': ('app.services.enrichment.progress_tracker_compat', 'start_progress_tracker'),
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
