from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Correct locale parsing so a language such as `en` is never stored as a country.
replace_once(
    "web-dashboard/frontend/src/components/auth/AuthGate.tsx",
    '''function inferredCountryCode(): string {
  if (typeof navigator === "undefined") return "";
  const locale = navigator.language.replace("_", "-");
  const segments = locale.split("-");
  const region = segments.find((segment) => /^[A-Za-z]{2}$/.test(segment));
  return region?.toUpperCase() ?? "";
}
''',
    '''function localeCountryCode(locale: string): string {
  const normalized = locale.replace("_", "-");
  try {
    const region = new Intl.Locale(normalized).region;
    if (region && /^[A-Za-z]{2}$/.test(region)) return region.toUpperCase();
  } catch {
    // Fall through to conservative BCP-47 parsing for older browsers.
  }
  const region = normalized
    .split("-")
    .slice(1)
    .find((segment) => /^[A-Za-z]{2}$/.test(segment));
  return region?.toUpperCase() ?? "";
}

function inferredCountryCode(): string {
  if (typeof navigator === "undefined") return "";
  const locales =
    navigator.languages && navigator.languages.length > 0
      ? navigator.languages
      : [navigator.language];
  for (const locale of locales) {
    const country = localeCountryCode(locale);
    if (country) return country;
  }
  return "";
}
''',
)

# Run a server-side readiness check before Firebase sends an SMS. It validates the
# real mobile-number country, Phone provider, SMS-region policy, and authorized host.
replace_once(
    "web-dashboard/frontend/src/components/auth/AuthGate.tsx",
    '''    try {
      const challenge = await startFirebasePhoneVerification(
        firebasePhone.web_config,
        normalizedPhone,
        "firebase-phone-recaptcha",
      );
''',
    '''    try {
      const readiness = await authService.getFirebasePhoneReadiness(
        normalizedPhone,
        window.location.origin,
      );
      setCountryCode(readiness.country_code);
      if (!readiness.ready) {
        throw new Error(
          readiness.detail ||
            "Firebase phone verification is not ready for this number.",
        );
      }
      const challenge = await startFirebasePhoneVerification(
        firebasePhone.web_config,
        readiness.phone_number,
        "firebase-phone-recaptcha",
      );
''',
)

