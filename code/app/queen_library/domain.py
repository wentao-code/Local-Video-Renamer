QUEEN_RECORD_PREFIX = '\u5957\u8def\u76f4\u64ad_'

QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY = 'keyword_library'
QUEEN_CRAWL_SOURCE_AUTO_GENERATED = 'auto_generated'
QUEEN_CRAWL_SOURCES = (
    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
)

QUEEN_PROFILE_FIELD_OPTIONS = {
    'body_type': ('slim', 'overweight'),
    'style': ('gentle', 'rough'),
    'face': ('visible', 'hidden'),
    'age_group': ('loli', 'young_married', 'mature'),
    'like_level': ('A', 'B', 'C', 'D'),
}

QUEEN_VIDEO_CONTENT_TYPES = ('humiliation', 'chat', 'discipline')
QUEEN_VIDEO_CONTENT_LEVELS = ('S', 'A', 'B', 'C')


def _legacy_mojibake(value):
    try:
        return str(value).encode('utf-8').decode('gbk')
    except UnicodeError:
        return ''


_CRAWL_SOURCE_ALIASES = {
    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY: QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    'keyword': QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    'manual': QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    '\u5173\u952e\u8bcd\u5e93': QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    _legacy_mojibake('\u5173\u952e\u8bcd\u5e93'): QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    QUEEN_CRAWL_SOURCE_AUTO_GENERATED: QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
    'auto': QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
    'generated': QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
    '\u81ea\u52a8\u751f\u6210': QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
    _legacy_mojibake('\u81ea\u52a8\u751f\u6210'): QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
}

_PROFILE_VALUE_ALIASES = {
    'body_type': {
        'slim': 'slim',
        '\u82d7\u6761': 'slim',
        _legacy_mojibake('\u82d7\u6761'): 'slim',
        'overweight': 'overweight',
        'fat': 'overweight',
        '\u80a5\u80d6': 'overweight',
        _legacy_mojibake('\u80a5\u80d6'): 'overweight',
    },
    'style': {
        'gentle': 'gentle',
        '\u6e29\u548c': 'gentle',
        _legacy_mojibake('\u6e29\u548c'): 'gentle',
        'rough': 'rough',
        '\u7c97\u66b4': 'rough',
        _legacy_mojibake('\u7c97\u66b4'): 'rough',
    },
    'face': {
        'visible': 'visible',
        'yes': 'visible',
        '\u662f': 'visible',
        _legacy_mojibake('\u662f'): 'visible',
        'hidden': 'hidden',
        'no': 'hidden',
        '\u5426': 'hidden',
        _legacy_mojibake('\u5426'): 'hidden',
    },
    'age_group': {
        'loli': 'loli',
        '\u841d\u8389': 'loli',
        _legacy_mojibake('\u841d\u8389'): 'loli',
        'young_married': 'young_married',
        '\u5c11\u5987': 'young_married',
        _legacy_mojibake('\u5c11\u5987'): 'young_married',
        'mature': 'mature',
        '\u719f\u5973': 'mature',
        _legacy_mojibake('\u719f\u5973'): 'mature',
    },
    'like_level': {level: level for level in QUEEN_PROFILE_FIELD_OPTIONS['like_level']},
}

_VIDEO_CONTENT_TYPE_ALIASES = {
    'humiliation': 'humiliation',
    '\u8fb1\u9a82': 'humiliation',
    _legacy_mojibake('\u8fb1\u9a82'): 'humiliation',
    'chat': 'chat',
    '\u804a\u5929': 'chat',
    _legacy_mojibake('\u804a\u5929'): 'chat',
    'discipline': 'discipline',
    '\u8c03\u6559': 'discipline',
    _legacy_mojibake('\u8c03\u6559'): 'discipline',
}


def normalize_queen_crawl_source(value, default=QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY):
    normalized = str(value or '').strip()
    if not normalized:
        return default
    return _CRAWL_SOURCE_ALIASES.get(normalized, normalized)


def normalize_queen_profile_value(field_key, value):
    normalized = str(value or '').strip()
    if not normalized:
        return ''
    return _PROFILE_VALUE_ALIASES.get(field_key, {}).get(normalized, normalized)


def normalize_queen_video_content_type(value):
    normalized = str(value or '').strip()
    if not normalized:
        return ''
    return _VIDEO_CONTENT_TYPE_ALIASES.get(normalized, normalized)


def normalize_queen_video_content_level(value):
    return str(value or '').strip().upper()
