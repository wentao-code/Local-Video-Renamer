from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, DEFAULT_VIDEO_ENRICHMENT_SOURCE
from app.core.enrichment_targets import (
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.services.actor_enrichment import ActorEnrichmentService
from app.services.code_prefix_enrichment import CodePrefixEnrichmentService
from app.services.video_source_enrichment_service import VideoSourceEnrichmentService


class LibraryEnrichmentService:
    def __init__(
        self,
        database,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
    ):
        self.database = database
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.should_stop = should_stop

    def run(self, target_type, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        if not target_type:
            target_type = VIDEO_LIBRARY_TARGET

        if target_type == VIDEO_LIBRARY_TARGET:
            service = VideoSourceEnrichmentService(
                self.database,
                source_key=source_key,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                should_stop=self.should_stop,
            )
            result = service.enrich_next_videos(limit)
            result.setdefault('entity_label', '视频')
            return result

        fixed_source = AVFAN_VIDEO_SOURCE

        if target_type == CODE_PREFIX_LIBRARY_TARGET:
            service = CodePrefixEnrichmentService(
                self.database,
                show_browser=self.show_browser,
                should_stop=self.should_stop,
            )
            result = service.enrich_next_prefixes(limit)
            result.setdefault('source_key', fixed_source)
            return result

        if target_type == ACTOR_LIBRARY_TARGET:
            service = ActorEnrichmentService(
                self.database,
                show_browser=self.show_browser,
                should_stop=self.should_stop,
            )
            result = service.enrich_next_actors(limit)
            result.setdefault('source_key', fixed_source)
            return result

        raise ValueError(f'未知补全目标: {target_type}')
