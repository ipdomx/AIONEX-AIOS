from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    AuditEvent,
    GrowthControlledPilot,
    GrowthSocialProviderCapability,
    Organization,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_owned_connector as meta_owned

META_PROVIDER = "meta"
META_CAPABILITY = "ads.manage"
META_VALIDATION_MODE = "owned_live_no_spend_write"
META_CREDENTIAL_REF = meta_owned.META_CREDENTIAL_REF
META_TARGET_ACCOUNT_ID_ENV = "AIOS_META_OWNED_WRITE_AD_ACCOUNT_ID"
META_CONFIRM_ENV = "AIOS_GS12_META_OWNED_WRITE_VALIDATION"
META_CONFIRM_VALUE = "confirm-paused-create-delete"
META_OBJECTIVE = "OUTCOME_TRAFFIC"
META_STATUS = "PAUSED"


class MetaOwnedWriteValidationError(RuntimeError):
    """Fail-closed GS-12 Meta owned-account no-spend write validation error."""


def _require_confirmation() -> None:
    if os.environ.get(META_CONFIRM_ENV, "").strip() != META_CONFIRM_VALUE:
        raise MetaOwnedWriteValidationError("meta-owned-write-confirmation-required")


def _target_account_id() -> str:
    account_id = os.environ.get(META_TARGET_ACCOUNT_ID_ENV, "").strip()
    if not account_id.isdigit() or not (6 <= len(account_id) <= 32):
        raise MetaOwnedWriteValidationError("meta-owned-write-account-id-invalid")
    return account_id


def opaque_scope_ref(account_id: str) -> str:
    if not account_id.isdigit() or not (6 <= len(account_id) <= 32):
        raise MetaOwnedWriteValidationError("meta-owned-write-account-id-invalid")
    digest = hashlib.sha256(
        f"meta-managed-ad-account:{account_id}".encode("utf-8")
    ).hexdigest()
    return f"accountref://meta/sha256/{digest}"


def _canonical_pilot_id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-pilot-id-invalid"
        ) from None


def _redacted_meta_error(exc: HTTPError, action: str) -> MetaOwnedWriteValidationError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict) and meta_error.get("code") is not None:
            code = meta_error["code"]
    except (ValueError, OSError):
        code = exc.code
    return MetaOwnedWriteValidationError(f"meta-owned-{action}-api-error-{code}")


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
        raise MetaOwnedWriteValidationError(
            f"meta-owned-{action}-failed-{type(exc).__name__.lower()}"
        ) from None
    if not isinstance(payload, dict):
        raise MetaOwnedWriteValidationError(f"meta-owned-{action}-response-invalid")
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
    return {
        str(item.get("permission"))
        for item in payload.get("data", [])
        if isinstance(item, dict)
        and item.get("status") == "granted"
        and item.get("permission")
    }


def _verify_owned_account_membership(
    *,
    account_id: str,
    token: str,
    api_version: str,
    opener: Callable[..., BinaryIO],
) -> None:
    query = urlencode({"fields": "id,account_status", "limit": "100"})
    request = Request(
        f"https://graph.facebook.com/{api_version}/me/adaccounts?{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    payload = _request_json(request, action="owned-account-list", opener=opener)
    data = payload.get("data")
    if not isinstance(data, list):
        raise MetaOwnedWriteValidationError("meta-owned-account-list-invalid")
    paging = payload.get("paging")
    if isinstance(paging, dict) and paging.get("next"):
        raise MetaOwnedWriteValidationError("meta-owned-account-list-truncated")
    accessible = {
        str(item.get("id") or "").removeprefix("act_")
        for item in data
        if isinstance(item, dict)
    }
    if account_id not in accessible:
        raise MetaOwnedWriteValidationError("meta-owned-write-target-not-owned")


def _verify_target_account(
    *,
    account_id: str,
    token: str,
    api_version: str,
    opener: Callable[..., BinaryIO],
) -> dict[str, Any]:
    fields = "id,name,currency,timezone_name,account_status"
    request = Request(
        f"https://graph.facebook.com/{api_version}/act_{account_id}?fields={fields}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    payload = _request_json(request, action="target-account-read", opener=opener)
    returned_id = str(payload.get("id") or "").removeprefix("act_")
    if returned_id != account_id:
        raise MetaOwnedWriteValidationError("meta-owned-write-target-account-mismatch")
    if int(payload.get("account_status") or 0) != 1:
        raise MetaOwnedWriteValidationError("meta-owned-write-target-account-inactive")
    name = str(payload.get("name") or "").strip()
    if not name or "sandbox" in name.lower():
        raise MetaOwnedWriteValidationError("meta-owned-write-target-not-live-owned")
    currency = str(payload.get("currency") or "").strip().upper()
    timezone_name = str(payload.get("timezone_name") or "").strip()
    if re.fullmatch(r"[A-Z]{3}", currency) is None or not timezone_name:
        raise MetaOwnedWriteValidationError("meta-owned-write-target-metadata-invalid")
    return {
        "account_name_present": True,
        "currency": currency,
        "timezone": timezone_name,
        "account_status": 1,
    }


def _campaign_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AIONEX GS12 Owned No-Spend Write Validation {stamp}"


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
        raise MetaOwnedWriteValidationError("meta-owned-write-campaign-id-invalid")
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
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-campaign-readback-mismatch"
        )
    if str(payload.get("status") or "").upper() != META_STATUS:
        raise MetaOwnedWriteValidationError("meta-owned-write-campaign-not-paused")
    if str(payload.get("objective") or "").upper() != META_OBJECTIVE:
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-campaign-objective-mismatch"
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
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-campaign-delete-not-confirmed"
        )


