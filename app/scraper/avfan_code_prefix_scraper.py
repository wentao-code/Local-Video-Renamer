from urllib.parse import quote

from app.scraper.avfan_scraper import (
    AvfanScraper,
    accept_age_gate_if_needed,
    wait_for_manual_login_if_needed,
    wait_for_page_ready,
    wait_for_security_verification_if_needed,
)


class AvfanCodePrefixScraper:
    def __init__(self, headless=True, locale='zh-CN', profile_dir=None):
        self.browser = AvfanScraper(
            headless=headless,
            locale=locale,
            profile_dir=profile_dir,
        )

    def session(self):
        return self.browser.session()

    def open_listing_page(self, page, prefix, page_number):
        url = self.build_listing_url(prefix, page_number)
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        wait_for_security_verification_if_needed(page, self.browser.headless)
        accept_age_gate_if_needed(page)
        wait_for_security_verification_if_needed(page, self.browser.headless)
        wait_for_manual_login_if_needed(page, self.browser.headless)
        wait_for_page_ready(page)
        return url

    @staticmethod
    def build_listing_url(prefix, page_number):
        safe_prefix = quote(str(prefix or '').strip().upper())
        return f'https://avfan.com/zh-CN/number_letters/{safe_prefix}?page={int(page_number)}'

    @staticmethod
    def detect_total_pages(page):
        total_pages = page.evaluate(
            """
            () => {
                const pages = new Set();
                for (const link of document.querySelectorAll('a[href*="page="]')) {
                    try {
                        const href = new URL(link.href, location.href);
                        const value = Number.parseInt(href.searchParams.get('page') || '', 10);
                        if (Number.isFinite(value) && value > 0) {
                            pages.add(value);
                        }
                    } catch (error) {
                    }
                }
                return pages.size ? Math.max(...pages) : 1;
            }
            """
        )
        try:
            return max(1, int(total_pages or 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def collect_page_entries(page):
        return page.evaluate(
            """
            () => {
                const rows = [];
                const seen = new Set();
                const links = Array.from(document.querySelectorAll('a[href*="/movies/"]'));
                for (const link of links) {
                    let href = '';
                    try {
                        href = new URL(link.getAttribute('href'), location.href).href;
                    } catch (error) {
                        continue;
                    }
                    if (!href || seen.has(href)) {
                        continue;
                    }
                    seen.add(href);

                    const container =
                        link.closest('article, li, .card, .item, .movie, .col, .col-md-2, .col-md-3, .col-sm-3, .col-xs-6, div') ||
                        link.parentElement ||
                        link;
                    const text = (container.innerText || link.innerText || '').trim();
                    if (!text) {
                        continue;
                    }
                    rows.push({ href, text });
                }
                return rows;
            }
            """
        )

