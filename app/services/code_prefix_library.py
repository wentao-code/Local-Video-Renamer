import re


SEPARATED_PREFIX_RE = re.compile(r'^\s*([A-Za-z0-9]+?)[\s_-]+\d', re.IGNORECASE)
LEADING_ALPHA_PREFIX_RE = re.compile(r'^\s*([A-Za-z]+)\d', re.IGNORECASE)


def extract_code_prefix(code):
    text = str(code or '').strip().upper()
    if not text:
        return ''

    match = SEPARATED_PREFIX_RE.match(text)
    if match:
        prefix = re.sub(r'[^A-Z0-9]', '', match.group(1).upper())
        return prefix if any(ch.isalpha() for ch in prefix) else ''

    match = LEADING_ALPHA_PREFIX_RE.match(text)
    if match:
        return match.group(1).upper()

    prefix_chars = []
    for char in text:
        if char.isdigit():
            break
        if char.isalnum():
            prefix_chars.append(char)

    prefix = ''.join(prefix_chars)
    return prefix if any(ch.isalpha() for ch in prefix) else ''


class CodePrefixLibrary:
    def __init__(self, database):
        self.database = database

    def list_prefixes(self, search_text=''):
        rows = self.database.list_videos()
        grouped = {}

        for row in rows:
            prefix = extract_code_prefix(row.get('code', ''))
            if not prefix:
                continue
            grouped[prefix] = grouped.get(prefix, 0) + 1

        search = str(search_text or '').strip().upper()
        results = []
        for prefix in sorted(grouped):
            if search and search not in prefix:
                continue
            results.append({
                'prefix': prefix,
                'video_count': grouped[prefix],
                'first_updated_at': '',
                'last_updated_at': '',
            })

        return results
