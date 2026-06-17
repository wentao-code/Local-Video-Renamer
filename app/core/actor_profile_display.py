from app.core.second_source_actor_text import normalize_second_source_actor_text


UNKNOWN_ACTOR_AGE_TEXT = '未知'


def has_known_actor_birthday(value):
    return bool(normalize_second_source_actor_text(value))


def normalize_actor_age_for_display(age, birthday):
    age_text = str(age or '').strip()
    if not has_known_actor_birthday(birthday):
        return UNKNOWN_ACTOR_AGE_TEXT
    return age_text
