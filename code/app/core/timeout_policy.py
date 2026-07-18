"""Runtime timeout validation shared by HTTP, sockets, and browsers."""

import math


# Keep below the platform timeval boundary while allowing long-running tasks.
MAX_SOCKET_TIMEOUT_SECONDS = 2_000_000.0
MAX_BROWSER_TIMEOUT_MILLISECONDS = 2_000_000_000


def validate_timeout_seconds(value, *, name='timeout', minimum=0.001, maximum=MAX_SOCKET_TIMEOUT_SECONDS):
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be a finite number of seconds') from exc
    if not math.isfinite(normalized) or normalized < float(minimum) or normalized > float(maximum):
        raise ValueError(
            f'{name} must be between {minimum} and {maximum} seconds'
        )
    return normalized


def normalize_http_timeout_seconds(value, *, name='HTTP timeout'):
    """Normalize seconds and repair legacy callers that passed milliseconds."""
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be a finite number of seconds') from exc
    if (
        math.isfinite(normalized)
        and normalized > MAX_SOCKET_TIMEOUT_SECONDS
        and normalized <= MAX_BROWSER_TIMEOUT_MILLISECONDS
    ):
        normalized /= 1000.0
    return validate_timeout_seconds(normalized, name=name)


def validate_timeout_milliseconds(
    value,
    *,
    name='timeout',
    minimum=1,
    maximum=MAX_BROWSER_TIMEOUT_MILLISECONDS,
):
    try:
        normalized = int(round(float(value)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be a finite number of milliseconds') from exc
    if normalized < int(minimum) or normalized > int(maximum):
        raise ValueError(
            f'{name} must be between {minimum} and {maximum} milliseconds'
        )
    return normalized