async def _lock_and_validate_pilot(
    session: AsyncSession,
    pilot_id: str,
    *,
    expected_scope_ref: str,
) -> GrowthControlledPilot:
    row = await session.scalar(
        select(GrowthControlledPilot)
        .where(GrowthControlledPilot.id == _canonical_pilot_id(pilot_id))
        .with_for_update()
    )
    if row is None:
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-not-found")
    if row.mode != "live_spend" or row.provider != META_PROVIDER:
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-pilot-mode-provider-mismatch"
        )
    if (
        row.provider_scope != "managed_ad_account"
        or row.scope_ref != expected_scope_ref
    ):
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-scope-mismatch")
    if not row.organization_id:
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-pilot-organization-required"
        )
    organization = await session.scalar(
        select(Organization.id).where(
            Organization.id == row.organization_id,
            Organization.status == "active",
        )
    )
    if organization is None:
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-pilot-organization-inactive"
        )
    if not row.owner_approved_at or not row.owner_approved_by_id:
        raise MetaOwnedWriteValidationError("meta-owned-write-owner-approval-missing")
    approval = dict(
        (row.evidence or {}).get(pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY) or {}
    )
    if not (
        approval.get("approved") is True
        and approval.get("scope") == pilots.NO_SPEND_WRITE_APPROVAL_SCOPE
    ):
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-no-spend-approval-missing"
        )
    if approval.get("consumed") is True or approval.get("completed") is True:
        raise MetaOwnedWriteValidationError(
            "meta-owned-write-no-spend-approval-consumed"
        )
    expiry = row.expires_at
    if expiry is None:
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-expiry-missing")
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-expired")
    if (
        row.launch_authorized
        or row.live_provider_mutation_allowed
        or row.real_spend_allowed
    ):
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-must-be-prelaunch")
    if row.status in {"armed", "completed", "revoked"}:
        raise MetaOwnedWriteValidationError("meta-owned-write-pilot-status-invalid")
    return row


async def _consume_no_spend_approval(
    session: AsyncSession, pilot: GrowthControlledPilot
) -> None:
    evidence = dict(pilot.evidence or {})
    approval = dict(evidence.get(pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY) or {})
    approval.update(
        {
            "consumed": True,
            "consumed_at": datetime.now(timezone.utc).isoformat(),
            "completed": False,
            "provider_call_executed": False,
            "spend_executed": False,
            "real_spend_minor": 0,
        }
    )
    evidence[pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY] = approval
    pilot.evidence = evidence
    pilot.live_provider_mutation_allowed = False
    pilot.real_spend_allowed = False
    pilot.version += 1
    session.add(
        AuditEvent(
            organization_id=pilot.organization_id,
            user_id=approval.get("approved_by"),
            action="growth.pilot.no_spend_write_validation_started",
            resource_type="growth_controlled_pilot",
            resource_id=pilot.id,
            details={
                "provider": META_PROVIDER,
                "approval_scope": pilots.NO_SPEND_WRITE_APPROVAL_SCOPE,
                "approval_consumed": True,
                "provider_call_executed": False,
                "spend_executed": False,
                "real_spend_minor": 0,
            },
        )
    )
    await session.flush()
    # Persist the single-use consumption before any credential read/provider call.
    # A failed remote attempt therefore cannot silently reuse the same approval.
    await session.commit()


