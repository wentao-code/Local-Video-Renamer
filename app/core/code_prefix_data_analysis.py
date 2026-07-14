CODE_PREFIX_ANALYSIS_METRICS = (
    {
        'key': 'collection_ratio',
        'label_key': 'data_center.analysis.collection_ratio',
    },
    {
        'key': 'video_count',
        'label_key': 'data_center.analysis.video_count',
        'value_type': 'range_count',
        'ranges': (
            {'key': '0_49', 'label': '50\u4e2a\u4ee5\u4e0b', 'minimum': 0, 'maximum': 49},
            {'key': '50_99', 'label': '50~99\u4e2a', 'minimum': 50, 'maximum': 99},
            {'key': '100_299', 'label': '100~299\u4e2a', 'minimum': 100, 'maximum': 299},
            {'key': '300_799', 'label': '300~799\u4e2a', 'minimum': 300, 'maximum': 799},
            {'key': '800_plus', 'label': '800\u4e2a\u4ee5\u4e0a', 'minimum': 800, 'maximum': None},
        ),
    },
)


CODE_PREFIX_ANALYSIS_METRIC_MAP = {item['key']: dict(item) for item in CODE_PREFIX_ANALYSIS_METRICS}
