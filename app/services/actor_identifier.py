import re

from app.core.filename_rules import normalize_text_spacing


IGNORED_ACTOR_NAMES = {'无', '暂无', '未知', '无记录', 'none', 'null', 'n/a', 'na', '-'}


class ActorIdentifier:
    def __init__(self):
        self.actor_profiles = {}

    def load_profiles(self):
        self.actor_profiles = {}
        return self.actor_profiles

    def ensure_profiles_loaded(self):
        if self.actor_profiles is None:
            self.load_profiles()

    def identify_from_author_text(self, author_text):
        self.ensure_profiles_loaded()

        actors = []
        seen = set()
        for name in split_actor_names(author_text):
            if name in seen:
                continue
            seen.add(name)
            actors.append(
                {
                    'name': name,
                    'birthday': '',
                    'age': '',
                    'matched': False,
                }
            )
        return actors

    def identify_from_plans(self, plans):
        actors = []
        seen = set()

        for plan in plans or []:
            author_text = getattr(getattr(plan, 'metadata', None), 'author', '')
            for actor in self.identify_from_author_text(author_text):
                if actor['name'] in seen:
                    continue
                seen.add(actor['name'])
                actors.append(actor)

        return actors


def split_actor_names(author_text):
    author_text = normalize_text_spacing(author_text or '')
    if not author_text:
        return []

    raw_names = re.split(r'[\s,，、/;；]+', author_text)
    return [
        name
        for name in (normalize_actor_name(raw_name) for raw_name in raw_names)
        if name and not is_ignored_actor_name(name)
    ]


def normalize_actor_name(name):
    return normalize_text_spacing(name).strip('、,，/;； \t\r\n')


def is_ignored_actor_name(name):
    return normalize_actor_name(name).lower() in IGNORED_ACTOR_NAMES
