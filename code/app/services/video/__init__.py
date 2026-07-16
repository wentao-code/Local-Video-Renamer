"""Video metadata and filtering entrypoints.

Use this package for category classification constants/helpers and library
filtering services.
"""

from importlib import import_module


__all__ = [
    'COLLECTION_TAG_KEYWORDS',
    'MANUAL_CATEGORY_TIER_FIRST',
    'MANUAL_CATEGORY_TIER_SECOND',
    'MANUAL_CATEGORY_TIER_THIRD',
    'VIDEO_CATEGORY_COLLECTION',
    'VIDEO_CATEGORY_CO_STAR',
    'VIDEO_CATEGORY_OPTIONS',
    'VIDEO_CATEGORY_SINGLE',
    'VideoFilterService',
    'RuleSet',
    'classify_manual_category_tier',
    'count_video_actors',
    'detect_video_category',
    'normalize_video_category',
    'requires_manual_video_category',
]

_EXPORT_MAP = {
    'COLLECTION_TAG_KEYWORDS': ('app.services.video.video_category_service', 'COLLECTION_TAG_KEYWORDS'),
    'MANUAL_CATEGORY_TIER_FIRST': ('app.services.video.video_category_service', 'MANUAL_CATEGORY_TIER_FIRST'),
    'MANUAL_CATEGORY_TIER_SECOND': ('app.services.video.video_category_service', 'MANUAL_CATEGORY_TIER_SECOND'),
    'MANUAL_CATEGORY_TIER_THIRD': ('app.services.video.video_category_service', 'MANUAL_CATEGORY_TIER_THIRD'),
    'VIDEO_CATEGORY_COLLECTION': ('app.services.video.video_category_service', 'VIDEO_CATEGORY_COLLECTION'),
    'VIDEO_CATEGORY_CO_STAR': ('app.services.video.video_category_service', 'VIDEO_CATEGORY_CO_STAR'),
    'VIDEO_CATEGORY_OPTIONS': ('app.services.video.video_category_service', 'VIDEO_CATEGORY_OPTIONS'),
    'VIDEO_CATEGORY_SINGLE': ('app.services.video.video_category_service', 'VIDEO_CATEGORY_SINGLE'),
    'classify_manual_category_tier': ('app.services.video.video_category_service', 'classify_manual_category_tier'),
    'count_video_actors': ('app.services.video.video_category_service', 'count_video_actors'),
    'detect_video_category': ('app.services.video.video_category_service', 'detect_video_category'),
    'normalize_video_category': ('app.services.video.video_category_service', 'normalize_video_category'),
    'requires_manual_video_category': ('app.services.video.video_category_service', 'requires_manual_video_category'),
    'VideoFilterService': ('app.services.video.video_filter_service', 'VideoFilterService'),
    'RuleSet': ('app.core.video_filter_rules', 'RuleSet'),
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
