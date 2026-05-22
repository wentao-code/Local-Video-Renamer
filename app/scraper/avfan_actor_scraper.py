from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from app.scraper.avfan_scraper import (
    AvfanScraper,
    accept_age_gate_if_needed,
    wait_for_manual_login_if_needed,
    wait_for_page_ready,
    wait_for_security_verification_if_needed,
)


class AvfanActorScraper:
    def __init__(self, headless=True, locale='zh-CN', profile_dir=None):
        self.browser = AvfanScraper(
            headless=headless,
            locale=locale,
            profile_dir=profile_dir,
        )
        self.actor_base_urls = {}

    def session(self):
        return self.browser.session()

    def open_listing_page(self, page, actor_name, page_number):
        actor_name = str(actor_name or '').strip()
        if not actor_name:
            raise ValueError('缺少演员姓名')

        base_url = self.actor_base_urls.get(actor_name)
        if not base_url:
            search_url = self.build_search_url(actor_name)
            page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            self._prepare_page(page)
            base_url = self._resolve_first_actor_result_url(page)
            if not base_url:
                return search_url
            self.actor_base_urls[actor_name] = base_url

        target_url = self.build_actor_page_url(base_url, page_number)
        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        self._prepare_page(page)
        return target_url

    @staticmethod
    def build_search_url(actor_name):
        safe_actor_name = quote(str(actor_name or '').strip())
        return f'https://avfan.com/search?q={safe_actor_name}&st=cast'

    @staticmethod
    def build_actor_page_url(base_url, page_number):
        parsed = urlparse(str(base_url or '').strip())
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if int(page_number or 1) <= 1:
            query.pop('page', None)
        else:
            query['page'] = str(int(page_number))
        return urlunparse(parsed._replace(query=urlencode(query)))

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

    def _prepare_page(self, page):
        wait_for_security_verification_if_needed(page, self.browser.headless)
        accept_age_gate_if_needed(page)
        wait_for_security_verification_if_needed(page, self.browser.headless)
        wait_for_manual_login_if_needed(page, self.browser.headless)
        wait_for_page_ready(page)

    @staticmethod
    def _resolve_first_actor_result_url(page):
        return page.evaluate(
            """
            () => {
                const candidates = Array.from(document.querySelectorAll('a[href]'));
                for (const link of candidates) {
                    let href = '';
                    try {
                        href = new URL(link.getAttribute('href'), location.href).href;
                    } catch (error) {
                        continue;
                    }

                    if (!href || href.includes('/movies/') || href.includes('/search?')) {
                        continue;
                    }

                    const text = (link.innerText || '').trim();
                    const image = link.querySelector('img');
                    const card = link.closest('article, li, .card, .item, .avatar, .col, div');
                    if ((text || image) && card) {
                        return href;
                    }
                }
                return '';
            }
            """
        )
