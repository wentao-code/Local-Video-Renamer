from app.core.enrichment_targets import (
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.services.code_prefix_enrichment import CodePrefixEnrichmentService
from app.services.video_enrichment import VideoEnrichmentService


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

    def run(self, target_type, limit):
        if not target_type:
            target_type = VIDEO_LIBRARY_TARGET

        if target_type == VIDEO_LIBRARY_TARGET:
            service = VideoEnrichmentService(
                self.database,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                should_stop=self.should_stop,
            )
            result = service.enrich_next_videos(limit)
            result.setdefault('entity_label', '视频')
            result.setdefault('remaining_label', '剩余未补全视频')
            return result

        if target_type == CODE_PREFIX_LIBRARY_TARGET:
            service = CodePrefixEnrichmentService(
                self.database,
                show_browser=self.show_browser,
                should_stop=self.should_stop,
            )
            return service.enrich_next_prefixes(limit)

        if target_type == ACTOR_LIBRARY_TARGET:
            raise RuntimeError('演员库补全暂未实现，请先使用“视频库”或“番号库”。')

        raise ValueError(f'未知补全目标: {target_type}')
