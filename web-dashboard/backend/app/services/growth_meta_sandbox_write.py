from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import GrowthSocialProviderCapability
from app.services import growth_meta_connector as meta_read

META_PROVIDER = "meta"
META_CAPABILITY = "ads.manage"
META_VALIDATION_MODE = "sandbox_write"
META_CREDENTIAL_REF = meta_read.META_CREDENTIAL_REF
META_CONFIRM_ENV = "AIOS_GS12_META_SANDBOX_WRITE_VALIDATION"
META_CONFIRM_VALUE = "confirm-paused-create-delete"
META_OBJECTIVE = "OUTCOME_TRAFFIC"
META_STATUS = "PAUSED"


class MetaSandboxWriteValidationError(RuntimeError):
    """Fail-closed GS-12 Meta sandbox write validation error."""


def _require_confirmation() -> None:
    if os.environ.get(META_CONFIRM_ENV, "").strip() != META_CONFIRM_VALUE:
        raise MetaSandboxWriteValidationError(
            "meta-sandbox-write-confirmation-required"
        )


def _redacted_meta_error(
    exc: HTTPError, action: str
) -> MetaSandboxWriteValidationError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaSandboxWriteValidationError(f"meta-sandbox-{action}-api-error-{code}")


def _request_json(
    request: Request,
    *,
    action: str,
    opener: Callable[..., BinaryIO],
) -> dict[str, Any]:
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_meta_error(exc, action) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise MetaSandboxWriteValidationError(
            f"meta-sandbox-{action}-failed-{type(exc).__name__.lower()}"
        ) from None
    if not isinstance(payload, dict):
        raise MetaSandboxWriteValidationError(f"meta-sandbox-{action}-response-invalid")
    return payload


