from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import GrowthSocialProviderCapability

META_PROVIDER = "meta"
META_CAPABILITY = "ads_read"
META_SCOPE = "owned_assets"
META_VALIDATION_MODE = "read_only"
META_DEFAULT_GRAPH_API_VERSION = "v26.0"
META_TOKEN_FILE_ENV = "AIOS_META_OWNED_TOKEN_FILE"
META_GRAPH_API_VERSION_ENV = "AIOS_META_GRAPH_API_VERSION"
META_CREDENTIAL_REF = "secretref://file/meta/marketing-api-token"
_ALLOWED_SECRET_PREFIX = "/run/operator-secrets/"


class MetaOwnedReadOnlyValidationError(RuntimeError):
    """Fail-closed Meta owned-assets read-only validation error."""


def _safe_config() -> tuple[str, str]:
    token_file = os.environ.get(META_TOKEN_FILE_ENV, "").strip()
    api_version = os.environ.get(
        META_GRAPH_API_VERSION_ENV, META_DEFAULT_GRAPH_API_VERSION
    ).strip()
    if not token_file.startswith(_ALLOWED_SECRET_PREFIX):
        raise MetaOwnedReadOnlyValidationError("meta-owned-token-file-not-allowlisted")
    if re.fullmatch(r"v[0-9]+\.[0-9]+", api_version) is None:
        raise MetaOwnedReadOnlyValidationError("meta-graph-api-version-invalid")
    return token_file, api_version


def _read_token(token_file: str) -> str:
    path = Path(token_file)
    if not path.is_file():
        raise MetaOwnedReadOnlyValidationError("meta-owned-token-file-missing")
    token = path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 4096:
        raise MetaOwnedReadOnlyValidationError("meta-owned-token-invalid")
    return token


def _redacted_meta_error(exc: HTTPError) -> MetaOwnedReadOnlyValidationError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaOwnedReadOnlyValidationError(f"meta-api-error-{code}")


def probe_meta_owned_assets_read_only(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Validate ads_read against only ad accounts accessible to the token owner."""

    token_file, api_version = _safe_config()
    token = _read_token(token_file)
    query = urlencode({"fields": "id,account_status", "limit": "100"})
    url = f"https://graph.facebook.com/{api_version}/me/adaccounts?{query}"
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_meta_error(exc) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaOwnedReadOnlyValidationError(
            f"meta-api-read-failed-{type(exc).__name__.lower()}"
        ) from None
    finally:
        token = ""

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise MetaOwnedReadOnlyValidationError("meta-api-response-invalid")

    accounts = payload["data"]
    active_count = sum(
        1
        for item in accounts
        if isinstance(item, dict) and item.get("account_status") == 1
    )
    raw_paging = payload.get("paging")
    paging: dict[str, Any] = raw_paging if isinstance(raw_paging, dict) else {}

    return {
        "provider": META_PROVIDER,
        "capability": META_CAPABILITY,
        "scope": META_SCOPE,
        "validation_mode": META_VALIDATION_MODE,
        "credential_ref": META_CREDENTIAL_REF,
        "graph_api_version": api_version,
        "ad_accounts_count": len(accounts),
        "active_ad_accounts_count": active_count,
        "result_page_truncated": bool(paging.get("next")),
        "provider_call_allowed": True,
        "mutation_allowed": False,
        "spend_allowed": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def record_meta_owned_read_only_verified(evidence: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(GrowthSocialProviderCapability).where(
                GrowthSocialProviderCapability.provider == META_PROVIDER,
                GrowthSocialProviderCapability.capability == META_CAPABILITY,
            )
        )
        if row is None:
            row = GrowthSocialProviderCapability(
                provider=META_PROVIDER,
                capability=META_CAPABILITY,
                verification_state="unverified",
                mutation_class="read",
                evidence={},
            )
            session.add(row)

        stored = dict(row.evidence or {})
        stored["gs09_meta_owned_read_only"] = {
            key: value for key, value in evidence.items() if key != "credential_ref"
        }
        stored["owned_read_only_credential_ref"] = META_CREDENTIAL_REF
        stored["raw_secret_persisted"] = False
        row.evidence = stored
        row.verification_state = "read_only_verified"
        row.mutation_class = "read"
        row.verified_at = datetime.now(timezone.utc)
        row.version = int(row.version or 0) + 1
        await session.commit()


async def validate_and_record() -> dict[str, Any]:
    evidence = probe_meta_owned_assets_read_only()
    await record_meta_owned_read_only_verified(evidence)
    return evidence


def _print_safe_evidence(evidence: dict[str, Any]) -> None:
    print("AIOS_META_OWNED_READ_ONLY_VALIDATION_OK")
    print("provider=meta")
    print("capability=ads_read")
    print("scope=owned_assets")
    print("verification_state=read_only_verified")
    print(f"ad_accounts_count={evidence['ad_accounts_count']}")
    print(f"active_ad_accounts_count={evidence['active_ad_accounts_count']}")
    print(f"result_page_truncated={str(evidence['result_page_truncated']).lower()}")
    print("provider_call_allowed=true")
    print("mutation_allowed=false")
    print("spend_allowed=false")
    print("raw_secret_persisted=false")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-owned-assets-read-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_owned_assets_read_only:
        raise SystemExit("use --validate-owned-assets-read-only")
    evidence = asyncio.run(validate_and_record())
    _print_safe_evidence(evidence)


if __name__ == "__main__":
    main()
