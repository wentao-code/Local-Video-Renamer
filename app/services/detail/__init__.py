"""Detail-page service entrypoints.

Use this package for actor/code detail loaders, quick filters, update-status
helpers, and detail-page web-link/category summaries.
"""

from importlib import import_module


__all__ = [
    'ACTOR_DETAIL_FILTER_OPTIONS',
    'ActorDetailLibrary',
    'CODE_PREFIX_DETAIL_FILTER_OPTIONS',
    'CodePrefixDetailLibrary',
    'DETAIL_FILTER_ACTIVE',
    'DETAIL_FILTER_ALL',
    'DETAIL_FILTER_AVFAN_ENRICHED',
    'DETAIL_FILTER_AVFAN_FAILED',
    'DETAIL_FILTER_AVFAN_PENDING',
    'DETAIL_FILTER_ENRICHED',
    'DETAIL_FILTER_FAILED',
    'DETAIL_FILTER_INACTIVE',
    'DETAIL_FILTER_JAVTXT_ENRICHED',
    'DETAIL_FILTER_JAVTXT_FAILED',
    'DETAIL_FILTER_JAVTXT_PENDING',
    'DETAIL_FILTER_MISSING_AGE',
    'DETAIL_FILTER_MISSING_BIRTHDAY',
    'DETAIL_FILTER_PENDING',
    'DETAIL_FILTER_SUSPECT',
    'DETAIL_FILTER_TIER_A',
    'DETAIL_FILTER_TIER_B',
    'DETAIL_FILTER_TIER_C',
    'DETAIL_FILTER_TIER_D',
    'DETAIL_FILTER_TIER_S',
    'UNCATEGORIZED_VIDEO_LABEL',
    'build_actor_detail_web_url',
    'build_code_prefix_detail_web_url',
    'build_video_category_distribution',
    'count_uncategorized_video_rows',
    'filter_library_rows',
    'resolve_update_status',
]

_EXPORT_MAP = {
    'ActorDetailLibrary': ('app.services.detail.actor_detail_library', 'ActorDetailLibrary'),
    'CodePrefixDetailLibrary': ('app.services.detail.code_prefix_detail_library', 'CodePrefixDetailLibrary'),
    'ACTOR_DETAIL_FILTER_OPTIONS': ('app.services.detail.quick_filter_service', 'ACTOR_DETAIL_FILTER_OPTIONS'),
    'CODE_PREFIX_DETAIL_FILTER_OPTIONS': ('app.services.detail.quick_filter_service', 'CODE_PREFIX_DETAIL_FILTER_OPTIONS'),
    'DETAIL_FILTER_ACTIVE': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_ACTIVE'),
    'DETAIL_FILTER_ALL': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_ALL'),
    'DETAIL_FILTER_AVFAN_ENRICHED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_AVFAN_ENRICHED'),
    'DETAIL_FILTER_AVFAN_FAILED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_AVFAN_FAILED'),
    'DETAIL_FILTER_AVFAN_PENDING': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_AVFAN_PENDING'),
    'DETAIL_FILTER_ENRICHED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_ENRICHED'),
    'DETAIL_FILTER_FAILED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_FAILED'),
    'DETAIL_FILTER_INACTIVE': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_INACTIVE'),
    'DETAIL_FILTER_JAVTXT_ENRICHED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_JAVTXT_ENRICHED'),
    'DETAIL_FILTER_JAVTXT_FAILED': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_JAVTXT_FAILED'),
    'DETAIL_FILTER_JAVTXT_PENDING': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_JAVTXT_PENDING'),
    'DETAIL_FILTER_MISSING_AGE': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_MISSING_AGE'),
    'DETAIL_FILTER_MISSING_BIRTHDAY': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_MISSING_BIRTHDAY'),
    'DETAIL_FILTER_PENDING': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_PENDING'),
    'DETAIL_FILTER_SUSPECT': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_SUSPECT'),
    'DETAIL_FILTER_TIER_A': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_TIER_A'),
    'DETAIL_FILTER_TIER_B': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_TIER_B'),
    'DETAIL_FILTER_TIER_C': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_TIER_C'),
    'DETAIL_FILTER_TIER_D': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_TIER_D'),
    'DETAIL_FILTER_TIER_S': ('app.services.detail.quick_filter_service', 'DETAIL_FILTER_TIER_S'),
    'filter_library_rows': ('app.services.detail.quick_filter_service', 'filter_library_rows'),
    'resolve_update_status': ('app.services.detail.update_status_service', 'resolve_update_status'),
    'UNCATEGORIZED_VIDEO_LABEL': ('app.services.detail.video_category_summary', 'UNCATEGORIZED_VIDEO_LABEL'),
    'build_video_category_distribution': ('app.services.detail.video_category_summary', 'build_video_category_distribution'),
    'count_uncategorized_video_rows': ('app.services.detail.video_category_summary', 'count_uncategorized_video_rows'),
    'build_actor_detail_web_url': ('app.services.detail.web_link_service', 'build_actor_detail_web_url'),
    'build_code_prefix_detail_web_url': ('app.services.detail.web_link_service', 'build_code_prefix_detail_web_url'),
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
