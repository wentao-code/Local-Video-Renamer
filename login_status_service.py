from app_config import get_setting


MANUAL_CHECK_TIMEOUT_MS = 600000
LOGIN_STATUS_LOGGED_IN = 'logged_in'
LOGIN_STATUS_LOGGED_OUT = 'logged_out'
LOGIN_STATUS_UNKNOWN = 'unknown'


def ensure_logged_in_on_home(page, headless=False):
    home_url = get_setting('SCRAPER_HOME_URL', required=True)
    login_url = get_setting('SCRAPER_LOGIN_URL', required=True)
    username = get_setting('SCRAPER_USERNAME', required=True)
    password = get_setting('SCRAPER_PASSWORD', required=True)

    open_home_page(page, home_url, headless)
    status = detect_home_login_status(page)
    if status == LOGIN_STATUS_LOGGED_IN:
        return {
            'status': status,
            'auto_login_triggered': False,
            'message': '检测到当前已经登录。',
        }

    if headless:
        raise RuntimeError(
            '检测到当前未登录。请先点击“自动登录”，或在补全信息中勾选“显示浏览器窗口”后重试。'
        )

    run_login_flow(page, login_url, home_url, username, password, headless=False)
    final_status = detect_home_login_status(page)
    if final_status != LOGIN_STATUS_LOGGED_IN:
        raise RuntimeError('登录流程已执行，但仍未检测到登录成功，请检查验证码或账号状态。')

    return {
        'status': final_status,
        'auto_login_triggered': True,
        'message': '检测到未登录，已触发自动登录并完成登录。',
    }


def open_home_page(page, home_url, headless):
    page.goto(home_url, wait_until='domcontentloaded', timeout=60000)
    wait_for_security_verification_if_needed(page, headless)
    accept_age_gate_if_needed(page)
    wait_for_security_verification_if_needed(page, headless)
    wait_for_page_ready(page)


def detect_home_login_status(page):
    wait_for_page_ready(page)
    if is_login_page(page):
        return LOGIN_STATUS_LOGGED_OUT

    clicked = click_user_menu_trigger(page)
    if not clicked:
        return LOGIN_STATUS_UNKNOWN

    page.wait_for_timeout(500)

    if is_login_page(page):
        return LOGIN_STATUS_LOGGED_OUT

    status = read_login_status_from_menu(page)
    close_user_menu(page)
    return status


def run_login_flow(page, login_url, home_url, username, password, headless):
    page.goto(login_url, wait_until='domcontentloaded', timeout=60000)
    wait_for_security_verification_if_needed(page, headless)
    accept_age_gate_if_needed(page)
    wait_for_security_verification_if_needed(page, headless)
    wait_for_page_ready(page)
    fill_login_form(page, username, password)
    wait_for_manual_login_if_needed(page, headless)
    open_home_page(page, home_url, headless)


def read_login_status_from_menu(page):
    if any_visible_text(page, ('退出登录', '设置', '通知', '收藏的清单', '最近浏览', '清单')):
        return LOGIN_STATUS_LOGGED_IN
    if any_visible_text(page, ('登录', '注册')):
        return LOGIN_STATUS_LOGGED_OUT
    return LOGIN_STATUS_UNKNOWN


def click_user_menu_trigger(page):
    try:
        return bool(page.evaluate(
            """
            () => {
                const nodes = Array.from(document.querySelectorAll('a, button, [role="button"]'));
                const candidates = nodes.filter((node) => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    const text = (node.innerText || node.textContent || '').trim();
                    if (!rect.width || !rect.height) return false;
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    if (node.offsetParent === null) return false;
                    if (rect.top > 180 || rect.bottom < 0) return false;
                    if (rect.right < window.innerWidth * 0.7) return false;
                    if (text.includes('搜索') || text.includes('全部')) return false;
                    return true;
                }).sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);

                const target = candidates[0];
                if (!target) return false;
                target.click();
                return true;
            }
            """
        ))
    except Exception:
        return False


def close_user_menu(page):
    try:
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
    except Exception:
        pass


