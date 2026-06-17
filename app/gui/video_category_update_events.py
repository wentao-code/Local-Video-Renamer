from PyQt5.QtCore import QObject, pyqtSignal


class VideoCategoryUpdateEventBus(QObject):
    categories_updated = pyqtSignal()


video_category_update_event_bus = VideoCategoryUpdateEventBus()
