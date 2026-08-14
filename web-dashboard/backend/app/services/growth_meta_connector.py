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
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import GrowthSocialProviderCapability

META_PROVIDER = "meta"
META_CAPABILITY = "ads_read"
META_SANDBOX_MODE = "sandbox"
META_DEFAULT_GRAPH_API_VERSION = "v26.0"
META_TOKEN_FILE_ENV = "AIOS_META_SANDBOX_TOKEN_FILE"
META_AD_ACCOUNT_ID_ENV = "AIOS_META_SANDBOX_AD_ACCOUNT_ID"
META_GRAPH_API_VERSION_ENV = "AIOS_META_GRAPH_API_VERSION"
META_CREDENTIAL_REF = "secretref://file/meta/marketing-api-sandbox-token"
_ALLOWED_SECRET_PREFIX = "/run/operator-secrets/"


class MetaSandboxValidationError(RuntimeError):
    """Fail-closed Meta sandbox validation error."""


def _safe_config() -> tuple[str, str, str]:
    token_file = os.environ.get(META_TOKEN_FILE_ENV, "").strip()
    account_id = os.environ.get(META_AD_ACCOUNT_ID_ENV, "").strip()
    api_version = os.environ.get(
        META_GRAPH_API_VERSION_ENV, META_DEFAULT_GRAPH_API_VERSION
    ).strip()

    if not token_file.startswith(_ALLOWED_SECRET_PREFIX):
        raise MetaSandboxValidationError("meta-sandbox-token-file-not-allowlisted")
    if not account_id.isdigit() or not (6 <= len(account_id) <= 32):
        raise MetaSandboxValidationError("meta-sandbox-account-id-invalid")
    if re.fullmatch(r"v[0-9]+\.[0-9]+", api_version) is None:
        raise MetaSandboxValidationError("meta-graph-api-version-invalid")
    return token_file, account_id, api_version


def _read_token(token_file: str) -> str:
    path = Path(token_file)
    if not path.is_file():
        raise MetaSandboxValidationError("meta-sandbox-token-file-missing")
    token = path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 4096:
        raise MetaSandboxValidationError("meta-sandbox-token-invalid")
    return token


def _redacted_meta_error(exc: HTTPError) -> MetaSandboxValidationError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        pass
    return MetaSandboxValidationError(f"meta-api-error-{code}")


def probe_meta_sandbox_read_only(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Perform one Meta Marketing API sandbox read with no mutation or spend."""

    token_file, account_id, api_version = _safe_config()
    token = _read_token(token_file)
    fields = "id,name,currency,timezone_name,account_status"
    url = (
        f"https://graph.facebook.com/{api_version}/act_{account_id}" f"?fields={fields}"
    )
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_meta_error(exc) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaSandboxValidationError(
            f"meta-api-read-failed-{type(exc).__name__.lower()}"
        ) from None
    finally:
        token = ""

    if not isinstance(payload, dict):
        raise MetaSandboxValidationError("meta-api-response-invalid")
    returned_id = str(payload.get("id") or "")
    if returned_id not in {account_id, f"act_{account_id}"}:
        raise MetaSandboxValidationError("meta-api-account-mismatch")

    return {
        "provider": META_PROVIDER,
        "capability": META_CAPABILITY,
        "validation_mode": META_SANDBOX_MODE,
        "credential_ref": META_CREDENTIAL_REF,
        "graph_api_version": api_version,
        "ad_account_id": account_id,
        "account_name": str(payload.get("name") or ""),
        "currency": str(payload.get("currency") or ""),
        "timezone": str(payload.get("timezone_name") or ""),
        "account_status": payload.get("account_status"),
        "provider_call_allowed": True,
        "mutation_allowed": False,
        "spend_allowed": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def record_meta_sandbox_verified(evidence: dict[str, Any]) -> None:
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
        stored["gs09_meta_sandbox"] = {
            key: value for key, value in evidence.items() if key != "credential_ref"
        }
        stored["credential_ref"] = META_CREDENTIAL_REF
        stored["raw_secret_persisted"] = False
        row.evidence = stored
        row.verification_state = "sandbox_verified"
        row.mutation_class = "read"
        row.verified_at = datetime.now(timezone.utc)
        row.version = int(row.version or 0) + 1
        await session.commit()


async def validate_and_record() -> dict[str, Any]:
    evidence = probe_meta_sandbox_read_only()
    await record_meta_sandbox_verified(evidence)
    return evidence


def _print_safe_evidence(evidence: dict[str, Any]) -> None:
    print("AIOS_META_SANDBOX_VALIDATION_OK")
    print("provider=meta")
    print("capability=ads_read")
    print("verification_state=sandbox_verified")
    print(f"account_name={evidence['account_name']}")
    print(f"currency={evidence['currency']}")
    print(f"timezone={evidence['timezone']}")
    print(f"account_status={evidence['account_status']}")
    print("provider_call_allowed=true")
    print("mutation_allowed=false")
    print("spend_allowed=false")
    print("raw_secret_persisted=false")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-sandbox-read-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_sandbox_read_only:
        raise SystemExit("use --validate-sandbox-read-only")
    evidence = asyncio.run(validate_and_record())
    _print_safe_evidence(evidence)


if __name__ == "__main__":
    main()
