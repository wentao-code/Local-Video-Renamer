from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, CODE_PREFIX_LIBRARY_TARGET


KAN_SHUI_COMBO = 'kan_shui'
FU_SHUI_COMBO = 'fu_shui'
DEFAULT_COMBO_KEY = KAN_SHUI_COMBO


COMBO_LABELS = {
    KAN_SHUI_COMBO: '坎水',
    FU_SHUI_COMBO: '府水',
}

COMBO_TASK_DEFINITIONS = {
    KAN_SHUI_COMBO: (
        {
            'task_key': 'code_prefix_avfan',
            'task_label': '番号库 / 天限阁',
            'target_type': CODE_PREFIX_LIBRARY_TARGET,
            'source_key': AVFAN_VIDEO_SOURCE,
            'uses_avfan_profile': True,
        },
        {
            'task_key': 'actor_javtxt',
            'task_label': '演员库 / 辛聚谷',
            'target_type': ACTOR_LIBRARY_TARGET,
            'source_key': JAVTXT_VIDEO_SOURCE,
            'uses_avfan_profile': False,
        },
    ),
    FU_SHUI_COMBO: (
        {
            'task_key': 'code_prefix_javtxt',
            'task_label': '番号库 / 辛聚谷',
            'target_type': CODE_PREFIX_LIBRARY_TARGET,
            'source_key': JAVTXT_VIDEO_SOURCE,
            'uses_avfan_profile': False,
        },
        {
            'task_key': 'actor_avfan',
            'task_label': '演员库 / 天限阁',
            'target_type': ACTOR_LIBRARY_TARGET,
            'source_key': AVFAN_VIDEO_SOURCE,
            'uses_avfan_profile': True,
        },
    ),
}


def normalize_combo_key(combo_key):
    if combo_key in COMBO_TASK_DEFINITIONS:
        return combo_key
    return DEFAULT_COMBO_KEY


def get_combo_label(combo_key):
    return COMBO_LABELS[normalize_combo_key(combo_key)]


def get_combo_tasks(combo_key):
    return COMBO_TASK_DEFINITIONS[normalize_combo_key(combo_key)]
