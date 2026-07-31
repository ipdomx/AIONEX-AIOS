"""Firebase Admin based phone-token verification for free-user onboarding."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import HTTPException, status

try:
    import firebase_admin
    from firebase_admin import auth, credentials
except ImportError:  # pragma: no cover - deployment dependency guard
    firebase_admin = None
    auth = None
    credentials = None

_APP_LOCK = Lock()


def _firebase_app():
    if firebase_admin is None or auth is None or credentials is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin SDK is not installed",
        )

    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    credential_path = os.getenv("FIREBASE_ADMIN_CREDENTIALS_JSON", "").strip()
    if not project_id or not credential_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase phone verification is not configured",
        )
    if not os.path.isfile(credential_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials file is unavailable",
        )

    with _APP_LOCK:
        try:
            return firebase_admin.get_app()
        except ValueError:
            return firebase_admin.initialize_app(
                credentials.Certificate(credential_path),
                {"projectId": project_id},
            )


def verify_firebase_phone_token(token: str, phone_number: str) -> dict[str, Any]:
    """Verify a Firebase ID token and bind it to the submitted E.164 number."""

    try:
        decoded = auth.verify_id_token(
            token,
            app=_firebase_app(),
            check_revoked=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or expired Firebase phone verification token",
        ) from exc

    verified_phone = str(decoded.get("phone_number") or "").strip()
    firebase_claims = decoded.get("firebase") or {}
    sign_in_provider = str(firebase_claims.get("sign_in_provider") or "").strip()
    if verified_phone != phone_number or sign_in_provider != "phone":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Firebase token does not verify the submitted phone number",
        )

    verified_at = datetime.now(UTC)
    auth_time = decoded.get("auth_time")
    if isinstance(auth_time, (int, float)):
        verified_at = datetime.fromtimestamp(auth_time, tz=UTC)

    return {
        "verified": True,
        "provider": "firebase",
        "line_type": "mobile",
        "phone_number": verified_phone,
        "verified_at": verified_at.isoformat(),
        "firebase_uid": str(decoded.get("uid") or decoded.get("sub") or ""),
    }