def fill_login_form(page, username, password):
    username_selectors = (
        'input[name="email"]',
        'input[name="login"]',
        'input[type="email"]',
        'input[placeholder*="邮箱"]',
        'input[placeholder*="用户"]',
        'input[placeholder*="example@example.com"]',
        'input[type="text"]',
    )
    password_selectors = (
        'input[type="password"]',
        'input[name="password"]',
    )

    fill_first_visible(page, username_selectors, username, '未找到邮箱或用户名输入框')
    fill_first_visible(page, password_selectors, password, '未找到密码输入框')


def fill_first_visible(page, selectors, value, error_message):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1500):
                locator.click()
                locator.fill(value)
                return
        except Exception:
            continue
    raise RuntimeError(error_message)


def any_visible_text(page, texts):
    for text in texts:
        try:
            if page.get_by_text(text, exact=True).first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


def accept_age_gate_if_needed(page):
    for selector in ('text=是，我已经成年', 'text=我已经成年', 'text=Yes', 'text=I am over'):
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2500):
                button.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def wait_for_security_verification_if_needed(page, headless):
    if not is_security_verification_page(page):
        return

    if headless:
        raise RuntimeError(
            '主页出现 Cloudflare 真人验证。请先使用“自动登录”或在可见浏览器窗口中手动完成验证后再继续。'
        )

    try:
        page.wait_for_function(
            """
            () => {
                const text = (document.body?.innerText || '').toLowerCase();
                const title = (document.title || '').toLowerCase();
                const combined = `${title}\\n${text}`;
                const markers = [
                    'security verification',
                    'please complete the captcha',
                    'verification failed',
                    'cloudflare',
                    'captcha',
                    '请验证您是真人'
                ];
                const hasMarker = markers.some((marker) => combined.includes(marker));
                const hasChallengeFrame = Boolean(
                    document.querySelector('iframe[src*="challenges.cloudflare.com"]') ||
                    document.querySelector('input[name="cf-turnstile-response"]') ||
                    document.querySelector('[class*="cf-turnstile"]')
                );
                return !hasMarker && !hasChallengeFrame;
            }
            """,
            timeout=MANUAL_CHECK_TIMEOUT_MS,
        )
        wait_for_page_ready(page)
    except Exception as exc:
        raise RuntimeError('等待真人验证超时，请先在浏览器里完成验证后再继续。') from exc


def is_security_verification_page(page):
    try:
        title = page.title().lower()
    except Exception:
        title = ''

    try:
        text = page.locator('body').inner_text(timeout=1500).lower()
    except Exception:
        text = ''

    combined = f'{title}\n{text}'
    markers = (
        'security verification',
        'please complete the captcha',
        'verification failed',
        'cloudflare',
        'captcha',
        '请验证您是真人',
    )
    if any(marker in combined for marker in markers):
        return True

    for selector in (
        'iframe[src*="challenges.cloudflare.com"]',
        'input[name="cf-turnstile-response"]',
        '[class*="cf-turnstile"]',
    ):
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue

    return False


def wait_for_manual_login_if_needed(page, headless):
    if not is_login_page(page):
        return

    if headless:
        raise RuntimeError('当前仍在登录页，无法在后台模式下完成验证码登录。')

    try:
        page.wait_for_function(
            """
            () => {
                const path = location.pathname.toLowerCase();
                if (path.includes('sign_in') || path.includes('login')) return false;
                const passwordInput = document.querySelector('input[type="password"]');
                return !passwordInput;
            }
            """,
            timeout=300000,
        )
        wait_for_page_ready(page)
    except Exception as exc:
        raise RuntimeError('等待手动登录超时，请完成验证码和登录后重试。') from exc


def is_login_page(page):
    url = (page.url or '').lower()
    if 'sign_in' in url or 'login' in url:
        return True

    try:
        return page.locator('input[type="password"]').first.is_visible(timeout=1200)
    except Exception:
        return False


def wait_for_page_ready(page):
    try:
        page.wait_for_load_state('networkidle', timeout=12000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.body && document.body.innerText.trim().length > 20",
            timeout=12000,
        )
    except Exception:
        pass
    page.wait_for_timeout(600)
