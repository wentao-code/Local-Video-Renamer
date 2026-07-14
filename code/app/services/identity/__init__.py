"""Actor identity helpers.

Import from here for actor-name normalization, splitting, ignore rules, and
the lightweight ActorIdentifier utility.
"""

from app.services.identity.actor_identifier import (
    ActorIdentifier,
    IGNORED_ACTOR_NAMES,
    is_ignored_actor_name,
    normalize_actor_name,
    split_actor_names,
)


__all__ = [
    'ActorIdentifier',
    'IGNORED_ACTOR_NAMES',
    'is_ignored_actor_name',
    'normalize_actor_name',
    'split_actor_names',
]
