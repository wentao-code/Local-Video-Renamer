from app.gui.detail_summary_widgets import format_distribution_summary, format_distribution_table


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


def test_distribution_table_uses_seven_aligned_columns_and_highlights_ranked_rows():
    rows = [
        {
            'name': f'Actor{index:02d}',
            'video_count': 20 - index,
            'ladder_tier': 'S' if index == 0 else '',
        }
        for index in range(14)
    ]

    result = format_distribution_table(
        rows,
        'name',
        columns=7,
        highlight_key='ladder_tier',
        highlight_color='#16a34a',
    )

    assert result.count('<tr>') == 2
    assert result.count('<td') == 14
    assert '<font color="#16a34a">Actor00: 20</font>' in result
    assert '<font color="#16a34a">Actor01: 19</font>' not in result
