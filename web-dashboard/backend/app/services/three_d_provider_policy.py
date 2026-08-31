"""Phase 34F jurisdiction, licensing disclosure, and provider routing policy."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import time
from typing import Any
import urllib.error
import urllib.request

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings

HUNYUAN_PROVIDER = "hunyuan3d"
TRIPOSR_PROVIDER = "triposr"
THREE_D_TERMS_VERSION = "3d-model-service-2026-08-09"

# Security quarantine for the currently deployed Hunyuan v11 runtime. The exact
# production digest was re-audited during the 2026-08-30 pre-launch closeout and
# its installed Python inventory contains unresolved high-impact advisories across
# the GPU/model stack.  This constant is deliberately source-controlled rather
# than Owner-configurable: legal/commercial attestations must never be able to
# bypass a technical security gate.  A later GPU rebuild must earn a fresh
# security + functional acceptance before this can become True.
HUNYUAN_RUNTIME_SECURITY_APPROVED = False
HUNYUAN_QUARANTINED_IMAGE_DIGEST = (
    "sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc"
)

_RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
_RUNPOD_CONTROL_PLANE_TIMEOUT_SECONDS = 5.0
_RUNPOD_REGION_CACHE_TTL_SECONDS = 30.0
_RUNPOD_MAX_CONTROL_PLANE_BYTES = 1_000_000
_RUNPOD_US_DATACENTER_ID = re.compile(r"US-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
_RUNPOD_ENDPOINT_REGIONS_QUERY = """
query AiosEndpointRegions {
  myself {
    endpoints {
      id
      dataCenterIds
    }
  }
}
""".strip()
_runpod_endpoint_region_cache: dict[str, tuple[float, bool]] = {}

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


def _fetch_runpod_endpoint_datacenter_ids(
    api_key: str, endpoint_id: str
) -> tuple[str, ...] | None:
    payload = json.dumps({"query": _RUNPOD_ENDPOINT_REGIONS_QUERY}).encode("utf-8")
    request = urllib.request.Request(
        _RUNPOD_GRAPHQL_URL,
        data=payload,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; AIONEX-AIOS/34F)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=_RUNPOD_CONTROL_PLANE_TIMEOUT_SECONDS
        ) as response:
            raw = response.read(_RUNPOD_MAX_CONTROL_PLANE_BYTES + 1)
        if len(raw) > _RUNPOD_MAX_CONTROL_PLANE_BYTES:
            return None
        document = json.loads(raw.decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(document, dict) or document.get("errors"):
        return None
    data = document.get("data")
    myself = data.get("myself") if isinstance(data, dict) else None
    endpoints = myself.get("endpoints") if isinstance(myself, dict) else None
    if not isinstance(endpoints, list):
        return None
    for endpoint in endpoints:
        if not isinstance(endpoint, dict) or endpoint.get("id") != endpoint_id:
            continue
        datacenter_ids = endpoint.get("dataCenterIds")
        if not isinstance(datacenter_ids, list):
            return None
        if any(
            not isinstance(item, str) or not item.strip() for item in datacenter_ids
        ):
            return None
        return tuple(item.strip() for item in datacenter_ids)
    return None


def _is_us_datacenter_id(value: object) -> bool:
    normalized = str(value or "").strip().upper()
    return bool(_RUNPOD_US_DATACENTER_ID.fullmatch(normalized))


async def _hunyuan_endpoint_is_us_only(
    values: dict[str, str], *, bypass_cache: bool = False
) -> bool:
    api_key = values.get("RUNPOD_API_KEY", "").strip()
    endpoint_id = values.get("RUNPOD_ENDPOINT_ID", "").strip()
    if not api_key or not endpoint_id:
        return False

    now = time.monotonic()
    cached = _runpod_endpoint_region_cache.get(endpoint_id)
    if not bypass_cache and cached is not None and cached[0] > now:
        return cached[1]

    try:
        datacenter_ids = await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_runpod_endpoint_datacenter_ids, api_key, endpoint_id
            ),
            timeout=_RUNPOD_CONTROL_PLANE_TIMEOUT_SECONDS + 1.0,
        )
        verified = datacenter_ids is not None and bool(datacenter_ids) and all(
            _is_us_datacenter_id(item) for item in (datacenter_ids or ())
        )
    except Exception:
        verified = False

    _runpod_endpoint_region_cache[endpoint_id] = (
        time.monotonic() + _RUNPOD_REGION_CACHE_TTL_SECONDS,
        verified,
    )
    return verified


async def provider_runtime_configured(
    provider: str,
    *,
    expected_endpoint_id: str | None = None,
    bypass_cache: bool = False,
) -> bool:
    values = _provider_env()
    if not values.get("RUNPOD_API_KEY", "").strip():
        return False
    key = provider.strip().lower()
    if key not in {HUNYUAN_PROVIDER, TRIPOSR_PROVIDER}:
        return False
    if key == HUNYUAN_PROVIDER and not HUNYUAN_RUNTIME_SECURITY_APPROVED:
        return False
    endpoint_key = (
        "RUNPOD_ENDPOINT_ID"
        if key == HUNYUAN_PROVIDER
        else "RUNPOD_FALLBACK_ENDPOINT_ID"
    )
    configured_endpoint_id = values.get(endpoint_key, "").strip()
    if not configured_endpoint_id:
        return False
    if expected_endpoint_id is not None:
        expected = expected_endpoint_id.strip()
        if not expected or expected != configured_endpoint_id:
            return False
    if key == HUNYUAN_PROVIDER:
        if values.get("RUNPOD_HUNYUAN_LOCATION", "").strip().upper() != "US":
            return False
        return await _hunyuan_endpoint_is_us_only(values, bypass_cache=bypass_cache)
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
