import re
from datetime import date, datetime, timedelta
from statistics import median


_DATE_RE = re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})')
_STATUS_LABELS = {
    'active': '正在更新',
    'suspect': '疑似更新',
    'inactive': '断更',
}
_CATEGORY_LABELS = ('单体作品', '共演作品', '合集作品')


def build_data_dashboard(
    actor_rows,
    code_prefix_rows,
    visible_video_rows,
    filtered_video_rows=None,
    source_coverages=None,
    today=None,
):
    actors = [dict(row or {}) for row in actor_rows or []]
    prefixes = [dict(row or {}) for row in code_prefix_rows or []]
    videos = [dict(row or {}) for row in visible_video_rows or []]
    filtered_videos = [dict(row or {}) for row in filtered_video_rows or []]
    source_coverages = dict(source_coverages or {})
    reference_day = _coerce_date(today) or date.today()
    recent_cutoff = reference_day - timedelta(days=90)
    recent_videos = [
        row for row in videos
        if (_coerce_date(row.get('release_date')) or date.min) >= recent_cutoff
    ]

    actor_ages = _numeric_values(actors, 'age')
    actor_heights = _numeric_values(actors, 'height')
    actor_video_counts = _numeric_values(actors, 'video_count', include_zero=True)
    prefix_video_counts = _numeric_values(prefixes, 'video_count', include_zero=True)

    actor_items = [_actor_item(row) for row in actors]
    prefix_items = [_prefix_item(row) for row in prefixes]
    video_items = [_video_item(row) for row in videos]
    recent_video_items = [_video_item(row) for row in recent_videos]
    filtered_video_items = [_video_item(row) for row in filtered_videos]
    items_by_metric = {}

    actor_metrics = [
        _metric('actor_total', '演员总数', _count(actors), actor_items, items_by_metric),
        _metric('actor_average_age', '平均年龄', _average(actor_ages, ' 岁'), actor_items, items_by_metric),
        _metric('actor_median_age', '年龄中位数', _median(actor_ages, ' 岁'), actor_items, items_by_metric),
        _metric('actor_age_coverage', '年龄数据覆盖率', _coverage(len(actor_ages), len(actors)), actor_items, items_by_metric),
        _metric('actor_average_height', '平均身高', _average(actor_heights, ' cm'), actor_items, items_by_metric),
        _metric('actor_median_height', '身高中位数', _median(actor_heights, ' cm'), actor_items, items_by_metric),
        _metric('actor_height_coverage', '身高数据覆盖率', _coverage(len(actor_heights), len(actors)), actor_items, items_by_metric),
        _metric('actor_average_video_count', '平均有效视频数量', _average(actor_video_counts), actor_items, items_by_metric),
        _metric('actor_median_video_count', '视频数量中位数', _median(actor_video_counts), actor_items, items_by_metric),
    ]
    actor_metrics.extend(
        _status_metrics('actor', actors, actor_items, items_by_metric)
    )
    complete_actors = [row for row in actors if bool(row.get('complete_profile'))]
    zero_video_actors = [row for row in actors if _number(row.get('video_count')) == 0]
    actor_metrics.extend(
        [
            _metric(
                'actor_complete_profile',
                '完整资料演员数量',
                _count(complete_actors),
                [_actor_item(row) for row in complete_actors],
                items_by_metric,
            ),
            _metric(
                'actor_zero_video',
                '无有效视频演员数量',
                _count(zero_video_actors),
                [_actor_item(row) for row in zero_video_actors],
                items_by_metric,
            ),
            _metric(
                'actor_recent_90_days',
                '近90天新增视频数量',
                _count(recent_videos),
                recent_video_items,
                items_by_metric,
            ),
        ]
    )

    prefix_metrics = [
        _metric('code_prefix_total', '番号总数', _count(prefixes), prefix_items, items_by_metric),
        _metric(
            'code_prefix_average_video_count',
            '平均视频数量',
            _average(prefix_video_counts),
            prefix_items,
            items_by_metric,
        ),
        _metric(
            'code_prefix_median_video_count',
            '视频数量中位数',
            _median(prefix_video_counts),
            prefix_items,
            items_by_metric,
        ),
    ]
    prefix_metrics.extend(
        _status_metrics('code_prefix', prefixes, prefix_items, items_by_metric)
    )
    zero_video_prefixes = [row for row in prefixes if _number(row.get('video_count')) == 0]
    max_prefix = max(prefixes, key=lambda row: _number(row.get('video_count')), default={})
    max_prefix_value = '暂无'
    if max_prefix:
        max_prefix_value = '{}（{}）'.format(
            str(max_prefix.get('prefix', '') or ''),
            int(_number(max_prefix.get('video_count'))),
        )
    prefix_metrics.extend(
        [
            _metric(
                'code_prefix_zero_video',
                '无有效视频番号数量',
                _count(zero_video_prefixes),
                [_prefix_item(row) for row in zero_video_prefixes],
                items_by_metric,
            ),
            _metric(
                'code_prefix_recent_90_days',
                '近90天新增视频数量',
                _count(recent_videos),
                recent_video_items,
                items_by_metric,
            ),
            _metric(
                'code_prefix_max_video',
                '视频数量最多的番号',
                max_prefix_value,
                [_prefix_item(max_prefix)] if max_prefix else [],
                items_by_metric,
            ),
        ]
    )

    category_rows = {
        label: [row for row in videos if str(row.get('video_category', '') or '').strip() == label]
        for label in _CATEGORY_LABELS
    }
    uncategorized_videos = [
        row for row in videos
        if str(row.get('video_category', '') or '').strip() not in _CATEGORY_LABELS
    ]
    missing_actor_videos = [row for row in videos if not str(row.get('author', '') or '').strip()]
    quality_metrics = [
        _metric('video_valid_total', '有效视频总数', _count(videos), video_items, items_by_metric),
        _metric(
            'video_filtered_total',
            '被过滤视频数量',
            _count(filtered_videos),
            filtered_video_items,
            items_by_metric,
        ),
        _metric(
            'video_uncategorized',
            '未分类视频数量',
            _count(uncategorized_videos),
            [_video_item(row) for row in uncategorized_videos],
            items_by_metric,
        ),
        _metric(
            'video_missing_actor',
            '缺少演员信息的视频数量',
            _count(missing_actor_videos),
            [_video_item(row) for row in missing_actor_videos],
            items_by_metric,
        ),
    ]
    for key, label in (
        ('single', '单体作品'),
        ('co_star', '共演作品'),
        ('collection', '合集作品'),
    ):
        rows = category_rows[label]
        quality_metrics.append(
            _metric(
                f'video_category_{key}',
                f'{label}数量及占比',
                _count_with_percent(len(rows), len(videos)),
                [_video_item(row) for row in rows],
                items_by_metric,
            )
        )
    quality_metrics.append(
        _metric(
            'video_recent_90_days',
            '近90天新增视频数量',
            _count(recent_videos),
            recent_video_items,
            items_by_metric,
        )
    )
    for source_key, title in (('avfan', '天陨阁补全覆盖率'), ('javtxt', '辛聚阁补全覆盖率')):
        coverage_value = source_coverages.get(source_key, (0, 0))
        completed = int((coverage_value or (0, 0))[0] or 0)
        total = int((coverage_value or (0, 0))[1] or 0)
        source_items = list((coverage_value or (0, 0, []))[2] or []) if len(coverage_value) > 2 else []
        quality_metrics.append(
            _metric(
                f'{source_key}_coverage',
                title,
                _coverage(completed, total),
                source_items,
                items_by_metric,
            )
        )

    return {
        'sections': [
            {'key': 'actors', 'title': '演员信息', 'metrics': actor_metrics},
            {'key': 'code_prefixes', 'title': '番号信息', 'metrics': prefix_metrics},
            {'key': 'quality', 'title': '数据质量', 'metrics': quality_metrics},
        ],
        'items_by_metric': items_by_metric,
    }


