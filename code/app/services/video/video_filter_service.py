from app.core.video_filter_rules import (
    RuleSet,
)
from app.core.video_filter_settings import load_video_filter_settings


class VideoFilterService:
    def __init__(self, settings_loader=None):
        self.settings_loader = settings_loader or load_video_filter_settings

    def load_settings(self):
        return self.load_ruleset().to_settings()

    def load_ruleset(self, settings=None, scope='library'):
        active_settings = self.settings_loader() if settings is None else settings
        return RuleSet.normalize(active_settings, scope=scope)

    def build_pre_enrichment_filter(self, settings=None):
        ruleset = self.load_ruleset(settings=settings, scope='pre_enrichment')
        return lambda video: bool(ruleset.apply_residual([video]))

    def filter_library_rows(self, rows, settings=None):
        ruleset = self.load_ruleset(settings=settings, scope='library')
        return ruleset.apply_residual(rows)

    def filter_video_rows(self, rows, settings=None):
        return self.filter_library_rows(rows, settings=settings)
