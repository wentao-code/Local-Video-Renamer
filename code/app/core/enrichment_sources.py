from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
)


AVFAN_VIDEO_SOURCE = 'avfan'
JAVTXT_VIDEO_SOURCE = 'javtxt'
BINGHUO_ACTOR_SOURCE = 'binghuo'
BAOMU_ACTOR_SOURCE = 'baomu'
SUPPLEMENT_TASK_SOURCE = 'supplement'
DEFAULT_VIDEO_ENRICHMENT_SOURCE = JAVTXT_VIDEO_SOURCE


VIDEO_ENRICHMENT_SOURCE_LABELS = {
    AVFAN_VIDEO_SOURCE: '天限阁',
    JAVTXT_VIDEO_SOURCE: '辛聚谷',
    BINGHUO_ACTOR_SOURCE: '并火',
    BAOMU_ACTOR_SOURCE: '保木',
    SUPPLEMENT_TASK_SOURCE: '补充任务',
}

LEGACY_SOURCE_LABEL_ALIASES = {
    AVFAN_VIDEO_SOURCE: ('天陨阁',),
}


def normalize_video_enrichment_source(source_key):
    if source_key in VIDEO_ENRICHMENT_SOURCE_LABELS:
        return source_key
    return DEFAULT_VIDEO_ENRICHMENT_SOURCE


def get_video_enrichment_source_label(source_key):
    return VIDEO_ENRICHMENT_SOURCE_LABELS[normalize_video_enrichment_source(source_key)]


def build_video_enrichment_status_text(avfan_status, javtxt_status):
    normalized_avfan = normalize_source_enrichment_status(avfan_status, AVFAN_VIDEO_SOURCE)
    normalized_javtxt = normalize_source_enrichment_status(javtxt_status, JAVTXT_VIDEO_SOURCE)
    return (
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[AVFAN_VIDEO_SOURCE]}: {normalized_avfan} | '
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[JAVTXT_VIDEO_SOURCE]}: {normalized_javtxt}'
    )


def build_library_enrichment_status_text(avfan_status, javtxt_status, binghuo_status=None, baomu_status=None):
    normalized_avfan = normalize_source_enrichment_status(avfan_status, AVFAN_VIDEO_SOURCE)
    normalized_javtxt = normalize_source_enrichment_status(javtxt_status, JAVTXT_VIDEO_SOURCE)
    parts = [
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[AVFAN_VIDEO_SOURCE]}: {normalized_avfan}',
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[JAVTXT_VIDEO_SOURCE]}: {normalized_javtxt}',
    ]
    if binghuo_status is not None:
        normalized_binghuo = normalize_source_enrichment_status(binghuo_status, BINGHUO_ACTOR_SOURCE)
        parts.append(f'{VIDEO_ENRICHMENT_SOURCE_LABELS[BINGHUO_ACTOR_SOURCE]}: {normalized_binghuo}')
    if baomu_status is not None:
        normalized_baomu = normalize_source_enrichment_status(baomu_status, BAOMU_ACTOR_SOURCE)
        parts.append(f'{VIDEO_ENRICHMENT_SOURCE_LABELS[BAOMU_ACTOR_SOURCE]}: {normalized_baomu}')
    return ' | '.join(parts)


def normalize_video_enrichment_status(status):
    text = str(status or '').strip()
    return text or UNENRICHED_STATUS


def normalize_source_enrichment_status(status, source_key):
    text = str(status or '').strip()
    extracted = _extract_source_status(text, source_key)
    return normalize_video_enrichment_status(extracted or text)


def _extract_source_status(text, source_key):
    normalized_text = str(text or '').strip()
    if not normalized_text or ':' not in normalized_text:
        return ''
    for label in _source_status_labels(source_key):
        marker = f'{label}:'
        marker_index = normalized_text.find(marker)
        if marker_index < 0:
            continue
        tail = normalized_text[marker_index + len(marker):].strip()
        return tail.split('|', 1)[0].strip()
    return ''


def _source_status_labels(source_key):
    labels = [VIDEO_ENRICHMENT_SOURCE_LABELS.get(source_key, '')]
    labels.extend(LEGACY_SOURCE_LABEL_ALIASES.get(source_key, ()))
    return tuple(label for label in labels if str(label or '').strip())


def build_video_remaining_label(source_key):
    return f'剩余未用{get_video_enrichment_source_label(source_key)}补全视频'


def is_effective_video_success_status(status):
    return normalize_video_enrichment_status(status) == ENRICHED_STATUS


def is_effective_video_pending_status(status):
    return normalize_video_enrichment_status(status) in (UNENRICHED_STATUS, FAILED_STATUS)


def is_effective_video_terminal_status(status):
    normalized_status = normalize_video_enrichment_status(status)
    return normalized_status == ENRICHED_STATUS or is_no_result_status(normalized_status)
