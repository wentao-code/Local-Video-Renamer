"""Canonical enrichment status codes and compatibility mappings.

Database fields use the stable codes below. Legacy Chinese values and the
compact library display values remain readable during migration.
"""

UNENRICHED_STATUS = 'UNENRICHED'
NO_SEARCH_RESULTS_STATUS = 'NO_RESULT'
NO_VIDEO_DETAIL_STATUS = 'NO_DETAIL'
ENRICHED_STATUS = 'ENRICHED'
FAILED_STATUS = 'FAILED'
PENDING_STATUS = 'PENDING'

STATUS_REGISTRY = {
    UNENRICHED_STATUS: {'label': '未补全', 'display_code': 'x'},
    NO_SEARCH_RESULTS_STATUS: {'label': '无搜索结果', 'display_code': 'y'},
    NO_VIDEO_DETAIL_STATUS: {'label': '无视频详情', 'display_code': 'z'},
    ENRICHED_STATUS: {'label': '已补全', 'display_code': 'f'},
    FAILED_STATUS: {'label': '补全失败', 'display_code': 's'},
    PENDING_STATUS: {'label': '等待补全', 'display_code': 'w'},
}

LEGACY_STATUS_ALIASES = {
    '未补全': UNENRICHED_STATUS,
    '无搜索结果': NO_SEARCH_RESULTS_STATUS,
    '无视频详情': NO_VIDEO_DETAIL_STATUS,
    '已补全': ENRICHED_STATUS,
    '补全失败': FAILED_STATUS,
    '等待补全': PENDING_STATUS,
    'x': UNENRICHED_STATUS,
    'y': NO_SEARCH_RESULTS_STATUS,
    'z': NO_VIDEO_DETAIL_STATUS,
    'f': ENRICHED_STATUS,
    's': FAILED_STATUS,
    'w': PENDING_STATUS,
}


def normalize_enrichment_status(value, default=UNENRICHED_STATUS):
    text = str(value or '').strip()
    if not text:
        return default
    if text in STATUS_REGISTRY:
        return text
    return LEGACY_STATUS_ALIASES.get(text, default)


def get_enrichment_status_label(value):
    code = normalize_enrichment_status(value)
    return STATUS_REGISTRY[code]['label']


def get_enrichment_status_display_code(value):
    code = normalize_enrichment_status(value)
    return STATUS_REGISTRY[code]['display_code']


def is_no_result_status(value):
    return normalize_enrichment_status(value) in (
        NO_SEARCH_RESULTS_STATUS,
        NO_VIDEO_DETAIL_STATUS,
    )
