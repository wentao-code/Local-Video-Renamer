import re


_MISSING_ACTOR_TEXTS = {
    '',
    '-',
    '--',
    'na',
    'n/a',
    'none',
    'null',
    'unknown',
    '无',
    '無',
    '暂无',
    '暫無',
    '未知',
    '无记录',
    '無記錄',
    '未公开',
    '未公開',
}


def normalize_second_source_actor_text(value):
    text = _normalize_spacing(value)
    if not text:
        return ''
    compact = re.sub(r'[\s\u3000,，、/;；|]+', '', text).lower()
    if compact in _MISSING_ACTOR_TEXTS:
        return ''
    return text


def _normalize_spacing(value):
    return ' '.join(str(value or '').replace('\u3000', ' ').split()).strip()
