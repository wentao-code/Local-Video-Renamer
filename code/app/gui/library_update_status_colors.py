from app.services.detail.update_status_service import (
    UPDATE_STATUS_ACTIVE,
    UPDATE_STATUS_INACTIVE,
    UPDATE_STATUS_SUSPECT,
)


UPDATE_STATUS_FOREGROUND_COLORS = {
    UPDATE_STATUS_ACTIVE: '#16a34a',
    UPDATE_STATUS_SUSPECT: '#ca8a04',
    UPDATE_STATUS_INACTIVE: '#6b7280',
}


def update_status_foreground(status):
    normalized_status = str(status or '').strip().lower()
    return UPDATE_STATUS_FOREGROUND_COLORS.get(
        normalized_status,
        UPDATE_STATUS_FOREGROUND_COLORS[UPDATE_STATUS_INACTIVE],
    )