# Add the readiness contract and API call.
replace_once(
    "web-dashboard/frontend/src/lib/auth-service.ts",
    '''export type FreeTierStatus = {
''',
    '''export type FirebasePhoneReadiness = {
  provider: "firebase";
  ready: boolean;
  diagnostics_available: boolean;
  project_id: string;
  phone_number: string;
  country_code: string;
  provider_enabled: boolean | null;
  sms_region_allowed: boolean | null;
  origin_authorized: boolean | null;
  detail: string;
};

export type FreeTierStatus = {
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/auth-service.ts",
    '''  async getFreeTierStatus(): Promise<FreeTierStatus> {
''',
    '''  async getFirebasePhoneReadiness(
    phoneNumber: string,
    origin: string,
  ): Promise<FirebasePhoneReadiness> {
    return apiClient.get<FirebasePhoneReadiness>(
      "/auth/firebase/phone/readiness",
      { params: { phone_number: phoneNumber, origin } },
    );
  },

  async getFreeTierStatus(): Promise<FreeTierStatus> {
''',
)

# Preserve actionable Firebase failure details instead of the misleading generic text.
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''function firebaseErrorMessage(error: unknown): string {
''',
    '''function firebaseErrorMessage(
  error: unknown,
  projectId = "",
): string {
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''    "auth/captcha-check-failed": "The security check failed. Please try again.",
''',
    '''    "auth/captcha-check-failed":
      "The reCAPTCHA security check failed. Confirm this site is an authorized Firebase Authentication domain.",
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''    "auth/operation-not-allowed":
      "Phone verification is not enabled for this project.",
''',
    '''    "auth/operation-not-allowed":
      `Firebase rejected phone sign-in for project ${projectId || "the configured project"}. Enable the Phone provider and allow this number's country in Authentication > Settings > SMS region policy.`,
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''    "auth/unauthorized-domain":
      "This site domain is not authorized in Firebase.",
''',
    '''    "auth/unauthorized-domain":
      "This site host is not listed in Firebase Authentication authorized domains.",
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''  auth.languageCode = navigator.language || "en";
''',
    '''  auth.useDeviceLanguage();
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''    throw new Error(firebaseErrorMessage(error), { cause: error });
''',
    '''    throw new Error(firebaseErrorMessage(error, config.projectId), {
      cause: error,
    });
''',
)
replace_once(
    "web-dashboard/frontend/src/lib/firebase-phone-auth.ts",
    '''    throw new Error(firebaseErrorMessage(error), { cause: error });
  } finally {
''',
    '''    throw new Error(
      firebaseErrorMessage(
        error,
        String(challenge.auth.app.options.projectId ?? ""),
      ),
      { cause: error },
    );
  } finally {
''',
)

# Add server-side Firebase project diagnostics and authoritative mobile country parsing.
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import firebase_admin
import phonenumbers
''',
    '''import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import firebase_admin
import phonenumbers
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''from firebase_admin.exceptions import FirebaseError
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
''',
    '''from firebase_admin.exceptions import FirebaseError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''_FIREBASE_APP_SIGNATURE: tuple[str, str, str] | None = None
''',
    '''_FIREBASE_APP_SIGNATURE: tuple[str, str, str] | None = None
_IDENTITY_CONFIG_LOCK = threading.Lock()
_IDENTITY_CONFIG_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)
_IDENTITY_CONFIG_TTL_SECONDS = 300
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''def _admin_verification_ready() -> bool:
''',
    '''def _identity_platform_config() -> dict[str, Any] | None:
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
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''def _canonical_mobile_number(phone_number: str) -> str:
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


async def verify_firebase_phone_id_token(
''',
    '''def _canonical_mobile_number(phone_number: str) -> str:
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
            str(value).upper()
            for value in allowlist.get("allowedRegions", [])
            if value
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


def firebase_phone_readiness(phone_number: str, origin: str | None = None) -> dict[str, Any]:
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
        reasons.append("Firebase web or Admin verification is not configured.")
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
            reasons.append("Firebase Phone sign-in is disabled for this project.")
        if sms_region_allowed is False:
            reasons.append(
                f"Firebase SMS region policy does not allow {country_code}."
            )
        if origin_authorized is False:
            reasons.append(
                f"The site host {origin_host} is not an authorized Firebase domain."
            )

    ready = bool(local["enabled"]) and all(
        value is not False
        for value in (provider_enabled, sms_region_allowed, origin_authorized)
    )
    if ready:
        detail = (
            "Firebase phone verification is ready."
            if config is not None
            else "Local Firebase configuration is ready; Firebase will validate project policy."
        )
    else:
        detail = " ".join(reasons) or "Firebase phone verification is not ready."
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
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''    canonical_phone = _canonical_mobile_number(expected_phone_number)
''',
    '''    canonical_phone, country_code = canonical_mobile_number_details(
        expected_phone_number
    )
''',
)
replace_once(
    "web-dashboard/backend/app/services/firebase_phone.py",
    '''        "phone_number": canonical_phone,
        "verified_at": datetime.fromtimestamp(auth_time, tz=UTC).isoformat(),
''',
    '''        "phone_number": canonical_phone,
        "country_code": country_code,
        "verified_at": datetime.fromtimestamp(auth_time, tz=UTC).isoformat(),
''',
)

# Expose readiness through the existing public auth contract.
replace_once(
    "web-dashboard/backend/app/api/v1/endpoints/auth.py",
    '''from fastapi import APIRouter, Depends, HTTPException, Request, status
''',
    '''from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
''',
)
replace_once(
    "web-dashboard/backend/app/api/v1/endpoints/auth.py",
    '''from app.services.firebase_phone import firebase_public_configuration
''',
    '''from app.services.firebase_phone import (
    firebase_phone_readiness,
    firebase_public_configuration,
)
''',
)
replace_once(
    "web-dashboard/backend/app/api/v1/endpoints/auth.py",
    '''@router.post(
    "/register/free",
''',
    '''@router.get("/firebase/phone/readiness")
async def get_public_firebase_phone_readiness(
    phone_number: str = Query(
        min_length=8,
        max_length=20,
        pattern=r"^\\+[1-9][0-9]{7,14}$",
    ),
    origin: str | None = Query(default=None, max_length=512),
):
    return firebase_phone_readiness(phone_number, origin)


@router.post(
    "/register/free",
''',
)

# Enforce that the declared country agrees with the verified mobile range.
replace_once(
    "web-dashboard/backend/app/services/free_tier.py",
    '''    normalized_phone = str(phone_assertion.get("phone_number") or normalized_phone)
    sanitized = sanitize_registration_telemetry(telemetry)
''',
    '''    normalized_phone = str(phone_assertion.get("phone_number") or normalized_phone)
    verified_country = str(phone_assertion.get("country_code") or "").upper()
    if verified_country and normalized_country != verified_country:
        raise HTTPException(
            status_code=422,
            detail="Declared country must match the verified mobile-number country",
        )
    sanitized = sanitize_registration_telemetry(telemetry)
''',
)

# Extend focused tests and route contracts.
replace_once(
    "web-dashboard/backend/tests/test_batch7_quality_contracts.py",
    '''        "/auth/firebase/phone/public",
''',
    '''        "/auth/firebase/phone/public",
        "/auth/firebase/phone/readiness",
''',
)
replace_once(
    "web-dashboard/backend/tests/test_firebase_phone_auth.py",
    '''        "phone_number": PHONE,
        "verified_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
''',
    '''        "phone_number": PHONE,
        "country_code": "AE",
        "verified_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
''',
)
replace_once(
    "web-dashboard/backend/tests/test_firebase_phone_auth.py",
    '''    assert "firebase_id_token?: string" in auth_service


def test_production_mounts_admin_credential_and_drops_privileges() -> None:
''',
    '''    assert "firebase_id_token?: string" in auth_service
    assert "new Intl.Locale" in auth_gate
    assert "getFirebasePhoneReadiness" in auth_gate
    assert "SMS region policy" in firebase_client


def test_mobile_country_and_firebase_project_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(firebase_phone, "_get_firebase_app", lambda: object())
    monkeypatch.setattr(
        firebase_phone,
        "_identity_platform_config",
        lambda: {
            "signIn": {"phoneNumber": {"enabled": True}},
            "smsRegionConfig": {
                "allowlistOnly": {"allowedRegions": ["AE"]}
            },
            "authorizedDomains": ["209.74.65.106"],
        },
    )

    result = firebase_phone.firebase_phone_readiness(
        PHONE,
        "http://209.74.65.106",
    )

    assert result["ready"] is True
    assert result["country_code"] == "AE"
    assert result["phone_number"] == PHONE
    assert result["provider_enabled"] is True
    assert result["sms_region_allowed"] is True
    assert result["origin_authorized"] is True


def test_firebase_readiness_reports_sms_region_and_domain_blockers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(firebase_phone, "_get_firebase_app", lambda: object())
    monkeypatch.setattr(
        firebase_phone,
        "_identity_platform_config",
        lambda: {
            "signIn": {"phoneNumber": {"enabled": True}},
            "smsRegionConfig": {
                "allowlistOnly": {"allowedRegions": ["EG"]}
            },
            "authorizedDomains": ["example.com"],
        },
    )

    result = firebase_phone.firebase_phone_readiness(
        PHONE,
        "http://209.74.65.106",
    )

    assert result["ready"] is False
    assert result["sms_region_allowed"] is False
    assert result["origin_authorized"] is False
    assert "SMS region policy" in result["detail"]
    assert "authorized Firebase domain" in result["detail"]


def test_production_mounts_admin_credential_and_drops_privileges() -> None:
''',
)

print("Firebase phone readiness and country fixes applied")
