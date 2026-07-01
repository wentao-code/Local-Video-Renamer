from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
)
from app.core.enrichment_targets import (
    ACTOR_BIRTHDAY_TARGET,
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.services.enrichment import (
    ActorBaomuEnrichmentService,
    ActorBinghuoEnrichmentService,
    ActorEnrichmentService,
    ActorJavtxtEnrichmentService,
    CodePrefixEnrichmentService,
    CodePrefixJavtxtEnrichmentService,
    VideoSourceEnrichmentService,
)
from app.services.enrichment.supplement_enrichment import (
    ActorSupplementEnrichmentService,
    CodePrefixSupplementEnrichmentService,
    VideoSupplementEnrichmentService,
)


class LibraryEnrichmentService:
    def __init__(
        self,
        database,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
        video_candidate_filter=None,
        video_filter_settings=None,
    ):
        self.database = database
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.should_stop = should_stop
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.video_candidate_filter = video_candidate_filter
        self.video_filter_settings = video_filter_settings

    def run(self, target_type, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        if not target_type:
            target_type = VIDEO_LIBRARY_TARGET

        if self.logger is not None:
            self.logger.log(
                'INFO',
                '任务调度开始',
                requested_target_type=target_type,
                requested_source_key=source_key or '',
                limit=max(0, int(limit or 0)),
                show_browser=bool(self.show_browser),
                cooldown_before_search=bool(self.cooldown_before_search),
            )

        if target_type == VIDEO_LIBRARY_TARGET:
            if source_key == SUPPLEMENT_TASK_SOURCE:
                service = VideoSupplementEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    filter_settings=self.video_filter_settings,
                )
                result = service.enrich_next_videos(limit)
            else:
                service = VideoSourceEnrichmentService(
                    self.database,
                    source_key=source_key,
                    show_browser=self.show_browser,
                    cooldown_before_search=self.cooldown_before_search,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    candidate_filter=self.video_candidate_filter,
                )
                result = service.enrich_next_videos(limit)
            result.setdefault('entity_label', '视频')
            return result

        if target_type == CODE_PREFIX_LIBRARY_TARGET:
            if source_key == SUPPLEMENT_TASK_SOURCE:
                service = CodePrefixSupplementEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    filter_settings=self.video_filter_settings,
                )
            elif source_key == JAVTXT_VIDEO_SOURCE:
                service = CodePrefixJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                )
            else:
                service = CodePrefixEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                )
            result = service.enrich_next_prefixes(limit)
            result.setdefault(
                'source_key',
                source_key or (SUPPLEMENT_TASK_SOURCE if source_key == SUPPLEMENT_TASK_SOURCE else AVFAN_VIDEO_SOURCE),
            )
            return result

        if target_type == ACTOR_LIBRARY_TARGET:
            if source_key == SUPPLEMENT_TASK_SOURCE:
                service = ActorSupplementEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    filter_settings=self.video_filter_settings,
                )
            elif source_key == JAVTXT_VIDEO_SOURCE:
                service = ActorJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                )
            else:
                service = ActorEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                )
            result = service.enrich_next_actors(limit)
            result.setdefault(
                'source_key',
                source_key or (SUPPLEMENT_TASK_SOURCE if source_key == SUPPLEMENT_TASK_SOURCE else AVFAN_VIDEO_SOURCE),
            )
            return result

        if target_type == ACTOR_BIRTHDAY_TARGET:
            service_class = ActorBaomuEnrichmentService if source_key == BAOMU_ACTOR_SOURCE else ActorBinghuoEnrichmentService
            service = service_class(
                self.database,
                show_browser=self.show_browser,
                should_stop=self.should_stop,
                progress_tracker=self.progress_tracker,
                logger=self.logger,
            )
            result = service.enrich_next_actors(limit)
            result.setdefault('source_key', source_key or BINGHUO_ACTOR_SOURCE)
            return result

        raise ValueError(f'未知补全目标: {target_type}')
