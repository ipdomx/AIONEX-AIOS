"""Firebase phone authentication bridge for AIOS free registration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import HTTPException, status

_FIREBASE_APP_LOCK = Lock()
_FIREBASE_APP: Any | None = None


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _credentials_source() -> tuple[str, dict[str, Any] | str]:
    inline = os.getenv("FIREBASE_ADMIN_CREDENTIALS_JSON", "").strip()
    if inline.startswith("{"):
        try:
            payload = json.loads(inline)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin credentials JSON is invalid",
            ) from exc
        return "json", payload

    path_value = inline or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path_value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials are not configured",
        )
    path = Path(path_value)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials file is unavailable",
        )
    return "file", str(path)


def _firebase_app() -> Any:
    global _FIREBASE_APP
    if _FIREBASE_APP is not None:
        return _FIREBASE_APP

    with _FIREBASE_APP_LOCK:
        if _FIREBASE_APP is not None:
            return _FIREBASE_APP
        try:
            import firebase_admin
            from firebase_admin import credentials
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin SDK is not installed",
            ) from exc

        source_type, source = _credentials_source()
        credential = (
            credentials.Certificate(source)
            if source_type == "file"
            else credentials.Certificate(source)
        )
        project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip() or None
        options = {"projectId": project_id} if project_id else None
        try:
            _FIREBASE_APP = firebase_admin.initialize_app(credential, options=options)
        except ValueError:
            _FIREBASE_APP = firebase_admin.get_app()
        return _FIREBASE_APP


def verify_firebase_phone_token(id_token: str, expected_phone: str) -> dict[str, Any]:
    """Verify a recent Firebase ID token produced by the phone provider."""

    if not id_token or len(id_token) < 100:
        raise HTTPException(status_code=422, detail="Invalid Firebase ID token")
    try:
        from firebase_admin import auth

        claims = auth.verify_id_token(
            id_token,
            app=_firebase_app(),
            check_revoked=True,
            clock_skew_seconds=30,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Firebase phone verification failed",
        ) from exc

    phone = str(claims.get("phone_number") or "").strip()
    provider = (
        claims.get("firebase", {}).get("sign_in_provider")
        if isinstance(claims.get("firebase"), dict)
        else None
    )
    auth_time = claims.get("auth_time")
    now = datetime.now(UTC)
    try:
        authenticated_at = datetime.fromtimestamp(int(auth_time), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Firebase token has no valid auth time") from exc

    max_age_seconds = int(os.getenv("FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS", "600"))
    if (
        phone != expected_phone
        or provider != "phone"
        or authenticated_at > now + timedelta(seconds=30)
        or now - authenticated_at > timedelta(seconds=max_age_seconds)
    ):
        raise HTTPException(
            status_code=422,
            detail="A recent Firebase verification for this phone number is required",
        )
    return claims


def issue_aios_phone_assertion(claims: dict[str, Any], phone_number: str) -> str:
    """Convert verified Firebase claims into the existing signed AIOS assertion."""

    secret = os.getenv("AIOS_PHONE_VERIFICATION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AIOS phone verification secret is not configured",
        )
    payload = {
        "phone_number": phone_number,
        "verified": True,
        "line_type": "mobile",
        "provider": "firebase",
        "firebase_uid": str(claims.get("uid") or claims.get("sub") or ""),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64url(signature)}"
