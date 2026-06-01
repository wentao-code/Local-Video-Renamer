LADDER_BOARD_ACTOR = 'juese'
LADDER_BOARD_CODE_PREFIX = 'tianyin'

LADDER_ENTITY_ACTOR = 'actor'
LADDER_ENTITY_CODE_PREFIX = 'code_prefix'

LADDER_VIEW_CANDIDATES = 'candidates'
LADDER_VIEW_SELECTED = 'selected'

LADDER_TIER_S = 'S'
LADDER_TIER_A = 'A'
LADDER_TIER_B = 'B'
LADDER_TIER_C = 'C'
LADDER_TIERS = (
    LADDER_TIER_S,
    LADDER_TIER_A,
    LADDER_TIER_B,
    LADDER_TIER_C,
)

LADDER_BOARD_CONFIGS = {
    LADDER_BOARD_ACTOR: {
        'board_key': LADDER_BOARD_ACTOR,
        'entity_type': LADDER_ENTITY_ACTOR,
        'board_label_key': 'ladder.board_actor',
        'entity_label_key': 'ladder.actor_label',
    },
    LADDER_BOARD_CODE_PREFIX: {
        'board_key': LADDER_BOARD_CODE_PREFIX,
        'entity_type': LADDER_ENTITY_CODE_PREFIX,
        'board_label_key': 'ladder.board_code_prefix',
        'entity_label_key': 'ladder.code_prefix_label',
    },
}

_TIER_ORDER = {
    LADDER_TIER_S: 0,
    LADDER_TIER_A: 1,
    LADDER_TIER_B: 2,
    LADDER_TIER_C: 3,
}


def normalize_ladder_board_key(board_key):
    normalized_key = str(board_key or '').strip().lower()
    return normalized_key if normalized_key in LADDER_BOARD_CONFIGS else LADDER_BOARD_ACTOR


def get_ladder_board_config(board_key):
    normalized_key = normalize_ladder_board_key(board_key)
    return dict(LADDER_BOARD_CONFIGS[normalized_key])


def normalize_ladder_entity_type(entity_type):
    normalized_type = str(entity_type or '').strip().lower()
    if normalized_type in {LADDER_ENTITY_ACTOR, LADDER_ENTITY_CODE_PREFIX}:
        return normalized_type
    return ''


def normalize_ladder_tier(tier):
    normalized_tier = str(tier or '').strip().upper()
    return normalized_tier if normalized_tier in LADDER_TIERS else ''


def ladder_tier_sort_key(tier):
    return _TIER_ORDER.get(normalize_ladder_tier(tier), len(_TIER_ORDER))
