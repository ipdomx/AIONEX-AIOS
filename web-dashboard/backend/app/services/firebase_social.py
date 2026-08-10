"""Verified Firebase social sign-in for AIOS accounts.

Firebase completes each provider's OAuth/OIDC flow in the browser. AIOS then
verifies the short-lived Firebase ID token with the Admin SDK and exchanges it
for the same first-party access and refresh tokens used by password login.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.db.redis import get_redis
from app.services.firebase_phone import (
    _verify_id_token_sync,
    firebase_public_configuration,
)
from fastapi import HTTPException, status
from firebase_admin import auth as firebase_auth  # type: ignore[import-untyped]
from firebase_admin.exceptions import FirebaseError  # type: ignore[import-untyped]

SOCIAL_PROVIDER_LABELS: dict[str, str] = {
    "google": "Google",
    "apple": "Apple",
    "facebook": "Facebook",
    "x": "X",
    "instagram": "Instagram",
}
SOCIAL_REGISTRATION_PREFIX = "aionex:auth:social-registration:"


def _provider_definition(provider_id: str) -> dict[str, str]:
    return {
        "label": SOCIAL_PROVIDER_LABELS[provider_id],
        "firebase_provider": settings.FIREBASE_SOCIAL_PROVIDER_IDS[provider_id],
    }


def enabled_social_providers() -> list[dict[str, str]]:
    configured = {
        str(provider).strip().lower()
        for provider in settings.FIREBASE_SOCIAL_PROVIDERS
        if str(provider).strip()
    }
    return [
        {"id": provider_id, **_provider_definition(provider_id)}
        for provider_id in SOCIAL_PROVIDER_LABELS
        if provider_id in configured
    ]


def firebase_social_public_configuration() -> dict[str, Any]:
    firebase = firebase_public_configuration()
    providers = enabled_social_providers()
    enabled = bool(firebase["enabled"] and providers)
    return {
        "provider": "firebase",
        "enabled": enabled,
        "web_config": firebase["web_config"] if enabled else None,
        "providers": [
            {
                "id": item["id"],
                "label": item["label"],
                "firebase_provider": item["firebase_provider"],
                "enabled": enabled,
            }
            for item in providers
        ],
    }


def _social_provider(sign_in_provider: str) -> tuple[str, dict[str, str]]:
    for provider_id in SOCIAL_PROVIDER_LABELS:
        definition = _provider_definition(provider_id)
        if definition["firebase_provider"] == sign_in_provider:
            enabled = {item["id"] for item in enabled_social_providers()}
            if provider_id not in enabled:
                break
            return provider_id, definition
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "SOCIAL_PROVIDER_NOT_ALLOWED",
            "message": "This social sign-in provider is not enabled.",
        },
    )


async def verify_firebase_social_id_token(id_token: str) -> dict[str, Any]:
    """Verify a recent Firebase OAuth/OIDC token and normalize its identity."""

    if not id_token or len(id_token) < 100 or len(id_token) > 8192:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_TOKEN_INVALID",
                "message": "The social sign-in token is invalid.",
            },
        )
    try:
        claims = await asyncio.to_thread(_verify_id_token_sync, id_token)
    except HTTPException:
        raise
    except (
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.InvalidIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_TOKEN_INVALID",
                "message": "The social sign-in token is invalid or expired.",
            },
        ) from exc
    except FirebaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOCIAL_AUTH_UNAVAILABLE",
                "message": "Social sign-in is temporarily unavailable.",
            },
        ) from exc

    firebase_claim = claims.get("firebase")
    sign_in_provider = (
        str(firebase_claim.get("sign_in_provider") or "")
        if isinstance(firebase_claim, dict)
        else ""
    )
    provider_id, definition = _social_provider(sign_in_provider)

    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not uid or len(uid) > 128 or not email or len(email) > 320:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_EMAIL_REQUIRED",
                "message": "The provider did not return a usable email address.",
            },
        )
    if claims.get("email_verified") is not True:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_EMAIL_UNVERIFIED",
                "message": "The provider email address must be verified.",
            },
        )

    try:
        auth_time = int(claims["auth_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_TOKEN_INVALID",
                "message": "The social sign-in token is missing authentication time.",
            },
        ) from exc
    now_seconds = int(datetime.now(UTC).timestamp())
    if (
        auth_time > now_seconds + 60
        or now_seconds - auth_time > settings.FIREBASE_SOCIAL_TOKEN_MAX_AGE_SECONDS
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_REAUTHENTICATION_REQUIRED",
                "message": "Please complete social sign-in again.",
            },
        )

    subject = uid
    if isinstance(firebase_claim, dict):
        identities = firebase_claim.get("identities")
        provider_subjects = (
            identities.get(definition["firebase_provider"])
            if isinstance(identities, dict)
            else None
        )
        if isinstance(provider_subjects, list) and provider_subjects:
            candidate = str(provider_subjects[0] or "").strip()
            if candidate:
                subject = candidate
    if len(subject) > 255:
        raise HTTPException(status_code=422, detail="Provider identity is invalid")

    return {
        "provider": provider_id,
        "firebase_provider": definition["firebase_provider"],
        "subject": subject,
        "firebase_uid": uid,
        "email": email,
        "name": str(claims.get("name") or "").strip()[:200] or None,
        "picture": str(claims.get("picture") or "").strip()[:2048] or None,
        "authenticated_at": datetime.fromtimestamp(auth_time, tz=UTC),
    }


async def create_social_registration(identity: dict[str, Any]) -> dict[str, Any]:
    """Persist a short-lived, one-use registration assertion without ID tokens."""

    registration_token = secrets.token_urlsafe(32)
    payload = {
        "provider": str(identity["provider"]),
        "subject": str(identity["subject"]),
        "firebase_uid": str(identity["firebase_uid"]),
        "email": str(identity["email"]),
        "name": identity.get("name"),
        "picture": identity.get("picture"),
    }
    try:
        redis = await get_redis()
        stored = await redis.set(
            f"{SOCIAL_REGISTRATION_PREFIX}{registration_token}",
            json.dumps(payload, separators=(",", ":")),
            ex=settings.FIREBASE_SOCIAL_REGISTRATION_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOCIAL_REGISTRATION_UNAVAILABLE",
                "message": "Social registration is temporarily unavailable.",
            },
            headers={"Retry-After": "5"},
        ) from exc
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOCIAL_REGISTRATION_UNAVAILABLE",
                "message": "Could not start social registration.",
            },
        )
    return {
        "registration_token": registration_token,
        "provider": payload["provider"],
        "email": payload["email"],
        "name": payload["name"],
        "expires_in": settings.FIREBASE_SOCIAL_REGISTRATION_TTL_SECONDS,
    }


async def consume_social_registration(registration_token: str) -> dict[str, Any]:
    """Consume a social registration assertion exactly once."""

    if (
        not registration_token
        or len(registration_token) < 20
        or len(registration_token) > 256
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SOCIAL_REGISTRATION_INVALID",
                "message": "The social registration request is invalid.",
            },
        )
    try:
        redis = await get_redis()
        raw = await redis.getdel(f"{SOCIAL_REGISTRATION_PREFIX}{registration_token}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOCIAL_REGISTRATION_UNAVAILABLE",
                "message": "Social registration is temporarily unavailable.",
            },
            headers={"Retry-After": "5"},
        ) from exc
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "SOCIAL_REGISTRATION_EXPIRED",
                "message": "Social registration expired; authenticate again.",
            },
        )
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "SOCIAL_REGISTRATION_EXPIRED",
                "message": "Social registration is no longer valid.",
            },
        ) from exc
    required = {"provider", "subject", "firebase_uid", "email"}
    if not isinstance(payload, dict) or any(not payload.get(key) for key in required):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "SOCIAL_REGISTRATION_EXPIRED",
                "message": "Social registration is no longer valid.",
            },
        )
    return payload