def _provider_write_cycle(
    *,
    account_id: str,
    api_version: str,
    token: str,
    opener: Callable[..., BinaryIO],
) -> dict[str, Any]:
    _verify_owned_account_membership(
        account_id=account_id,
        token=token,
        api_version=api_version,
        opener=opener,
    )
    target = _verify_target_account(
        account_id=account_id,
        token=token,
        api_version=api_version,
        opener=opener,
    )
    permissions = _permissions(token, api_version, opener=opener)
    if "ads_management" not in permissions:
        raise MetaOwnedWriteValidationError("meta-ads-management-permission-required")

    campaign_id: str | None = None
    deleted = False
    try:
        campaign_id = _create_paused_campaign(
            account_id=account_id,
            api_version=api_version,
            token=token,
            opener=opener,
        )
        verification_error: MetaOwnedWriteValidationError | None = None
        try:
            _verify_campaign_paused(
                campaign_id=campaign_id,
                api_version=api_version,
                token=token,
                opener=opener,
            )
        except MetaOwnedWriteValidationError as exc:
            verification_error = exc
        try:
            _delete_campaign(
                campaign_id=campaign_id,
                api_version=api_version,
                token=token,
                opener=opener,
            )
            deleted = True
        except MetaOwnedWriteValidationError:
            deleted = False
        if not deleted:
            raise MetaOwnedWriteValidationError(
                "meta-owned-write-campaign-cleanup-failed"
            )
        if verification_error is not None:
            raise verification_error
    finally:
        campaign_id = None

    return {
        **target,
        "ads_management_permission_verified": True,
        "campaign_created": True,
        "campaign_status_verified": META_STATUS,
        "campaign_objective_verified": META_OBJECTIVE,
        "campaign_deleted": True,
        "ad_set_created": False,
        "ad_created": False,
        "budget_configured": False,
        "real_spend_minor": 0,
    }


