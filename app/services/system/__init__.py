"""System-level service entrypoints.

Use this package for environment/runtime guards that are broader than a single
feature workflow, such as network health checks.
"""

from app.services.system.network_guard_service import (
    DEFAULT_NETWORK_GUARD_REQUIRED_FAILURES,
    DEFAULT_NETWORK_GUARD_TIMEOUT_SECONDS,
    NetworkGuardService,
)


__all__ = [
    'DEFAULT_NETWORK_GUARD_REQUIRED_FAILURES',
    'DEFAULT_NETWORK_GUARD_TIMEOUT_SECONDS',
    'NetworkGuardService',
]
