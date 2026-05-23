import re


INVALID_CHAR_TRANSLATION = str.maketrans(
    {
        '<': '＜',
        '>': '＞',
        ':': '：',
        '"': '＂',
        '/': '／',
        '\\': '＼',
        '|': '｜',
        '?': '？',
        '*': '＊',
    }
)
CONTROL_CHAR_RE = re.compile(r'[\x00-\x1f]')
WHITESPACE_RE = re.compile(r'\s+')
RESERVED_WINDOWS_NAMES = {
    'CON',
    'PRN',
    'AUX',
    'NUL',
    'COM1',
    'COM2',
    'COM3',
    'COM4',
    'COM5',
    'COM6',
    'COM7',
    'COM8',
    'COM9',
    'LPT1',
    'LPT2',
    'LPT3',
    'LPT4',
    'LPT5',
    'LPT6',
    'LPT7',
    'LPT8',
    'LPT9',
}


def sanitize_windows_filename_part(text, fallback='未命名'):
    sanitized = str(text or '').translate(INVALID_CHAR_TRANSLATION)
    sanitized = CONTROL_CHAR_RE.sub('', sanitized)
    sanitized = WHITESPACE_RE.sub(' ', sanitized).strip(' .')

    if not sanitized:
        sanitized = fallback

    if sanitized.upper() in RESERVED_WINDOWS_NAMES:
        sanitized = f'{sanitized}_'

    return sanitized


def sanitize_windows_extension(extension, fallback='.mp4'):
    sanitized = str(extension or '').strip()
    if not sanitized:
        return fallback
    if sanitized.startswith('.'):
        body = sanitized[1:]
    else:
        body = sanitized

    body = sanitize_windows_filename_part(body, fallback=fallback.lstrip('.'))
    return f'.{body}'
