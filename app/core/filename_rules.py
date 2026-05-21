import re


DEFAULT_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.mov')
TITLE_EDGE_CHARS = r'\s\-_【】\[\]{}()（）《》<>""''“”‘’.,。，！？!?~、；;：:'
VIDEO_SUFFIX_RE = re.compile(r'\.(mp4|mkv|avi|wmv|mov)\s*$', re.I)


def strip_title_suffix_noise(title):
    previous = None
    clean_title = title
    while clean_title != previous:
        previous = clean_title
        clean_title = VIDEO_SUFFIX_RE.sub('', clean_title)
        clean_title = re.sub(
            rf'^[{TITLE_EDGE_CHARS}]+|[{TITLE_EDGE_CHARS}]+$',
            '',
            clean_title,
        )
    return clean_title.strip()


def normalize_text_spacing(text):
    return re.sub(r'\s+', ' ', text).strip()


def clean_video_title(code, author, raw_name):
    clean_title = re.sub(re.escape(code), '', raw_name, flags=re.I)
    if author:
        clean_title = clean_title.replace(author, '')

    clean_title = normalize_text_spacing(strip_title_suffix_noise(clean_title))

    if not clean_title:
        clean_title = normalize_text_spacing(strip_title_suffix_noise(raw_name))

    return clean_title


def extract_code_from_filename(filename):
    # 支持 CMV-001, CMV_001, CMV 001, CMV001 等格式。
    match = re.search(r'([a-zA-Z]+)[-_ ]?(\d+)', filename)
    if match:
        letters = match.group(1).upper()
        numbers = match.group(2)
        return f"{letters}-{numbers}"
    return None


def build_normalized_filename(metadata, extension):
    if metadata.author:
        return f"【{metadata.code}】-{metadata.title}-{{{metadata.author}}}{extension}"
    return f"【{metadata.code}】-{metadata.title}{extension}"
