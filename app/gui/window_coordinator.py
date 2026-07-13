from app.gui.query_context import EntityReference, EntityType, QueryContext


class WindowCoordinator:
    """Routes typed navigation requests and reuses open desktop viewers."""

    def __init__(self, parent=None):
        self.parent = parent
        self._windows = {}
        self._factories = {}
        self._comparison_factory = None

    def set_factory(self, key, factory):
        self._factories[str(key)] = factory

    def set_comparison_factory(self, factory):
        self._comparison_factory = factory

    def register_window(self, key, window):
        normalized_key = self._normalize_key(key)
        self._windows[normalized_key] = window
        destroyed = getattr(window, 'destroyed', None)
        if destroyed is not None:
            destroyed.connect(lambda *_args, target=normalized_key: self.unregister_window(target))
        return window

    def unregister_window(self, key):
        self._windows.pop(self._normalize_key(key), None)

    def get_window(self, key):
        return self._windows.get(self._normalize_key(key))

    def open_entity(self, reference, context=None):
        if not isinstance(reference, EntityReference):
            raise TypeError('reference 必须是 EntityReference')
        context = context or QueryContext(entity=reference)
        key = self.window_key(reference)
        window = self.get_window(key)
        if window is None:
            factory = self._factories.get(reference.entity_type)
            if factory is None:
                raise KeyError(f'没有对象类型窗口工厂: {reference.entity_type}')
            window = factory(reference, context)
            if window is None:
                return None
            self.register_window(key, window)
        self._apply_context(window, context)
        self.activate(window)
        return window

    def open_list(self, entity_type, context=None):
        normalized_type = str(entity_type or '').strip()
        if normalized_type not in EntityType.ALL:
            raise ValueError(f'不支持的列表类型: {normalized_type}')
        key = ('list', normalized_type)
        window = self.get_window(key)
        if window is None:
            factory = self._factories.get(f'list:{normalized_type}')
            if factory is None:
                raise KeyError(f'没有列表窗口工厂: {normalized_type}')
            window = factory(context or QueryContext())
            self.register_window(key, window)
        if context is not None:
            self._apply_context(window, context)
        self.activate(window)
        return window

    def compare_entities(self, first, second):
        if self._comparison_factory is None:
            raise KeyError('没有配置对比窗口工厂')
        if not isinstance(first, EntityReference) or not isinstance(second, EntityReference):
            raise TypeError('对比对象必须是 EntityReference')
        if first.entity_type != second.entity_type:
            raise ValueError('对比对象类型必须一致')
        key = ('compare',)
        window = self.get_window(key)
        if window is None:
            window = self._comparison_factory(first, second)
            self.register_window(key, window)
        else:
            update_entities = getattr(window, 'set_entities', None)
            if callable(update_entities):
                update_entities(first, second)
        self.activate(window)
        return window

    def close_all(self):
        for window in list(self._windows.values()):
            close = getattr(window, 'close', None)
            if callable(close):
                close()
        self._windows.clear()

    @staticmethod
    def window_key(reference):
        return ('entity', reference.entity_type)

    @staticmethod
    def _normalize_key(key):
        if isinstance(key, tuple):
            return tuple(str(part or '').strip() for part in key)
        return str(key or '').strip()

    @staticmethod
    def _apply_context(window, context):
        apply_context = getattr(window, 'apply_query_context', None)
        if callable(apply_context):
            apply_context(context)

    @staticmethod
    def activate(window):
        show = getattr(window, 'show', None)
        if callable(show):
            show()
        raise_window = getattr(window, 'raise_', None)
        if callable(raise_window):
            raise_window()
        activate_window = getattr(window, 'activateWindow', None)
        if callable(activate_window):
            activate_window()
