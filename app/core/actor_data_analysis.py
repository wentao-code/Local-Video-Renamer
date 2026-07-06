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
)


ACTOR_ANALYSIS_METRIC_MAP = {item['key']: dict(item) for item in ACTOR_ANALYSIS_METRICS}
