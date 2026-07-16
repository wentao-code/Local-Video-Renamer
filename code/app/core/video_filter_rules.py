import json
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.javtxt_video_state import COLLECTION_TITLE_KEYWORDS
from app.core.video_code import standardize_video_code
from app.services.video import COLLECTION_TAG_KEYWORDS


FILTER_FIELD_CODE = 'code'
FILTER_FIELD_TITLE = 'title'
FILTER_FIELD_JAVTXT_TAGS = 'javtxt_tags'
FILTER_FIELD_CO_STAR_CODE = 'co_star_code'

FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
    FILTER_FIELD_JAVTXT_TAGS,
    FILTER_FIELD_CO_STAR_CODE,
)

PRE_ENRICHMENT_FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
)

LIBRARY_HIDDEN_FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
    FILTER_FIELD_JAVTXT_TAGS,
)

EXACT_PREFIX_FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_CO_STAR_CODE,
)

VR_FILTER_KEYWORD = 'VR'
DEFAULT_TITLE_FILTER_KEYWORDS = (
    VR_FILTER_KEYWORD,
    *COLLECTION_TITLE_KEYWORDS,
    *COLLECTION_TAG_KEYWORDS,
)
DEFAULT_JAVTXT_TAG_FILTER_KEYWORDS = (
    VR_FILTER_KEYWORD,
    *COLLECTION_TITLE_KEYWORDS,
    *COLLECTION_TAG_KEYWORDS,
)
VR_MARKER_RE = re.compile(r'(?<![A-Z0-9])V\s*R(?![A-Z0-9])', re.IGNORECASE)

DEFAULT_VIDEO_FILTER_SETTINGS = {
    'rules': {
        FILTER_FIELD_CODE: [],
        FILTER_FIELD_TITLE: list(DEFAULT_TITLE_FILTER_KEYWORDS),
        FILTER_FIELD_JAVTXT_TAGS: list(DEFAULT_JAVTXT_TAG_FILTER_KEYWORDS),
        FILTER_FIELD_CO_STAR_CODE: [],
    }
}


