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
        planned_items=None,
    ):
        self.database = database
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.should_stop = should_stop
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.video_candidate_filter = video_candidate_filter
        self.video_filter_settings = video_filter_settings
        self.planned_items = [dict(item or {}) for item in (planned_items or [])]

    @staticmethod
    def _unique_values(items, key_name):
        values = []
        seen = set()
        for item in items or []:
            value = str((item or {}).get(key_name, '') or '').strip()
            if not value or value in seen:
                continue
            values.append(value)
            seen.add(value)
        return values

    def _planned_codes(self):
        return self._unique_values(self.planned_items, 'code')

    def _planned_prefixes(self):
        return self._unique_values(self.planned_items, 'prefix')

    def _planned_actor_names(self):
        return self._unique_values(self.planned_items, 'actor_name')

    def _planned_video_candidate_filter(self):
        planned_codes = set(self._planned_codes())
        existing_filter = self.video_candidate_filter
        if not planned_codes:
            return existing_filter

        def candidate_filter(row):
            code = str((row or {}).get('code', '') or '').strip()
            if code not in planned_codes:
                return False
            return bool(existing_filter(row)) if callable(existing_filter) else True

        return candidate_filter

    def run(self, target_type, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE, batch_mode=False):
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
            if source_key in {AVFAN_VIDEO_SOURCE, SUPPLEMENT_TASK_SOURCE}:
                service = VideoSupplementEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    filter_settings=self.video_filter_settings,
                    planned_items=self.planned_items,
                )
                result = service.enrich_next_videos(limit, estimate_remaining=batch_mode)
            else:
                service = VideoSourceEnrichmentService(
                    self.database,
                    source_key=source_key,
                    show_browser=self.show_browser,
                    cooldown_before_search=self.cooldown_before_search,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    candidate_filter=self._planned_video_candidate_filter(),
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
                    planned_items=self.planned_items,
                )
            elif source_key == JAVTXT_VIDEO_SOURCE:
                service = CodePrefixJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    planned_prefixes=self._planned_prefixes(),
                    planned_items=self.planned_items,
                )
            else:
                service = CodePrefixEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    planned_prefixes=self._planned_prefixes(),
                )
            if source_key == SUPPLEMENT_TASK_SOURCE:
                result = service.enrich_next_prefixes(limit, estimate_remaining=batch_mode)
            else:
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
                    planned_items=self.planned_items,
                )
            elif source_key == JAVTXT_VIDEO_SOURCE:
                service = ActorJavtxtEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    planned_actor_names=self._planned_actor_names(),
                    planned_items=self.planned_items,
                )
            else:
                service = ActorEnrichmentService(
                    self.database,
                    show_browser=self.show_browser,
                    should_stop=self.should_stop,
                    progress_tracker=self.progress_tracker,
                    logger=self.logger,
                    planned_actor_names=self._planned_actor_names(),
                )
            if source_key == SUPPLEMENT_TASK_SOURCE:
                result = service.enrich_next_actors(limit, estimate_remaining=batch_mode)
            else:
                result = service.enrich_next_actors(limit)
            result.setdefault(
                'source_key',
                source_key or (SUPPLEMENT_TASK_SOURCE if source_key == SUPPLEMENT_TASK_SOURCE else AVFAN_VIDEO_SOURCE),
            )
            return result

        if target_type == ACTOR_BIRTHDAY_TARGET:
            if not self.planned_items:
                raise ValueError('演员生日补全必须先从候选表领取任务。')
            service_class = ActorBaomuEnrichmentService if source_key == BAOMU_ACTOR_SOURCE else ActorBinghuoEnrichmentService
            service = service_class(
                self.database,
                show_browser=self.show_browser,
                should_stop=self.should_stop,
                progress_tracker=self.progress_tracker,
                logger=self.logger,
                planned_actor_names=self._planned_actor_names(),
                planned_items=self.planned_items,
            )
            result = service.enrich_next_actors(limit)
            result.setdefault('source_key', source_key or BINGHUO_ACTOR_SOURCE)
            return result

        raise ValueError(f'未知补全目标: {target_type}')
