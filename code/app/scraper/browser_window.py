def minimize_browser_window_if_needed(page, headless):
    if headless or page is None:
        return
    try:
        cdp_session = page.context.new_cdp_session(page)
        window_info = cdp_session.send('Browser.getWindowForTarget') or {}
        window_id = int(window_info.get('windowId', 0) or 0)
        if window_id <= 0:
            return
        cdp_session.send(
            'Browser.setWindowBounds',
            {'windowId': window_id, 'bounds': {'windowState': 'minimized'}},
        )
    except Exception:
        return
