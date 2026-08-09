"""Phase 34F jurisdiction, licensing disclosure, and provider routing policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings

HUNYUAN_PROVIDER = "hunyuan3d"
TRIPOSR_PROVIDER = "triposr"
THREE_D_TERMS_VERSION = "3d-model-service-2026-08-09"

# Tencent Hunyuan 3D 2.1 Community License territory excludes the EU, UK and
# South Korea. Country codes use ISO 3166-1 alpha-2 as supplied by Cloudflare
# and registration telemetry. GB is the ISO code used for the United Kingdom.
EU_COUNTRY_CODES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)
HUNYUAN_EXCLUDED_COUNTRY_CODES = frozenset({*EU_COUNTRY_CODES, "GB", "KR"})

HUNYUAN_LICENSE_SOURCE_COMMIT = "82920d643c0dc2f7bfd7255f45f62d386edfe60c"
HUNYUAN_LICENSE_SHA256 = (
    "b79ac5e11ce063b6c6570dbe9686a45a03ba08bd248aa6aa82fb342a23a81c0c"
)
TRIPOSR_SOURCE_COMMIT = "107cefdc244c39106fa830359024f6a2f1c78871"
TRIPOSR_MODEL_REVISION = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
TRIPOSR_LICENSE_SHA256 = (
    "ade0a66629bdd7e01e46b3296b3851cff0fd27989bca53da470ad6e96ed620fb"
)


def _provider_env() -> dict[str, str]:
    source = Path(settings.THREE_D_RUNPOD_SECRET_FILE)
    if not source.is_file() or source.is_symlink():
        return {}
    values: dict[str, str] = {}
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def provider_runtime_configured(provider: str) -> bool:
    values = _provider_env()
    if not values.get("RUNPOD_API_KEY", "").strip():
        return False
    key = provider.strip().lower()
    endpoint_key = (
        "RUNPOD_ENDPOINT_ID"
        if key == HUNYUAN_PROVIDER
        else "RUNPOD_FALLBACK_ENDPOINT_ID"
    )
    if not values.get(endpoint_key, "").strip():
        return False
    if key == HUNYUAN_PROVIDER:
        return values.get("RUNPOD_HUNYUAN_LOCATION", "").strip().upper() == "US"
    return True


def normalize_country(value: object) -> str | None:
    code = str(value or "").strip().upper()
    if len(code) != 2 or not code.isalpha() or code in {"XX", "T1"}:
        return None
    return code


async def request_country(
    session: AsyncSession, actor: UserRecord, request: Request
) -> tuple[str | None, str]:
    """Resolve jurisdiction only from Cloudflare's protected edge headers.

    A direct/internal request or a request without the complete Cloudflare header
    set is deliberately treated as unknown, which can only route to the
    permissive fallback. Registration telemetry is retained for audit but is not
    authoritative enough to unlock a territory-limited model.
    """
    del session, actor
    if not request.headers.get("cf-ray") or not request.headers.get("cf-connecting-ip"):
        return None, "unknown"
    edge = normalize_country(request.headers.get("cf-ipcountry"))
    if edge:
        return edge, "cloudflare"
    return None, "unknown"


def hunyuan_license_permits_country(
    policy: dict[str, Any], country: str | None
) -> bool:
    if not bool(policy.get("hunyuan_license_acknowledged")):
        return False
    if not bool(policy.get("hunyuan_commercial_eligibility_attested")):
        return False
    if not bool(policy.get("service_provider_legal_name_confirmed")):
        return False
    if not str(policy.get("service_provider_legal_name") or "").strip():
        return False
    if country is None:
        return False
    excluded = {
        str(item).strip().upper()
        for item in policy.get(
            "hunyuan_excluded_country_codes", HUNYUAN_EXCLUDED_COUNTRY_CODES
        )
        if str(item).strip()
    }
    return country.upper() not in excluded


def provider_candidates(policy: dict[str, Any], country: str | None) -> list[str]:
    candidates: list[str] = []
    if hunyuan_license_permits_country(policy, country):
        candidates.append(HUNYUAN_PROVIDER)
    if bool(policy.get("fallback_enabled", True)):
        candidates.append(TRIPOSR_PROVIDER)
    if not candidates:
        raise HTTPException(
            status_code=451,
            detail={
                "code": "THREE_D_PROVIDER_NOT_PERMITTED",
                "message": "No licensed 3D model provider is available for this jurisdiction under the Owner policy.",
            },
        )
    return candidates


def provider_disclosure(policy: dict[str, Any], provider: str) -> dict[str, Any]:
    legal_name = str(policy.get("service_provider_legal_name") or "AIONEX AIOS").strip()
    if provider == HUNYUAN_PROVIDER:
        return {
            "provider": provider,
            "model": "Tencent Hunyuan 3D 2.1",
            "operator": legal_name,
            "license": "Tencent Hunyuan 3D 2.1 Community License Agreement",
            "territory_limited": True,
            "tencent_affiliation": False,
            "machine_generated": True,
            "terms_version": str(
                policy.get("third_party_terms_version") or THREE_D_TERMS_VERSION
            ),
        }
    if provider == TRIPOSR_PROVIDER:
        return {
            "provider": provider,
            "model": "TripoSR",
            "operator": legal_name,
            "license": "MIT",
            "territory_limited": False,
            "tencent_affiliation": None,
            "machine_generated": True,
            "terms_version": str(
                policy.get("third_party_terms_version") or THREE_D_TERMS_VERSION
            ),
        }
    raise HTTPException(status_code=503, detail={"code": "THREE_D_PROVIDER_UNKNOWN"})


def require_terms_acceptance(
    policy: dict[str, Any], *, accepted: bool, version: str
) -> str:
    expected = str(policy.get("third_party_terms_version") or THREE_D_TERMS_VERSION)
    if not accepted or version.strip() != expected:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "THREE_D_TERMS_ACCEPTANCE_REQUIRED",
                "terms_version": expected,
                "message": "Accept the current third-party 3D model terms before generation.",
            },
        )
    return expected
