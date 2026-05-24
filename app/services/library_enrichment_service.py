from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, DEFAULT_VIDEO_ENRICHMENT_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_targets import (
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.services.actor_enrichment import ActorEnrichmentService
from app.services.actor_javtxt_enrichment import ActorJavtxtEnrichmentService
from app.services.code_prefix_enrichment import CodePrefixEnrichmentService
from app.services.code_prefix_javtxt_enrichment import CodePrefixJavtxtEnrichmentService
from app.services.video_source_enrichment_service import VideoSourceEnrichmentService


class LibraryEnrichmentService:
    def __init__(
        self,
        database,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
        progress_tracker=None,
    ):
        self.database = database
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.should_stop = should_stop
        self.progress_tracker = progress_tracker

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
                progress_tracker=self.progress_tracker,
            )
            result = service.enrich_next_videos(limit)
            result.setdefault('entity_label', '视频')
            return result

        if target_type == CODE_PREFIX_LIBRARY_TARGET:
            if source_key == JAVTXT_VIDEO_SOURCE:
                service = CodePrefixJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                )
            else:
                service = CodePrefixEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                )
            result = service.enrich_next_prefixes(limit)
            result.setdefault('source_key', source_key or AVFAN_VIDEO_SOURCE)
            return result

        if target_type == ACTOR_LIBRARY_TARGET:
            if source_key == JAVTXT_VIDEO_SOURCE:
                service = ActorJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                )
            else:
                service = ActorEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                )
            result = service.enrich_next_actors(limit)
            result.setdefault('source_key', source_key or AVFAN_VIDEO_SOURCE)
            return result

        raise ValueError(f'未知补全目标: {target_type}')
