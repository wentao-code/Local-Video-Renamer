from app.gui.library_update_status_colors import update_status_foreground


def test_update_status_foreground_uses_requested_library_colors():
    assert update_status_foreground('active') == '#16a34a'
    assert update_status_foreground('suspect') == '#ca8a04'
    assert update_status_foreground('inactive') == '#6b7280'


def test_unknown_update_status_is_not_colored_as_active():
    assert update_status_foreground('') == '#6b7280'
    assert update_status_foreground('unknown') == '#6b7280'