def _permissions(
    token: str,
    api_version: str,
    *,
    opener: Callable[..., BinaryIO],
) -> set[str]:
    request = Request(
        f"https://graph.facebook.com/{api_version}/me/permissions",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    payload = _request_json(request, action="permission-read", opener=opener)
    permissions = {
        str(item.get("permission"))
        for item in payload.get("data", [])
        if isinstance(item, dict)
        and item.get("status") == "granted"
        and item.get("permission")
    }
    return permissions


def _campaign_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AIONEX GS12 Sandbox Write Validation {stamp}"


def _create_paused_campaign(
    *,
    account_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> str:
    form = {
        "name": _campaign_name(),
        "objective": META_OBJECTIVE,
        "status": META_STATUS,
        "special_ad_categories": "[]",
        "is_adset_budget_sharing_enabled": "false",
    }
    request = Request(
        f"https://graph.facebook.com/{api_version}/act_{account_id}/campaigns",
        data=urlencode(form).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    payload = _request_json(request, action="campaign-create", opener=opener)
    campaign_id = str(payload.get("id") or "")
    if not campaign_id.isdigit() or not (6 <= len(campaign_id) <= 32):
        raise MetaSandboxWriteValidationError("meta-sandbox-campaign-id-invalid")
    return campaign_id


def _verify_campaign_paused(
    *,
    campaign_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> None:
    request = Request(
        f"https://graph.facebook.com/{api_version}/{campaign_id}?fields=id,name,status,objective",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    payload = _request_json(request, action="campaign-readback", opener=opener)
    if str(payload.get("id") or "") != campaign_id:
        raise MetaSandboxWriteValidationError("meta-sandbox-campaign-readback-mismatch")
    if str(payload.get("status") or "").upper() != META_STATUS:
        raise MetaSandboxWriteValidationError("meta-sandbox-campaign-not-paused")
    if str(payload.get("objective") or "").upper() != META_OBJECTIVE:
        raise MetaSandboxWriteValidationError(
            "meta-sandbox-campaign-objective-mismatch"
        )


def _delete_campaign(
    *,
    campaign_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> None:
    request = Request(
        f"https://graph.facebook.com/{api_version}/{campaign_id}",
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    payload = _request_json(request, action="campaign-delete", opener=opener)
    if payload.get("success") is not True:
        raise MetaSandboxWriteValidationError(
            "meta-sandbox-campaign-delete-not-confirmed"
        )


def probe_meta_sandbox_write_validation(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Create, verify, and delete one PAUSED sandbox campaign with no spend path."""

    _require_confirmation()
    token_file, account_id, api_version = meta_read._safe_config()
    account = meta_read.probe_meta_sandbox_read_only(opener=opener)
    if "sandbox" not in str(account.get("account_name") or "").lower():
        raise MetaSandboxWriteValidationError("meta-account-not-explicitly-sandbox")

    token = meta_read._read_token(token_file)
    campaign_id: str | None = None
    deleted = False
    try:
        permissions = _permissions(token, api_version, opener=opener)
        if "ads_management" not in permissions:
            raise MetaSandboxWriteValidationError(
                "meta-ads-management-permission-required"
            )

        campaign_id = _create_paused_campaign(
            account_id=account_id,
            api_version=api_version,
            token=token,
            opener=opener,
        )
        verification_error: MetaSandboxWriteValidationError | None = None
        try:
            _verify_campaign_paused(
                campaign_id=campaign_id,
                api_version=api_version,
                token=token,
                opener=opener,
            )
        except MetaSandboxWriteValidationError as exc:
            verification_error = exc

        try:
            _delete_campaign(
                campaign_id=campaign_id,
                api_version=api_version,
                token=token,
                opener=opener,
            )
            deleted = True
        except MetaSandboxWriteValidationError:
            deleted = False

        if not deleted:
            raise MetaSandboxWriteValidationError(
                "meta-sandbox-campaign-cleanup-failed"
            )
        if verification_error is not None:
            raise verification_error
    finally:
        token = ""

    return {
        "provider": META_PROVIDER,
        "capability": META_CAPABILITY,
        "validation_mode": META_VALIDATION_MODE,
        "credential_ref": META_CREDENTIAL_REF,
        "graph_api_version": api_version,
        "sandbox_account_verified": True,
        "ads_management_permission_verified": True,
        "campaign_created": True,
        "campaign_status_verified": META_STATUS,
        "campaign_objective_verified": META_OBJECTIVE,
        "campaign_deleted": True,
        "ad_set_created": False,
        "ad_created": False,
        "budget_configured": False,
        "real_spend_minor": 0,
        "sandbox_mutation_verified": True,
        "live_provider_mutation_allowed": False,
        "mutation_allowed": False,
        "spend_allowed": False,
        "execution_adapter_verified": False,
        "sandbox_execution_adapter_verified": True,
        "raw_secret_persisted": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def record_meta_sandbox_write_verified(evidence: dict[str, Any]) -> None:
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
                mutation_class="write",
                evidence={},
            )
            session.add(row)

        safe = {
            key: value for key, value in evidence.items() if key != "credential_ref"
        }
        stored = dict(row.evidence or {})
        stored["gs12_meta_sandbox_write"] = safe
        stored["credential_ref"] = META_CREDENTIAL_REF
        stored["raw_secret_persisted"] = False
        stored["sandbox_mutation_verified"] = True
        stored["sandbox_execution_adapter_verified"] = True
        stored["mutation_allowed"] = False
        stored["spend_allowed"] = False
        stored["execution_adapter_verified"] = False
        row.evidence = stored
        row.verification_state = "sandbox_write_verified"
        row.mutation_class = "write"
        row.verified_at = datetime.now(timezone.utc)
        row.version = int(row.version or 0) + 1
        await session.commit()


async def validate_and_record() -> dict[str, Any]:
    evidence = probe_meta_sandbox_write_validation()
    await record_meta_sandbox_write_verified(evidence)
    return evidence


def _print_safe_evidence(evidence: dict[str, Any]) -> None:
    print("AIOS_META_SANDBOX_WRITE_VALIDATION_OK")
    print("provider=meta")
    print("capability=ads.manage")
    print("verification_state=sandbox_write_verified")
    print("campaign_created=true")
    print("campaign_status_verified=PAUSED")
    print("campaign_deleted=true")
    print("ad_set_created=false")
    print("ad_created=false")
    print("budget_configured=false")
    print("real_spend_minor=0")
    print("sandbox_mutation_verified=true")
    print("live_provider_mutation_allowed=false")
    print("mutation_allowed=false")
    print("spend_allowed=false")
    print("execution_adapter_verified=false")
    print("sandbox_execution_adapter_verified=true")
    print("raw_secret_persisted=false")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-paused-create-delete", action="store_true")
    args = parser.parse_args()
    if not args.validate_paused_create_delete:
        raise SystemExit("use --validate-paused-create-delete")
    evidence = asyncio.run(validate_and_record())
    _print_safe_evidence(evidence)


if __name__ == "__main__":
    main()
