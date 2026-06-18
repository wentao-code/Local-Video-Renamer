"""Authentication-related service entrypoints.

Use this package for user-facing login helpers and browser-backed auth checks.
"""

from app.services.auth.auto_login_service import AutoLoginService


__all__ = ['AutoLoginService']