def _status_metrics(prefix, rows, items, item_map):
    metrics = []
    for status_key in ('active', 'suspect', 'inactive'):
        matching = [row for row in rows if str(row.get('update_status', '') or '') == status_key]
        if prefix == 'actor':
            matching_items = [_actor_item(row) for row in matching]
        else:
            matching_items = [_prefix_item(row) for row in matching]
        metrics.append(
            _metric(
                f'{prefix}_{status_key}',
                _STATUS_LABELS[status_key],
                _count_with_percent(len(matching), len(rows)),
                matching_items,
                item_map,
            )
        )
    return metrics


def _metric(key, title, value, items, item_map):
    normalized_items = [dict(item or {}) for item in items or []]
    item_map[key] = normalized_items
    return {
        'key': key,
        'title': title,
        'value': str(value),
        'clickable': bool(normalized_items),
    }


def _actor_item(row):
    return {
        'entity_type': 'actor',
        'key': str(row.get('name', '') or ''),
        'name': str(row.get('name', '') or ''),
        'value': str(int(_number(row.get('video_count')))),
    }


def _prefix_item(row):
    return {
        'entity_type': 'code_prefix',
        'key': str(row.get('prefix', '') or ''),
        'name': str(row.get('prefix', '') or ''),
        'value': str(int(_number(row.get('video_count')))),
    }


def _video_item(row):
    return {
        'entity_type': 'video',
        'key': str(row.get('code', '') or ''),
        'name': str(row.get('code', '') or ''),
        'title': str(row.get('title', '') or ''),
        'author': str(row.get('author', '') or ''),
        'category': str(row.get('video_category', '') or ''),
        'value': str(row.get('release_date', '') or ''),
    }


def _numeric_values(rows, key, include_zero=False):
    values = []
    for row in rows:
        raw_value = row.get(key)
        if raw_value in (None, ''):
            continue
        numeric_value = _number(raw_value)
        if numeric_value > 0 or include_zero:
            values.append(numeric_value)
    return values


def _number(value):
    if value in (None, ''):
        return 0.0
    match = re.search(r'-?\d+(?:\.\d+)?', str(value))
    return float(match.group(0)) if match else 0.0


def _average(values, suffix=''):
    if not values:
        return '暂无'
    return f'{sum(values) / len(values):.1f}{suffix}'


def _median(values, suffix=''):
    if not values:
        return '暂无'
    return f'{float(median(values)):.1f}{suffix}'


def _coverage(count, total):
    if not total:
        return '0.0%'
    return f'{(float(count) / float(total)) * 100.0:.1f}%'


def _count(rows):
    return str(len(rows))


def _count_with_percent(count, total):
    percent = 0.0 if not total else (float(count) / float(total)) * 100.0
    return f'{int(count)}（{percent:.1f}%）'


def _coerce_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DATE_RE.search(str(value or ''))
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None
