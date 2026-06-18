from app.services.identity import split_actor_names
from app.services.library import extract_code_prefix


def build_video_ladder_tags(code='', author='', actor_medal_map=None, prefix_medal_map=None):
    actor_medal_map = dict(actor_medal_map or {})
    prefix_medal_map = dict(prefix_medal_map or {})

    tags = []
    seen = set()

    for actor_name in split_actor_names(author):
        for medal in actor_medal_map.get(str(actor_name or '').strip(), []):
            normalized_medal = str(medal or '').strip()
            if not normalized_medal or normalized_medal in seen:
                continue
            tags.append(normalized_medal)
            seen.add(normalized_medal)

    prefix = extract_code_prefix(code)
    for medal in prefix_medal_map.get(prefix, []):
        normalized_medal = str(medal or '').strip()
        if not normalized_medal or normalized_medal in seen:
            continue
        tags.append(normalized_medal)
        seen.add(normalized_medal)

    return tags


def build_video_ladder_tag_text(tags):
    return ' | '.join(
        str(tag or '').strip()
        for tag in (tags or [])
        if str(tag or '').strip()
    )
