import json

from app.core.runtime_config import (
    get_probe_max_entries,
    get_probe_max_lines,
    get_probe_show_browser,
    get_probe_target_url,
)
from app.tools.avfan_page_probe import probe_url


TARGET_URL = get_probe_target_url()
SHOW_BROWSER = get_probe_show_browser()
MAX_LINES = get_probe_max_lines()
MAX_ENTRIES = get_probe_max_entries()


def main():
    if not TARGET_URL.strip():
        raise ValueError('请先在 .env 中设置 PROBE_TARGET_URL')

    result = probe_url(
        url=TARGET_URL.strip(),
        show_browser=SHOW_BROWSER,
        max_lines=MAX_LINES,
        max_entries=MAX_ENTRIES,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
