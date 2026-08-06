"""Compatibility export for the canonical authentication router.

The active API is implemented in ``app.api.v1.endpoints.auth``. Keeping this
module as a re-export prevents older imports from exposing stale or incomplete
authentication behavior.
"""

from app.api.v1.endpoints.auth import (  # noqa: F401
    LoginResponse,
    MFAChallengeResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    router,
)

__all__ = [
    "LoginResponse",
    "MFAChallengeResponse",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "RefreshRequest",
    "router",
]