async def validate_and_record(
    pilot_id: str,
    *,
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    _require_confirmation()
    account_id = _target_account_id()
    scope_ref = opaque_scope_ref(account_id)
    token_file, api_version = meta_owned._safe_config()
    token = ""

    async with AsyncSessionLocal() as session:
        try:
            pilot = await _lock_and_validate_pilot(
                session,
                pilot_id,
                expected_scope_ref=scope_ref,
            )
            durable_pilot_id = pilot.id
            durable_organization_id = pilot.organization_id
            await _consume_no_spend_approval(session, pilot)

            token = meta_owned._read_token(token_file)
            result = _provider_write_cycle(
                account_id=account_id,
                api_version=api_version,
                token=token,
                opener=opener,
            )

            reloaded_pilot = await session.scalar(
                select(GrowthControlledPilot)
                .where(GrowthControlledPilot.id == durable_pilot_id)
                .with_for_update()
            )
            if (
                reloaded_pilot is None
                or reloaded_pilot.organization_id != durable_organization_id
                or reloaded_pilot.scope_ref != scope_ref
            ):
                raise MetaOwnedWriteValidationError(
                    "meta-owned-write-pilot-changed-during-validation"
                )
            pilot = reloaded_pilot

            capability = await session.scalar(
                select(GrowthSocialProviderCapability)
                .where(
                    GrowthSocialProviderCapability.provider == META_PROVIDER,
                    GrowthSocialProviderCapability.capability == META_CAPABILITY,
                )
                .with_for_update()
            )
            if capability is None:
                capability = GrowthSocialProviderCapability(
                    provider=META_PROVIDER,
                    capability=META_CAPABILITY,
                    verification_state="unverified",
                    mutation_class="write",
                    evidence={},
                )
                session.add(capability)
                await session.flush()

            safe_result = {
                "provider": META_PROVIDER,
                "capability": META_CAPABILITY,
                "validation_mode": META_VALIDATION_MODE,
                "pilot_id": pilot.id,
                "organization_id": pilot.organization_id,
                "scope_ref": scope_ref,
                "graph_api_version": api_version,
                **result,
                "live_no_spend_write_verified": True,
                "mutation_allowed": True,
                "spend_allowed": False,
                "execution_adapter_verified": False,
                "raw_secret_persisted": False,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
            stored = dict(capability.evidence or {})
            stored["gs12_meta_owned_no_spend_write"] = dict(safe_result)
            stored["credential_ref"] = META_CREDENTIAL_REF
            stored["live_scope_ref"] = scope_ref
            stored["live_organization_id"] = pilot.organization_id
            stored["live_no_spend_write_verified"] = True
            stored["mutation_allowed"] = True
            stored["spend_allowed"] = False
            stored["execution_adapter_verified"] = False
            stored["raw_secret_persisted"] = False
            capability.evidence = stored
            capability.verification_state = "live_write_verified"
            capability.mutation_class = "write"
            capability.verified_at = datetime.now(timezone.utc)
            capability.version = int(capability.version or 0) + 1

            pilot_evidence = dict(pilot.evidence or {})
            approval = dict(
                pilot_evidence.get(pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY) or {}
            )
            approval.update(
                {
                    "consumed": True,
                    "completed": True,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "provider_call_executed": True,
                    "spend_executed": False,
                    "real_spend_minor": 0,
                }
            )
            pilot_evidence[pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY] = approval
            pilot_evidence["live_no_spend_write_validation"] = {
                "scope_ref": scope_ref,
                "verified": True,
                "real_spend_minor": 0,
                "campaign_deleted": True,
                "raw_secret_persisted": False,
            }
            pilot.evidence = pilot_evidence
            pilot.live_provider_mutation_allowed = False
            pilot.real_spend_allowed = False
            pilot.version += 1
            session.add(
                AuditEvent(
                    organization_id=pilot.organization_id,
                    user_id=None,
                    action="growth.pilot.live_write_verified_no_spend",
                    resource_type="growth_controlled_pilot",
                    resource_id=pilot.id,
                    details={
                        "provider": META_PROVIDER,
                        "scope_ref": scope_ref,
                        "campaign_deleted": True,
                        "real_spend_minor": 0,
                        "mutation_allowed": True,
                        "spend_allowed": False,
                        "execution_adapter_verified": False,
                        "automatic_execution_allowed": False,
                    },
                )
            )
            await session.commit()
            return safe_result
        except Exception:
            await session.rollback()
            raise
        finally:
            token = ""


def _print_safe_scope_ref() -> None:
    print("AIOS_META_OWNED_WRITE_SCOPE_REF_OK")
    print(f"scope_ref={opaque_scope_ref(_target_account_id())}")
    print("provider_call_executed=false")
    print("raw_account_id_printed=false")


def _print_safe_evidence(evidence: dict[str, Any]) -> None:
    print("AIOS_META_OWNED_NO_SPEND_WRITE_VALIDATION_OK")
    print("provider=meta")
    print("capability=ads.manage")
    print("verification_state=live_write_verified")
    print(f"scope_ref={evidence['scope_ref']}")
    print("campaign_created=true")
    print("campaign_status_verified=PAUSED")
    print("campaign_deleted=true")
    print("ad_set_created=false")
    print("ad_created=false")
    print("budget_configured=false")
    print("real_spend_minor=0")
    print("live_no_spend_write_verified=true")
    print("mutation_allowed=true")
    print("spend_allowed=false")
    print("execution_adapter_verified=false")
    print("live_provider_mutation_allowed=false")
    print("raw_secret_persisted=false")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-scope-ref", action="store_true")
    parser.add_argument("--validate-paused-create-delete", action="store_true")
    parser.add_argument("--pilot-id")
    args = parser.parse_args()
    if args.print_scope_ref:
        _print_safe_scope_ref()
        return
    if not args.validate_paused_create_delete or not args.pilot_id:
        raise SystemExit(
            "use --print-scope-ref or --validate-paused-create-delete --pilot-id UUID"
        )
    evidence = asyncio.run(validate_and_record(args.pilot_id))
    _print_safe_evidence(evidence)


if __name__ == "__main__":
    main()
