"""Firebase phone-auth verification for AIOS free-user registration.

The browser completes Firebase's SMS and reCAPTCHA flow, then sends the
resulting Firebase ID token to AIOS.  The backend verifies the token with the
Firebase Admin SDK, requires the Firebase phone sign-in provider, binds the
token to the exact E.164 number submitted with registration, and accepts only
numbering-plan ranges classified as mobile.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import firebase_admin
import phonenumbers
from app.core.config import settings
from fastapi import HTTPException, status
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin.exceptions import FirebaseError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

_FIREBASE_APP_NAME = "aionex-phone-auth"
_FIREBASE_APP_LOCK = threading.Lock()
_FIREBASE_APP: firebase_admin.App | None = None
_FIREBASE_APP_SIGNATURE: tuple[str, str, str] | None = None
_IDENTITY_CONFIG_LOCK = threading.Lock()
_IDENTITY_CONFIG_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)
_IDENTITY_CONFIG_TTL_SECONDS = 300


def _configured_text(name: str) -> str:
    environment_value = os.getenv(name)
    if environment_value is not None:
        return environment_value.strip()
    value = getattr(settings, name, "")
    return str(value or "").strip()


def _configured_int(name: str, default: int) -> int:
    raw = _configured_text(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_service_account() -> tuple[Path, dict[str, Any], str]:
    project_id = _configured_text("FIREBASE_PROJECT_ID")
    credentials_path = _configured_text("FIREBASE_ADMIN_CREDENTIALS_JSON")
    if not project_id or not credentials_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase phone verification is not configured",
        )

    path = Path(credentials_path).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials are unavailable",
        )

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials are invalid",
        ) from exc

    if not isinstance(document, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials are invalid",
        )

    required = ("type", "project_id", "client_email", "private_key")
    if any(not str(document.get(key) or "").strip() for key in required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials are incomplete",
        )
    if (
        document.get("type") != "service_account"
        or document.get("project_id") != project_id
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Admin credentials do not match this project",
        )
    return path, document, project_id


def _identity_platform_config() -> dict[str, Any] | None:
    """Retrieve and briefly cache non-secret Firebase Auth project settings."""

    global _IDENTITY_CONFIG_CACHE
    now = time.monotonic()
    expires_at, cached = _IDENTITY_CONFIG_CACHE
    if now < expires_at:
        return cached

    with _IDENTITY_CONFIG_LOCK:
        expires_at, cached = _IDENTITY_CONFIG_CACHE
        if now < expires_at:
            return cached
        payload: dict[str, Any] | None = None
        try:
            _, document, project_id = _load_service_account()
            scoped_credentials = service_account.Credentials.from_service_account_info(
                document,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            with AuthorizedSession(scoped_credentials) as session:
                response = session.get(
                    "https://identitytoolkit.googleapis.com/admin/v2/"
                    f"projects/{project_id}/config",
                    timeout=8,
                )
                if response.status_code == 200:
                    candidate = response.json()
                    if isinstance(candidate, dict):
                        payload = candidate
        except Exception:
            payload = None
        ttl = _IDENTITY_CONFIG_TTL_SECONDS if payload is not None else 60
        _IDENTITY_CONFIG_CACHE = (now + ttl, payload)
        return payload


def _admin_verification_ready() -> bool:
    try:
        _get_firebase_app()
    except HTTPException:
        return False
    return True


def firebase_public_configuration() -> dict[str, Any]:
    """Return browser-safe Firebase settings without any Admin credentials."""

    configured = {
        "apiKey": _configured_text("FIREBASE_WEB_API_KEY"),
        "authDomain": _configured_text("FIREBASE_AUTH_DOMAIN"),
        "projectId": _configured_text("FIREBASE_PROJECT_ID"),
        "storageBucket": _configured_text("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": _configured_text("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": _configured_text("FIREBASE_APP_ID"),
        "measurementId": _configured_text("FIREBASE_MEASUREMENT_ID"),
    }
    required = ("apiKey", "authDomain", "projectId", "appId")
    web_ready = all(configured[key] for key in required)
    admin_ready = _admin_verification_ready()
    browser_config = {key: value for key, value in configured.items() if value}
    return {
        "provider": "firebase",
        "enabled": web_ready and admin_ready,
        "web_config": browser_config if web_ready else None,
        "admin_verification_ready": admin_ready,
    }


def _get_firebase_app() -> firebase_admin.App:
    global _FIREBASE_APP, _FIREBASE_APP_SIGNATURE

    path, document, project_id = _load_service_account()
    signature = (
        str(path.resolve()),
        project_id,
        str(document.get("private_key_id") or ""),
    )
    with _FIREBASE_APP_LOCK:
        if _FIREBASE_APP is not None and _FIREBASE_APP_SIGNATURE == signature:
            return _FIREBASE_APP

        if _FIREBASE_APP is not None:
            try:
                firebase_admin.delete_app(_FIREBASE_APP)
            except ValueError:
                pass
            _FIREBASE_APP = None
            _FIREBASE_APP_SIGNATURE = None

        try:
            existing = firebase_admin.get_app(_FIREBASE_APP_NAME)
        except ValueError:
            existing = None
        if existing is not None:
            firebase_admin.delete_app(existing)

        try:
            _FIREBASE_APP = firebase_admin.initialize_app(
                credentials.Certificate(document),
                {"projectId": project_id},
                name=_FIREBASE_APP_NAME,
            )
        except (OSError, ValueError, FirebaseError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin initialization failed",
            ) from exc
        _FIREBASE_APP_SIGNATURE = signature
        return _FIREBASE_APP


def _verify_id_token_sync(id_token: str) -> dict[str, Any]:
    app = _get_firebase_app()
    return firebase_auth.verify_id_token(
        id_token,
        app=app,
        check_revoked=True,
        clock_skew_seconds=30,
    )


def _canonical_mobile_number(phone_number: str) -> str:
    """Validate and canonicalize a numbering-plan range classified as mobile."""

    try:
        parsed = phonenumbers.parse(phone_number, None)
    except NumberParseException as exc:
        raise HTTPException(
            status_code=422,
            detail="A valid international mobile number is required",
        ) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise HTTPException(
            status_code=422,
            detail="A valid international mobile number is required",
        )
    if phonenumbers.number_type(parsed) != PhoneNumberType.MOBILE:
        raise HTTPException(
            status_code=422,
            detail="A verified supported mobile number is required",
        )
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def mobile_number_country_code(phone_number: str) -> str:
    """Return the authoritative ISO-3166 alpha-2 region for an E.164 number."""

    try:
        parsed = phonenumbers.parse(phone_number, None)
    except NumberParseException as exc:
        raise HTTPException(
            status_code=422,
            detail="A valid international mobile number is required",
        ) from exc
    region = str(phonenumbers.region_code_for_number(parsed) or "").upper()
    if len(region) != 2 or not region.isalpha():
        raise HTTPException(
            status_code=422,
            detail="The mobile-number country could not be determined",
        )
    return region


def canonical_mobile_number_details(phone_number: str) -> tuple[str, str]:
    canonical = _canonical_mobile_number(phone_number)
    return canonical, mobile_number_country_code(canonical)


def _sms_region_allowed(config: dict[str, Any], country_code: str) -> bool | None:
    sms_config = config.get("smsRegionConfig")
    if not isinstance(sms_config, dict):
        return None
    allowlist = sms_config.get("allowlistOnly")
    if isinstance(allowlist, dict):
        allowed = {
            str(value).upper() for value in allowlist.get("allowedRegions", []) if value
        }
        return country_code in allowed
    allow_by_default = sms_config.get("allowByDefault")
    if isinstance(allow_by_default, dict):
        denied = {
            str(value).upper()
            for value in allow_by_default.get("disallowedRegions", [])
            if value
        }
        return country_code not in denied
    return None


def firebase_phone_readiness(
    phone_number: str, origin: str | None = None
) -> dict[str, Any]:
    """Report known Firebase Phone, region-policy, and origin blockers safely."""

    canonical_phone, country_code = canonical_mobile_number_details(phone_number)
    local = firebase_public_configuration()
    project_id = _configured_text("FIREBASE_PROJECT_ID")
    config = _identity_platform_config()
    provider_enabled: bool | None = None
    sms_region_allowed: bool | None = None
    origin_authorized: bool | None = None
    reasons: list[str] = []

    if not local["enabled"]:
        reasons.append("The mobile verification service is not fully configured.")
    if config is not None:
        sign_in = config.get("signIn")
        phone_config = sign_in.get("phoneNumber") if isinstance(sign_in, dict) else None
        provider_enabled = (
            bool(phone_config.get("enabled"))
            if isinstance(phone_config, dict)
            else False
        )
        sms_region_allowed = _sms_region_allowed(config, country_code)
        parsed_origin = urlparse(origin or "")
        origin_host = str(parsed_origin.hostname or "").lower()
        if origin_host:
            authorized = {
                str(value).lower()
                for value in config.get("authorizedDomains", [])
                if value
            }
            origin_authorized = origin_host in authorized

        if provider_enabled is False:
            reasons.append(
                "Phone sign-in is disabled for the mobile verification project."
            )
        if sms_region_allowed is False:
            reasons.append(f"The SMS region policy does not allow {country_code}.")
        if origin_authorized is False:
            reasons.append(
                f"The site host {origin_host} is not an authorized authentication domain."
            )

    ready = bool(local["enabled"]) and all(
        value is not False
        for value in (provider_enabled, sms_region_allowed, origin_authorized)
    )
    if ready:
        detail = (
            "Mobile verification is ready."
            if config is not None
            else "Local mobile-verification configuration is ready; the provider will validate project policy."
        )
    else:
        detail = " ".join(reasons) or "Mobile verification is not ready."
    return {
        "provider": "firebase",
        "ready": ready,
        "diagnostics_available": config is not None,
        "project_id": project_id,
        "phone_number": canonical_phone,
        "country_code": country_code,
        "provider_enabled": provider_enabled,
        "sms_region_allowed": sms_region_allowed,
        "origin_authorized": origin_authorized,
        "detail": detail,
    }


async def verify_firebase_phone_id_token(
    id_token: str,
    expected_phone_number: str,
) -> dict[str, Any]:
    """Verify a recent Firebase phone ID token and bind it to one number."""

    if not id_token or len(id_token) > 8192:
        raise HTTPException(status_code=422, detail="Invalid Firebase phone token")

    canonical_phone, country_code = canonical_mobile_number_details(
        expected_phone_number
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
            detail="Firebase phone verification is invalid or expired",
        ) from exc
    except FirebaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase phone verification is temporarily unavailable",
        ) from exc

    firebase_claim = claims.get("firebase")
    sign_in_provider = (
        firebase_claim.get("sign_in_provider")
        if isinstance(firebase_claim, dict)
        else None
    )
    token_phone = str(claims.get("phone_number") or "")
    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    if (
        sign_in_provider != "phone"
        or token_phone != canonical_phone
        or not uid
        or len(uid) > 128
    ):
        raise HTTPException(
            status_code=422,
            detail="Firebase token does not prove this phone number",
        )

    try:
        auth_time = int(claims["auth_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Firebase phone token is missing authentication time",
        ) from exc

    now_seconds = int(datetime.now(UTC).timestamp())
    maximum_age = max(
        60,
        min(
            _configured_int("FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS", 900),
            3600,
        ),
    )
    if auth_time > now_seconds + 60 or now_seconds - auth_time > maximum_age:
        raise HTTPException(
            status_code=422,
            detail="Firebase phone verification must be completed again",
        )

    return {
        "verified": True,
        "provider": "firebase",
        "line_type": "mobile",
        "line_type_source": "libphonenumber",
        "phone_number": canonical_phone,
        "country_code": country_code,
        "verified_at": datetime.fromtimestamp(auth_time, tz=UTC).isoformat(),
        "firebase_uid": uid,
    }


def _compat_firebase_app() -> Any:
    """Initialize the Firebase Admin app from the protected AIOS credential source."""

    import json
    import os
    from pathlib import Path

    import firebase_admin
    from fastapi import HTTPException, status
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    configured = os.getenv("FIREBASE_ADMIN_CREDENTIALS_JSON", "").strip()
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not configured or not project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase phone verification is not configured",
        )
    if configured.startswith("{"):
        try:
            source: dict[str, Any] | str = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin credentials JSON is invalid",
            ) from exc
    else:
        credential_path = Path(configured)
        if not credential_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin credentials file is unavailable",
            )
        source = str(credential_path)
    try:
        return firebase_admin.initialize_app(
            credentials.Certificate(source),
            options={"projectId": project_id},
        )
    except ValueError:
        return firebase_admin.get_app()


def _firebase_app() -> Any:
    """Backward-compatible Firebase app hook for verified-token callers."""

    return _compat_firebase_app()


def verify_firebase_phone_token(id_token: str, expected_phone: str) -> dict[str, Any]:
    """Verify a recent, non-revoked Firebase phone ID token for one E.164 number."""

    import os
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException
    from firebase_admin import auth

    if not id_token or len(id_token) < 100:
        raise HTTPException(status_code=422, detail="Invalid Firebase ID token")
    try:
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
    firebase_claim = claims.get("firebase")
    provider = (
        firebase_claim.get("sign_in_provider")
        if isinstance(firebase_claim, dict)
        else None
    )
    try:
        authenticated_at = datetime.fromtimestamp(int(claims.get("auth_time")), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Firebase token has no valid auth time",
        ) from exc

    now = datetime.now(UTC)
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
    """Convert verified Firebase claims into a short-lived signed AIOS assertion."""

    import base64
    import hashlib
    import hmac
    import json
    import os
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException, status

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
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded}.{encoded_signature}"
