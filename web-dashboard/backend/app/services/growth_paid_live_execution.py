"""GS-12 durable fail-closed orchestration of one approved Meta paid-campaign plan.

The orchestrator creates only PAUSED provider objects. It never activates a campaign,
never automatically retries an ambiguous provider mutation, and never exposes raw
provider object IDs. Every write is guarded by the existing same-transaction
``runtime_authorization()`` check inside ``growth_meta_live_execution_adapter``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthControlledPilot,
    GrowthPaidAd,
    GrowthPaidAdSet,
    GrowthPaidCampaign,
    GrowthPaidCreative,
    GrowthPaidLiveExecution,
    GrowthPaidLiveExecutionStep,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_live_execution_adapter as adapter
from app.services import growth_meta_page_discovery as pages
from app.services import growth_meta_target_discovery as targets
from app.services import growth_paid_live_plan as live_plan

EXECUTION_VERSION = "gs12-controlled-live-execution-v1"
EXECUTE_CONFIRMATION = "EXECUTE PAUSED META PLAN"
STALE_EXECUTING_AFTER_SECONDS = 90
_ALLOWED_PLACEMENTS = {"feed", "stories"}
_ALLOWED_CREATIVE_FORMATS = {"image", "link"}
_SAFE_ERROR = re.compile(r"[^a-zA-Z0-9_.:,\-]+")


class GrowthPaidLiveExecutionError(RuntimeError):
    """Fail-closed controlled live execution error."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_owner(actor: UserRecord) -> None:
    if actor.role != "Super Owner":
        raise GrowthPaidLiveExecutionError("super-owner-required")


def _provider_ref(kind: str, provider_id: str) -> str:
    digest = hashlib.sha256(f"meta:{kind}:{provider_id}".encode("utf-8")).hexdigest()
    return f"metaobjref://sha256/{digest}"


