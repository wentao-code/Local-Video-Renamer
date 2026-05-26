from app.services.combo_progress_service import ComboSubtaskProgressTracker


def start_progress_tracker(
    tracker,
    target_label,
    total_count,
    *,
    source_label='',
    message='',
    count_unit='项',
    target_type='',
    source_key='',
    log_path='',
    task_kind='single',
):
    if tracker is None:
        return
    if isinstance(tracker, ComboSubtaskProgressTracker):
        tracker.start(
            target_label,
            total_count,
            source_label=source_label,
            message=message,
            count_unit=count_unit,
        )
        return
    tracker.start(
        target_label,
        total_count,
        source_label=source_label,
        message=message,
        count_unit=count_unit,
        target_type=target_type,
        source_key=source_key,
        log_path=log_path,
        task_kind=task_kind,
    )
