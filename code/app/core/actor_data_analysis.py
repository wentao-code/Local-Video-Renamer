ACTOR_ANALYSIS_METRICS = (
    {
        'key': 'age',
        'label_key': 'data_center.analysis.age',
        'source': 'actor',
        'field': 'age',
        'suffix': '岁',
    },
    {
        'key': 'height',
        'label_key': 'data_center.analysis.height',
        'source': 'enrichment',
        'field': 'binghuo_height',
        'suffix': ' cm',
    },
    {
        'key': 'bust',
        'label_key': 'data_center.analysis.bust',
        'source': 'enrichment',
        'field': 'binghuo_bust',
        'suffix': ' cm',
    },
    {
        'key': 'cup',
        'label_key': 'data_center.analysis.cup',
        'source': 'enrichment',
        'field': 'binghuo_cup',
        'fallback_field': 'baomu_cup',
        'value_type': 'categorical',
        'sort_order': 'desc',
    },
    {
        'key': 'waist',
        'label_key': 'data_center.analysis.waist',
        'source': 'enrichment',
        'field': 'binghuo_waist',
        'suffix': ' cm',
    },
    {
        'key': 'hip',
        'label_key': 'data_center.analysis.hip',
        'source': 'enrichment',
        'field': 'binghuo_hip',
        'suffix': ' cm',
    },
    {
        'key': 'video_count',
        'label_key': 'data_center.analysis.video_count',
        'value_type': 'range_count',
        'ranges': (
            {'key': '0_4', 'label': '5\u4e2a\u4ee5\u4e0b', 'minimum': 0, 'maximum': 4},
            {'key': '5_9', 'label': '5~9\u4e2a', 'minimum': 5, 'maximum': 9},
            {'key': '10_29', 'label': '10~29\u4e2a', 'minimum': 10, 'maximum': 29},
            {'key': '30_79', 'label': '30~79\u4e2a', 'minimum': 30, 'maximum': 79},
            {'key': '80_plus', 'label': '80\u4e2a\u4ee5\u4e0a', 'minimum': 80, 'maximum': None},
        ),
    },
)


ACTOR_ANALYSIS_METRIC_MAP = {item['key']: dict(item) for item in ACTOR_ANALYSIS_METRICS}