def _request_digest(spec: adapter.MetaRequestSpec) -> str:
    raw = json.dumps(
        {
            "method": spec.method,
            "path": spec.path,
            "operation": spec.operation,
            "form": spec.form,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_error_code(exc: Exception) -> str:
    raw = f"{type(exc).__name__}:{exc}"[:500]
    lowered = raw.lower()
    if any(
        marker in lowered for marker in ("bearer ", "token=", "secret=", "password=")
    ):
        return "live-execution-provider-failure"
    clean = _SAFE_ERROR.sub("-", raw).strip("-")[:160]
    return clean or "live-execution-failure"


def _numeric_provider_id(payload: dict[str, Any], kind: str) -> str:
    raw = str(payload.get("id") or "").strip()
    if not raw.isdigit() or not (6 <= len(raw) <= 32):
        raise GrowthPaidLiveExecutionError(f"provider-{kind}-id-invalid")
    return raw


def _destination_with_utm(creative: GrowthPaidCreative) -> str:
    destination = str(creative.destination_url or "").strip()
    parsed = urlsplit(destination)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GrowthPaidLiveExecutionError("creative-destination-invalid")
    if parsed.username or parsed.password:
        raise GrowthPaidLiveExecutionError("creative-destination-credentials-forbidden")
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in sorted(dict(creative.utm or {}).items()):
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", clean_key)
            or len(clean_value) > 256
        ):
            raise GrowthPaidLiveExecutionError("creative-utm-invalid")
        query.append((clean_key, clean_value))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _meta_targeting(ad_set: GrowthPaidAdSet) -> dict[str, Any]:
    audience = dict(ad_set.audience or {})
    if set(audience) != {"countries"}:
        raise GrowthPaidLiveExecutionError("live-audience-shape-not-supported")
    countries = audience.get("countries")
    if not isinstance(countries, list) or not countries:
        raise GrowthPaidLiveExecutionError("live-target-countries-required")
    normalized = [str(item).strip().upper() for item in countries]
    if any(len(item) != 2 or not item.isalpha() for item in normalized):
        raise GrowthPaidLiveExecutionError("live-target-country-invalid")

    provider = str(ad_set.provider or "").strip().lower()
    if provider not in {"facebook", "instagram"}:
        raise GrowthPaidLiveExecutionError("live-meta-provider-not-supported")
    placements = [str(item).strip().lower() for item in (ad_set.placements or [])]
    if not placements or any(item not in _ALLOWED_PLACEMENTS for item in placements):
        raise GrowthPaidLiveExecutionError("live-placement-not-supported")
    if str(ad_set.bid_strategy or "").strip().lower() != "lowest_cost":
        raise GrowthPaidLiveExecutionError("live-bid-strategy-not-supported")

    targeting: dict[str, Any] = {
        "geo_locations": {"countries": normalized},
        "publisher_platforms": [provider],
    }
    if provider == "facebook":
        mapping = {"feed": "feed", "stories": "story"}
        targeting["facebook_positions"] = [mapping[item] for item in placements]
    else:
        mapping = {"feed": "stream", "stories": "story"}
        targeting["instagram_positions"] = [mapping[item] for item in placements]
    return targeting


def _object_story_spec(creative: GrowthPaidCreative, page_id: str) -> dict[str, Any]:
    if str(creative.format or "").strip().lower() not in _ALLOWED_CREATIVE_FORMATS:
        raise GrowthPaidLiveExecutionError("live-creative-format-not-supported")
    if creative.media_refs:
        raise GrowthPaidLiveExecutionError("live-media-asset-binding-not-supported")
    link_data: dict[str, Any] = {"link": _destination_with_utm(creative)}
    if str(creative.body or "").strip():
        link_data["message"] = str(creative.body).strip()
    if str(creative.headline or "").strip():
        link_data["name"] = str(creative.headline).strip()
    return {"page_id": page_id, "link_data": link_data}


async def _execution(
    session: AsyncSession,
    execution_id: str,
    *,
    lock: bool = False,
) -> GrowthPaidLiveExecution:
    stmt = select(GrowthPaidLiveExecution).where(
        GrowthPaidLiveExecution.id == execution_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await session.scalar(stmt)
    if row is None:
        raise GrowthPaidLiveExecutionError("live-execution-not-found")
    return row


async def _steps(
    session: AsyncSession, execution_id: str, *, lock: bool = False
) -> list[GrowthPaidLiveExecutionStep]:
    stmt = (
        select(GrowthPaidLiveExecutionStep)
        .where(GrowthPaidLiveExecutionStep.execution_id == execution_id)
        .order_by(GrowthPaidLiveExecutionStep.step_order)
    )
    if lock:
        stmt = stmt.with_for_update()
    return list(await session.scalars(stmt))


def public_execution(
    row: GrowthPaidLiveExecution,
    steps: list[GrowthPaidLiveExecutionStep],
) -> dict[str, Any]:
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "pilot_id": row.pilot_id,
        "provider": row.provider,
        "scope_ref": row.scope_ref,
        "creative_identity_ref": row.creative_identity_ref,
        "plan_version": row.plan_version,
        "plan_digest": row.plan_digest,
        "status": row.status,
        "authorized": bool(row.authorized_at and row.authorized_by_id),
        "manual_review_required": bool(row.manual_review_required),
        "provider_write_calls_completed": int(row.provider_call_count or 0),
        "spend_executed": bool(row.spend_executed),
        "automatic_execution_allowed": False,
        "raw_provider_object_ids_returned": False,
        "steps": [
            {
                "step_key": step.step_key,
                "step_order": step.step_order,
                "resource_kind": step.resource_kind,
                "operation": step.operation,
                "status": step.status,
                "attempt_count": step.attempt_count,
                "provider_object_ref": step.provider_object_ref,
                "manual_review_required": bool(step.manual_review_required),
                "last_error_code": step.last_error_code,
            }
            for step in steps
        ],
    }


async def _validate_binding(
    session: AsyncSession,
    actor: UserRecord,
    row: GrowthPaidLiveExecution,
) -> tuple[GrowthPaidCampaign, GrowthControlledPilot, dict[str, Any]]:
    validation = await live_plan.validate_prepared_plan(session, actor, row.campaign_id)
    if not validation.get("plan_valid"):
        raise GrowthPaidLiveExecutionError("prepared-live-plan-invalid")
    if validation.get("plan_digest_matches") is not True:
        raise GrowthPaidLiveExecutionError("prepared-live-plan-digest-mismatch")
    campaign = await session.get(GrowthPaidCampaign, row.campaign_id)
    pilot = await session.get(GrowthControlledPilot, row.pilot_id)
    if campaign is None or pilot is None:
        raise GrowthPaidLiveExecutionError("live-execution-binding-missing")
    plan = dict((campaign.campaign_metadata or {}).get("live_execution_plan") or {})
    if (
        str(plan.get("plan_digest") or "") != row.plan_digest
        or str(plan.get("version") or "") != row.plan_version
        or str(plan.get("pilot_id") or "") != row.pilot_id
        or str(plan.get("scope_ref") or "") != row.scope_ref
        or str(plan.get("creative_identity_ref") or "") != row.creative_identity_ref
    ):
        raise GrowthPaidLiveExecutionError("live-execution-plan-binding-changed")
    if (
        campaign.organization_id != row.organization_id
        or pilot.organization_id != row.organization_id
    ):
        raise GrowthPaidLiveExecutionError("live-execution-organization-mismatch")
    authorization = await pilots.runtime_authorization(
        session,
        pilot.id,
        provider="meta",
        scope_ref=row.scope_ref,
    )
    if not authorization.get("authorized"):
        reasons = ",".join(authorization.get("blocked_reasons") or ["denied"])
        raise GrowthPaidLiveExecutionError(f"runtime-authorization-denied:{reasons}")
    return campaign, pilot, plan


async def prepare_execution(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
) -> dict[str, Any]:
    """Create/reuse the durable execution journal without making provider calls."""
    _require_owner(actor)
    validation = await live_plan.validate_prepared_plan(session, actor, campaign_id)
    if not validation.get("plan_valid"):
        raise GrowthPaidLiveExecutionError("prepared-live-plan-invalid")
    campaign = await session.scalar(
        select(GrowthPaidCampaign)
        .where(GrowthPaidCampaign.id == campaign_id)
        .with_for_update()
    )
    if campaign is None:
        raise GrowthPaidLiveExecutionError("campaign-not-found")
    plan = dict((campaign.campaign_metadata or {}).get("live_execution_plan") or {})
    pilot_id = str(plan.get("pilot_id") or "")
    pilot = await session.get(GrowthControlledPilot, pilot_id)
    if pilot is None:
        raise GrowthPaidLiveExecutionError("pilot-not-found")
    authorization = await pilots.runtime_authorization(
        session, pilot.id, provider="meta", scope_ref=str(pilot.scope_ref or "")
    )
    if not authorization.get("authorized"):
        reasons = ",".join(authorization.get("blocked_reasons") or ["denied"])
        raise GrowthPaidLiveExecutionError(f"runtime-authorization-denied:{reasons}")

    digest = str(plan.get("plan_digest") or "")
    existing = await session.scalar(
        select(GrowthPaidLiveExecution).where(
            GrowthPaidLiveExecution.campaign_id == campaign.id,
            GrowthPaidLiveExecution.plan_digest == digest,
        )
    )
    if existing is not None:
        return public_execution(existing, await _steps(session, existing.id))

    source_ids = dict(plan.get("source_ids") or {})
    ad_set_ids = [str(item) for item in source_ids.get("ad_sets") or []]
    creative_ids = [str(item) for item in source_ids.get("creatives") or []]
    ad_ids = [str(item) for item in source_ids.get("ads") or []]
    expected_count = 1 + len(ad_set_ids) + len(creative_ids) + len(ad_ids)
    if expected_count != int(plan.get("operation_count") or 0) or expected_count <= 1:
        raise GrowthPaidLiveExecutionError("live-execution-step-count-mismatch")

    row = GrowthPaidLiveExecution(
        organization_id=campaign.organization_id,
        campaign_id=campaign.id,
        pilot_id=pilot.id,
        provider="meta",
        scope_ref=str(pilot.scope_ref or ""),
        creative_identity_ref=str(plan.get("creative_identity_ref") or ""),
        plan_version=str(plan.get("version") or ""),
        plan_digest=digest,
        status="prepared",
        manual_review_required=False,
        provider_call_count=0,
        spend_executed=False,
        automatic_execution_allowed=False,
    )
    session.add(row)
    await session.flush()
    definitions: list[tuple[str, str, str | None, str]] = [
        ("campaign", "campaign", campaign.id, "campaign.create_paused")
    ]
    definitions.extend(
        (f"adset:{item}", "ad_set", item, "adset.create_paused") for item in ad_set_ids
    )
    definitions.extend(
        (f"creative:{item}", "creative", item, "creative.create")
        for item in creative_ids
    )
    definitions.extend(
        (f"ad:{item}", "ad", item, "ad.create_paused") for item in ad_ids
    )
    for order, (step_key, kind, resource_id, operation) in enumerate(definitions):
        session.add(
            GrowthPaidLiveExecutionStep(
                execution_id=row.id,
                step_key=step_key,
                step_order=order,
                resource_kind=kind,
                resource_id=resource_id,
                operation=operation,
                status="pending",
                attempt_count=0,
                manual_review_required=False,
            )
        )
    session.add(
        AuditEvent(
            organization_id=campaign.organization_id,
            user_id=actor.id,
            action="growth.paid_campaign.live_execution_prepared",
            resource_type="growth_paid_campaign",
            resource_id=campaign.id,
            details={
                "execution_id": row.id,
                "pilot_id": pilot.id,
                "plan_digest": digest,
                "step_count": expected_count,
                "provider_call_executed": False,
                "spend_executed": False,
                "automatic_execution_allowed": False,
            },
        )
    )
    await session.flush()
    return public_execution(row, await _steps(session, row.id))


async def get_execution(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
) -> dict[str, Any]:
    _require_owner(actor)
    row = await session.scalar(
        select(GrowthPaidLiveExecution)
        .where(GrowthPaidLiveExecution.campaign_id == campaign_id)
        .order_by(GrowthPaidLiveExecution.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise GrowthPaidLiveExecutionError("live-execution-not-found")
    return public_execution(row, await _steps(session, row.id))


async def _provider_id_for(
    session: AsyncSession, execution_id: str, step_key: str
) -> str:
    step = await session.scalar(
        select(GrowthPaidLiveExecutionStep).where(
            GrowthPaidLiveExecutionStep.execution_id == execution_id,
            GrowthPaidLiveExecutionStep.step_key == step_key,
        )
    )
    if step is None or step.status != "succeeded" or not step.provider_object_id:
        raise GrowthPaidLiveExecutionError("live-execution-parent-provider-id-missing")
    return step.provider_object_id


async def _build_spec(
    session: AsyncSession,
    row: GrowthPaidLiveExecution,
    step: GrowthPaidLiveExecutionStep,
    *,
    account_id: str,
    page_id: str,
) -> adapter.MetaRequestSpec:
    if step.resource_kind == "campaign":
        campaign = await session.get(GrowthPaidCampaign, row.campaign_id)
        if campaign is None or str(campaign.objective).strip().lower() != "traffic":
            raise GrowthPaidLiveExecutionError("live-campaign-objective-not-supported")
        return adapter.build_campaign_create(account_id, name=campaign.name)
    if step.resource_kind == "ad_set":
        ad_set = await session.get(GrowthPaidAdSet, step.resource_id)
        if ad_set is None or ad_set.campaign_id != row.campaign_id:
            raise GrowthPaidLiveExecutionError("live-adset-binding-invalid")
        campaign_provider_id = await _provider_id_for(session, row.id, "campaign")
        return adapter.build_adset_create(
            account_id,
            campaign_id=campaign_provider_id,
            name=ad_set.name,
            daily_budget_minor=ad_set.daily_budget_cap_minor,
            targeting=_meta_targeting(ad_set),
        )
    if step.resource_kind == "creative":
        creative = await session.get(GrowthPaidCreative, step.resource_id)
        if creative is None or creative.campaign_id != row.campaign_id:
            raise GrowthPaidLiveExecutionError("live-creative-binding-invalid")
        return adapter.build_creative_create(
            account_id,
            name=creative.name,
            object_story_spec=_object_story_spec(creative, page_id),
        )
    if step.resource_kind == "ad":
        ad = await session.get(GrowthPaidAd, step.resource_id)
        if ad is None or ad.campaign_id != row.campaign_id:
            raise GrowthPaidLiveExecutionError("live-ad-binding-invalid")
        return adapter.build_ad_create(
            account_id,
            name=ad.name,
            adset_id=await _provider_id_for(session, row.id, f"adset:{ad.ad_set_id}"),
            creative_id=await _provider_id_for(
                session, row.id, f"creative:{ad.creative_id}"
            ),
        )
    raise GrowthPaidLiveExecutionError("live-execution-step-kind-invalid")


async def _mark_manual_review(
    session: AsyncSession,
    actor: UserRecord,
    execution_id: str,
    step_id: str,
    error_code: str,
) -> None:
    row = await _execution(session, execution_id, lock=True)
    step = await session.scalar(
        select(GrowthPaidLiveExecutionStep)
        .where(GrowthPaidLiveExecutionStep.id == step_id)
        .with_for_update()
    )
    if step is not None:
        step.status = "manual_review"
        step.manual_review_required = True
        step.last_error_code = error_code[:160]
    row.status = "manual_review"
    row.manual_review_required = True
    row.version += 1
    pilot = await session.scalar(
        select(GrowthControlledPilot)
        .where(GrowthControlledPilot.id == row.pilot_id)
        .with_for_update()
    )
    if pilot is not None:
        await pilots._auto_disarm_runtime(
            session, pilot, ["live-execution-step-ambiguous"]
        )
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=actor.id,
            action="growth.paid_campaign.live_execution_manual_review",
            resource_type="growth_paid_live_execution",
            resource_id=row.id,
            details={
                "step_key": step.step_key if step else "unknown",
                "error_code": error_code[:160],
                "provider_retry_allowed": False,
                "pilot_auto_disarmed": pilot is not None,
                "automatic_execution_allowed": False,
            },
        )
    )
    await session.flush()


async def execute_paused_plan(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
    execution_id: str,
    *,
    plan_digest: str,
    confirmation: str,
    target_opener: Callable[..., BinaryIO] = urlopen,
    page_opener: Callable[..., BinaryIO] = urlopen,
    provider_opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Execute the prepared graph exactly once, creating PAUSED Meta objects only."""
    _require_owner(actor)
    if confirmation != EXECUTE_CONFIRMATION:
        raise GrowthPaidLiveExecutionError("live-execution-confirmation-required")
    row = await _execution(session, execution_id, lock=True)
    if row.campaign_id != campaign_id or row.plan_digest != plan_digest:
        raise GrowthPaidLiveExecutionError("live-execution-request-binding-mismatch")
    if row.status == "paused_ready":
        return public_execution(row, await _steps(session, row.id))
    if row.manual_review_required or row.status in {"manual_review", "failed"}:
        raise GrowthPaidLiveExecutionError("live-execution-manual-review-required")
    existing_steps = await _steps(session, row.id, lock=True)
    if any(step.status in {"executing", "manual_review"} for step in existing_steps):
        raise GrowthPaidLiveExecutionError(
            "live-execution-incomplete-step-requires-review"
        )

    _, pilot, _ = await _validate_binding(session, actor, row)
    account_id, target_metadata = targets.resolve_scope_ref_to_raw_id(
        row.scope_ref, opener=target_opener
    )
    if target_metadata.get("currency") != pilot.currency:
        raise GrowthPaidLiveExecutionError("live-target-currency-mismatch")
    page_id, _ = pages.resolve_page_ref_to_raw_id(
        row.creative_identity_ref, opener=page_opener
    )

    if row.authorized_at is None:
        row.authorized_by_id = actor.id
        row.authorized_at = _now()
        row.status = "authorized"
        row.version += 1
        session.add(
            AuditEvent(
                organization_id=row.organization_id,
                user_id=actor.id,
                action="growth.paid_campaign.live_execution_authorized",
                resource_type="growth_paid_live_execution",
                resource_id=row.id,
                details={
                    "plan_digest": row.plan_digest,
                    "confirmation_scope": EXECUTE_CONFIRMATION,
                    "provider_call_executed": False,
                    "spend_executed": False,
                    "automatic_execution_allowed": False,
                },
            )
        )
        await session.commit()

    for original in await _steps(session, row.id):
        if original.status == "succeeded":
            continue
        step_id = original.id
        row = await _execution(session, execution_id, lock=True)
        step = await session.scalar(
            select(GrowthPaidLiveExecutionStep)
            .where(GrowthPaidLiveExecutionStep.id == step_id)
            .with_for_update()
        )
        if step is None or step.status != "pending" or step.attempt_count != 0:
            raise GrowthPaidLiveExecutionError("live-execution-step-not-retryable")
        await _validate_binding(session, actor, row)
        spec = await _build_spec(
            session, row, step, account_id=account_id, page_id=page_id
        )
        step.request_digest = _request_digest(spec)
        step.status = "executing"
        step.attempt_count = 1
        step.provider_call_started_at = _now()
        row.status = "executing"
        row.started_at = row.started_at or _now()
        row.version += 1
        session.add(
            AuditEvent(
                organization_id=row.organization_id,
                user_id=actor.id,
                action="growth.paid_campaign.live_execution_step_started",
                resource_type="growth_paid_live_execution",
                resource_id=row.id,
                details={
                    "step_key": step.step_key,
                    "operation": step.operation,
                    "request_digest": step.request_digest,
                    "request_shape": spec.safe_shape(),
                    "provider_retry_allowed": False,
                    "spend_executed": False,
                },
            )
        )
        await session.commit()

        try:
            row = await _execution(session, execution_id, lock=True)
            step = await session.scalar(
                select(GrowthPaidLiveExecutionStep)
                .where(GrowthPaidLiveExecutionStep.id == step_id)
                .with_for_update()
            )
            if step is None or step.status != "executing" or step.attempt_count != 1:
                raise GrowthPaidLiveExecutionError("live-execution-step-intent-changed")
            await _validate_binding(session, actor, row)
            spec = await _build_spec(
                session, row, step, account_id=account_id, page_id=page_id
            )
            if _request_digest(spec) != step.request_digest:
                raise GrowthPaidLiveExecutionError(
                    "live-execution-request-digest-changed"
                )
            payload = await adapter.execute_guarded_request(
                session,
                pilot_id=row.pilot_id,
                scope_ref=row.scope_ref,
                account_id=account_id,
                request_spec=spec,
                opener=provider_opener,
            )
            provider_id = _numeric_provider_id(payload, step.resource_kind)
            step.provider_object_id = provider_id
            step.provider_object_ref = _provider_ref(step.resource_kind, provider_id)
            step.status = "succeeded"
            step.provider_call_completed_at = _now()
            step.last_error_code = None
            step.manual_review_required = False
            row.provider_call_count = int(row.provider_call_count or 0) + 1
            row.version += 1
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=actor.id,
                    action="growth.paid_campaign.live_execution_step_succeeded",
                    resource_type="growth_paid_live_execution",
                    resource_id=row.id,
                    details={
                        "step_key": step.step_key,
                        "operation": step.operation,
                        "provider_object_ref": step.provider_object_ref,
                        "raw_provider_object_id_logged": False,
                        "spend_executed": False,
                    },
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            error_code = _safe_error_code(exc)
            await _mark_manual_review(session, actor, execution_id, step_id, error_code)
            await session.commit()
            raise GrowthPaidLiveExecutionError(
                f"live-execution-step-manual-review:{error_code}"
            ) from exc

    row = await _execution(session, execution_id, lock=True)
    final_steps = await _steps(session, row.id, lock=True)
    if not final_steps or any(step.status != "succeeded" for step in final_steps):
        raise GrowthPaidLiveExecutionError("live-execution-not-fully-succeeded")
    campaign = await session.scalar(
        select(GrowthPaidCampaign)
        .where(GrowthPaidCampaign.id == campaign_id)
        .with_for_update()
    )
    if campaign is None:
        raise GrowthPaidLiveExecutionError("campaign-not-found")
    row.status = "paused_ready"
    row.completed_at = _now()
    row.manual_review_required = False
    row.spend_executed = False
    row.automatic_execution_allowed = False
    row.version += 1
    campaign.status = "live_paused"
    campaign.live_provider_call = True
    campaign.live_campaign_mutation = True
    campaign.real_spend_allowed = False
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=actor.id,
            action="growth.paid_campaign.live_execution_paused_ready",
            resource_type="growth_paid_live_execution",
            resource_id=row.id,
            details={
                "step_count": len(final_steps),
                "provider_write_calls_completed": row.provider_call_count,
                "all_provider_objects_paused_by_request_contract": True,
                "spend_executed": False,
                "automatic_execution_allowed": False,
                "raw_provider_object_ids_logged": False,
            },
        )
    )
    await session.commit()
    return public_execution(row, final_steps)


async def reconcile_stale_live_executions(
    session: AsyncSession,
    *,
    stale_seconds: int = STALE_EXECUTING_AFTER_SECONDS,
) -> dict[str, int]:
    """Fail closed after a process crash: stale executing steps are never retried."""
    cutoff = _now() - timedelta(seconds=max(30, int(stale_seconds)))
    stale = list(
        await session.scalars(
            select(GrowthPaidLiveExecutionStep)
            .where(
                GrowthPaidLiveExecutionStep.status == "executing",
                GrowthPaidLiveExecutionStep.provider_call_started_at.is_not(None),
                GrowthPaidLiveExecutionStep.provider_call_started_at <= cutoff,
            )
            .with_for_update()
        )
    )
    executions_marked: set[str] = set()
    pilots_disarmed: set[str] = set()
    for step in stale:
        execution = await session.scalar(
            select(GrowthPaidLiveExecution)
            .where(GrowthPaidLiveExecution.id == step.execution_id)
            .with_for_update()
        )
        if execution is None:
            continue
        step.status = "manual_review"
        step.manual_review_required = True
        step.last_error_code = "stale-executing-step-after-process-loss"
        execution.status = "manual_review"
        execution.manual_review_required = True
        execution.version += 1
        executions_marked.add(execution.id)
        pilot = await session.scalar(
            select(GrowthControlledPilot)
            .where(GrowthControlledPilot.id == execution.pilot_id)
            .with_for_update()
        )
        if pilot is not None and pilot.live_provider_mutation_allowed:
            await pilots._auto_disarm_runtime(
                session, pilot, ["live-execution-stale-executing-step"]
            )
            pilots_disarmed.add(pilot.id)
        session.add(
            AuditEvent(
                organization_id=execution.organization_id,
                user_id=None,
                action="growth.paid_campaign.live_execution_stale_step_detected",
                resource_type="growth_paid_live_execution",
                resource_id=execution.id,
                details={
                    "step_key": step.step_key,
                    "provider_retry_allowed": False,
                    "manual_review_required": True,
                    "pilot_auto_disarmed": pilot is not None,
                    "automatic_execution_allowed": False,
                },
            )
        )
    return {
        "stale_steps": len(stale),
        "executions_marked_manual_review": len(executions_marked),
        "pilots_auto_disarmed": len(pilots_disarmed),
    }
