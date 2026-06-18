from app.services.identity import ActorIdentifier


class ActorLibrarySyncService:
    def __init__(self, database, actor_identifier=None):
        self.database = database
        self.actor_identifier = actor_identifier or ActorIdentifier()

    def sync_from_video_library(self):
        actors = []
        seen = set()

        for row in self.database.list_videos():
            author_text = str(row.get('author', '')).strip()
            if not author_text:
                continue

            for actor in self.actor_identifier.identify_from_author_text(author_text):
                name = str(actor.get('name', '')).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                actors.append(actor)

        return self.database.insert_missing_actors(actors)
