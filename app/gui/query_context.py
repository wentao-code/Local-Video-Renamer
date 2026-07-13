from dataclasses import dataclass, field, replace
from typing import Any, Mapping


class EntityType:
    VIDEO = 'video'
    ACTOR = 'actor'
    CODE_PREFIX = 'code_prefix'
    LADDER = 'ladder'
    MASTERPIECE = 'masterpiece'

    ALL = (VIDEO, ACTOR, CODE_PREFIX, LADDER, MASTERPIECE)


@dataclass(frozen=True)
class EntityReference:
    entity_type: str
    entity_key: str
    display_name: str = ''
    secondary_text: str = ''
    source: str = ''

    def __post_init__(self):
        entity_type = str(self.entity_type or '').strip()
        entity_key = str(self.entity_key or '').strip()
        if entity_type not in EntityType.ALL:
            raise ValueError(f'不支持的对象类型: {entity_type}')
        if not entity_key:
            raise ValueError('对象标识不能为空')
        object.__setattr__(self, 'entity_type', entity_type)
        object.__setattr__(self, 'entity_key', entity_key)
        object.__setattr__(self, 'display_name', str(self.display_name or '').strip())
        object.__setattr__(self, 'secondary_text', str(self.secondary_text or '').strip())
        object.__setattr__(self, 'source', str(self.source or '').strip())

    def as_dict(self):
        return {
            'entity_type': self.entity_type,
            'entity_key': self.entity_key,
            'display_name': self.display_name,
            'secondary_text': self.secondary_text,
            'source': self.source,
        }


@dataclass(frozen=True)
class QueryContext:
    search_text: str = ''
    filters: Mapping[str, Any] = field(default_factory=dict)
    sort_field: str = ''
    sort_order: str = 'asc'
    page: int = 1
    page_size: int = 100
    source: str = ''
    entity: EntityReference | None = None

    def __post_init__(self):
        object.__setattr__(self, 'search_text', str(self.search_text or '').strip())
        object.__setattr__(self, 'filters', dict(self.filters or {}))
        object.__setattr__(self, 'sort_field', str(self.sort_field or '').strip())
        sort_order = str(self.sort_order or 'asc').strip().lower()
        object.__setattr__(self, 'sort_order', sort_order if sort_order in ('asc', 'desc') else 'asc')
        object.__setattr__(self, 'page', max(1, int(self.page or 1)))
        object.__setattr__(self, 'page_size', max(1, min(1000, int(self.page_size or 100))))
        object.__setattr__(self, 'source', str(self.source or '').strip())

    @property
    def offset(self):
        return (self.page - 1) * self.page_size

    def copy_with(self, **changes):
        return replace(self, **changes)

    def as_dict(self):
        return {
            'search_text': self.search_text,
            'filters': dict(self.filters),
            'sort_field': self.sort_field,
            'sort_order': self.sort_order,
            'page': self.page,
            'page_size': self.page_size,
            'source': self.source,
            'entity': self.entity.as_dict() if self.entity else None,
        }


@dataclass(frozen=True)
class NavigationRequest:
    target: EntityReference | None = None
    context: QueryContext = field(default_factory=QueryContext)
    action: str = 'open'

    def __post_init__(self):
        action = str(self.action or 'open').strip().lower()
        if action not in ('open', 'list', 'compare'):
            raise ValueError(f'不支持的导航动作: {action}')
        object.__setattr__(self, 'action', action)

    @classmethod
    def open_entity(cls, target, context=None):
        return cls(target=target, context=context or QueryContext(), action='open')

    @classmethod
    def open_list(cls, entity_type, context=None):
        return cls(
            context=(context or QueryContext()).copy_with(
                entity=EntityReference(entity_type=entity_type, entity_key='list')
            ),
            action='list',
        )

    def as_dict(self):
        return {
            'target': self.target.as_dict() if self.target else None,
            'context': self.context.as_dict(),
            'action': self.action,
        }