@dataclass(frozen=True)
class RuleSet:
    """Normalized filter rules shared by SQL queries and residual filtering."""

    rules: object
    scope: str = 'library'

    @classmethod
    def normalize(cls, settings=None, scope='library'):
        if isinstance(settings, cls):
            if str(scope or '').strip() in ('', settings.scope):
                return settings
            settings = settings.to_settings()
        normalized = normalize_video_filter_settings(settings)
        normalized_rules = {
            field_name: tuple(
                str(value or '').strip().lower()
                for value in normalized['rules'].get(field_name, [])
            )
            for field_name in FILTER_FIELDS
        }
        normalized_scope = str(scope or 'library').strip().lower() or 'library'
        if normalized_scope not in {'library', 'pre_enrichment'}:
            raise ValueError(f'Unknown RuleSet scope: {scope}')
        return cls(MappingProxyType(normalized_rules), normalized_scope)

    def to_settings(self):
        return {
            'rules': {
                field_name: list(self.rules.get(field_name, ()))
                for field_name in FILTER_FIELDS
            }
        }

    def fingerprint(self):
        return json.dumps(
            {
                'scope': self.scope,
                'rules': {
                    field_name: list(self.rules.get(field_name, ()))
                    for field_name in FILTER_FIELDS
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        )

    def compile_sql(
        self,
        table_alias='',
        scope=None,
        visibility='visible',
        post_enriched_only=True,
    ):
        """Return a SQL visibility predicate and parameters.

        SQL only handles safe, literal substring and separated-code-prefix rules.
        Rules such as VR's spaced marker remain in ``apply_residual``.
        """
        active_scope = str(scope or self.scope).strip().lower() or self.scope
        if active_scope not in {'library', 'pre_enrichment'}:
            raise ValueError(f'Unknown RuleSet scope: {active_scope}')
        active_visibility = str(visibility or 'visible').strip().lower() or 'visible'
        if active_visibility not in {'visible', 'filtered'}:
            raise ValueError(f'Unknown RuleSet visibility: {active_visibility}')
        hidden_terms = []
        parameters = []

        code_column = self._column('code', table_alias)
        code_prefixes = []
        for keyword in self.rules.get(FILTER_FIELD_CODE, ()):
            prefix = _normalize_code_prefix(keyword)
            if prefix and re.fullmatch(r'[A-Z0-9]+', prefix):
                code_prefixes.append(prefix)
        if code_prefixes:
            placeholders = ','.join('?' for _ in code_prefixes)
            hidden_terms.append(
                f'{self._sql_separated_code_prefix(code_column)} IN ({placeholders})'
            )
            parameters.extend(code_prefixes)

        if active_scope == 'pre_enrichment':
            text_fields = (FILTER_FIELD_TITLE,)
        else:
            text_fields = (FILTER_FIELD_TITLE, FILTER_FIELD_JAVTXT_TAGS)
        for field_name in text_fields:
            column = self._column(field_name, table_alias)
            for keyword in self.rules.get(field_name, ()):
                if str(keyword or '').strip().upper() == VR_FILTER_KEYWORD:
                    continue
                hidden_terms.append(
                    f"LOWER(COALESCE({column}, '')) LIKE LOWER(?) ESCAPE '\\'"
                )
                parameters.append(self._escape_like_pattern(keyword))

        if not hidden_terms:
            if active_visibility == 'filtered' and active_scope == 'library':
                return self._post_enriched_sql(table_alias), [UNENRICHED_STATUS]
            return '1 = 1', []

        hidden_sql = ' OR '.join(f'({term})' for term in hidden_terms)
        if active_scope == 'pre_enrichment':
            return f'NOT ({hidden_sql})', parameters

        if not post_enriched_only:
            return f'NOT ({hidden_sql})', parameters

        post_enriched_sql = self._post_enriched_sql(table_alias)
        if active_visibility == 'filtered':
            if self._has_residual_rules(active_scope):
                return post_enriched_sql, [UNENRICHED_STATUS]
            return f'({post_enriched_sql} AND ({hidden_sql}))', [UNENRICHED_STATUS, *parameters]
        return f'(NOT ({post_enriched_sql}) OR NOT ({hidden_sql}))', [UNENRICHED_STATUS, *parameters]

    def apply_residual(self, rows, scope=None, visibility='visible'):
        active_scope = str(scope or self.scope).strip().lower() or self.scope
        active_visibility = str(visibility or 'visible').strip().lower() or 'visible'
        if active_visibility not in {'visible', 'filtered'}:
            raise ValueError(f'Unknown RuleSet visibility: {active_visibility}')
        settings = self.to_settings()
        if active_scope == 'pre_enrichment':
            predicate = lambda row: not should_skip_video_before_enrichment(row, settings)
        elif active_scope == 'library':
            predicate = lambda row: not should_hide_video_from_library(row, settings)
        else:
            raise ValueError(f'Unknown RuleSet scope: {active_scope}')
        return [
            dict(row or {})
            for row in (rows or [])
            if predicate(row) == (active_visibility == 'visible')
        ]

    @staticmethod
    def _column(column_name, table_alias=''):
        alias = str(table_alias or '').strip()
        return f'{alias}.{column_name}' if alias else column_name

    @staticmethod
    def _sql_separated_code_prefix(column):
        separated = f"REPLACE(REPLACE(TRIM({column}), '_', '-'), ' ', '-')"
        return (
            "UPPER(CASE WHEN instr({value}, '-') > 0 "
            "THEN substr({value}, 1, instr({value}, '-') - 1) "
            "ELSE '' END)"
        ).format(value=separated)

    @classmethod
    def _post_enriched_sql(cls, table_alias=''):
        fields = (
            'javtxt_movie_id',
            'javtxt_url',
            'javtxt_tags',
        )
        value_terms = [
            f"COALESCE({cls._column(field_name, table_alias)}, '') <> ''"
            for field_name in fields
        ]
        status_column = cls._column('javtxt_enrichment_status', table_alias)
        value_terms.append(
            f"(COALESCE({status_column}, '') <> '' AND COALESCE({status_column}, '') <> ?)"
        )
        return '(' + ' OR '.join(value_terms) + ')'

    def _has_residual_rules(self, scope):
        if scope == 'pre_enrichment':
            return False
        if any(
            str(keyword or '').strip().upper() == VR_FILTER_KEYWORD
            for field_name in (FILTER_FIELD_TITLE, FILTER_FIELD_JAVTXT_TAGS)
            for keyword in self.rules.get(field_name, ())
        ):
            return True
        return bool(self.rules.get(FILTER_FIELD_CODE, ()))

    @staticmethod
    def _escape_like_pattern(value):
        return '%' + str(value or '').replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def normalize_video_filter_settings(settings):
    payload = dict(settings or {}) if isinstance(settings, dict) else {}
    raw_rules = payload.get('rules', payload)
    if not isinstance(raw_rules, dict):
        raw_rules = {}

    return {
        'rules': {
            field: _normalize_keyword_list(raw_rules.get(field, []))
            for field in FILTER_FIELDS
        }
    }


def get_filter_keywords(settings, field_name):
    normalized = normalize_video_filter_settings(settings)
    return list(normalized.get('rules', {}).get(field_name, []))


def matches_filter_keywords(value, keywords, field_name=''):
    raw_value = str(value or '').strip()
    if not raw_value:
        return False
    normalized_value = raw_value.lower()
    normalized_field_name = str(field_name or '').strip().lower()
    return any(
        _matches_single_keyword(raw_value, normalized_value, keyword, normalized_field_name)
        for keyword in _normalize_keyword_values(keywords)
    )


def should_skip_video_before_enrichment(video, settings):
    rules = _get_normalized_rules(settings)
    return any(
        matches_filter_keywords((video or {}).get(field_name, ''), rules.get(field_name, []), field_name=field_name)
        for field_name in PRE_ENRICHMENT_FILTER_FIELDS
    )


def should_hide_video_from_library(video, settings):
    if not is_post_enrichment_video(video):
        return False
    rules = _get_normalized_rules(settings)
    return any(
        matches_filter_keywords((video or {}).get(field_name, ''), rules.get(field_name, []), field_name=field_name)
        for field_name in LIBRARY_HIDDEN_FILTER_FIELDS
    )


def _normalize_keyword_list(values):
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, (list, tuple)):
        values = []

    normalized = []
    seen = set()
    for value in values:
        keyword = str(value or '').strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
    return normalized


@lru_cache(maxsize=256)
def _normalize_keyword_tuple(values):
    return tuple(_normalize_keyword_list(list(values or ())))


def _normalize_keyword_values(values):
    if isinstance(values, str):
        values = (values,)
    elif isinstance(values, (list, tuple)):
        values = tuple(values)
    else:
        values = ()
    return _normalize_keyword_tuple(values)


def _get_normalized_rules(settings):
    if isinstance(settings, dict):
        rules = settings.get('rules', settings)
        if (
            isinstance(rules, dict)
            and all(field_name in rules for field_name in FILTER_FIELDS)
            and all(isinstance(rules.get(field_name, []), list) for field_name in FILTER_FIELDS)
        ):
            return rules
    return normalize_video_filter_settings(settings).get('rules', {})


def _matches_single_keyword(raw_value, normalized_value, keyword, field_name=''):
    normalized_keyword = str(keyword or '').strip().lower()
    if not normalized_keyword:
        return False
    if field_name in EXACT_PREFIX_FILTER_FIELDS:
        return _matches_exact_code_prefix(raw_value, normalized_keyword)
    if normalized_keyword == VR_FILTER_KEYWORD.lower():
        normalized_text = raw_value.replace('Ｖ', 'V').replace('Ｒ', 'R')
        return bool(VR_MARKER_RE.search(normalized_text))
    return normalized_keyword in normalized_value


def _matches_exact_code_prefix(raw_value, normalized_keyword):
    value_prefix = _normalize_code_prefix(raw_value)
    keyword_prefix = _normalize_code_prefix(normalized_keyword)
    if not value_prefix or not keyword_prefix:
        return False
    return value_prefix == keyword_prefix


def _normalize_code_prefix(value):
    standardized = standardize_video_code(value)
    if not standardized:
        return ''
    match = re.match(r'^([A-Z0-9]+?)(?:[-_\s]*\d.*)?$', standardized, re.IGNORECASE)
    if not match:
        return ''
    prefix = re.sub(r'[^A-Z0-9]', '', match.group(1).upper())
    return prefix if any(char.isalpha() for char in prefix) else ''


def is_post_enrichment_video(video):
    row = dict(video or {})
    if str(row.get('manual_tier', '') or '').strip():
        return True
    if any(
        str(row.get(field_name, '') or '').strip()
        for field_name in ('javtxt_movie_id', 'javtxt_url', 'javtxt_title', 'javtxt_actors', 'javtxt_tags')
    ):
        return True
    status = str(row.get('javtxt_enrichment_status', '') or '').strip()
    return bool(status) and status != UNENRICHED_STATUS
