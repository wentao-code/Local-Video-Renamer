from app.gui.detail_summary_widgets import format_distribution_summary


def test_distribution_summary_aligns_each_column_when_requested():
    rows = [
        {'prefix': 'A', 'video_count': 1},
        {'prefix': 'LONG', 'video_count': 22},
        {'prefix': 'B', 'video_count': 333},
        {'prefix': 'X', 'video_count': 4},
        {'prefix': 'YY', 'video_count': 55},
        {'prefix': 'ZZZZZ', 'video_count': 6},
    ]

    result = format_distribution_summary(
        rows,
        'prefix',
        items_per_line=3,
        align_columns=True,
    )
    first_line, second_line = result.splitlines()

    assert first_line.index('LONG') == second_line.index('YY')
    assert first_line.index('B: 333') == second_line.index('ZZZZZ: 6')
