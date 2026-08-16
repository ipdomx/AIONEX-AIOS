"""GS-12 bridge from Owner-approved paid campaigns to a fail-closed live plan.

This module never calls a provider and never authorizes spend. It only binds an
approved internal campaign to an already verified controlled pilot, checks that
campaign budgets fit the pilot safety envelope, and stores an immutable digest
of the current campaign configuration. Provider execution must revalidate this
plan and pass the independent GS-12 runtime authorization gate later.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

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
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_paid_campaigns as paid

PLAN_VERSION = "gs12-paid-live-plan-v1"
META_PROVIDERS = {"facebook", "instagram"}
_PAGE_REF_RE = re.compile(r"^pageref://meta/sha256/[0-9a-f]{64}$")


class GrowthPaidLivePlanError(RuntimeError):
    """Fail-closed paid-campaign live-plan validation error."""


def _require_owner(actor: UserRecord) -> None:
    if actor.role != "Super Owner":
        raise GrowthPaidLivePlanError("super-owner-required")


def _safe_page_ref(value: str | None) -> str | None:
    clean = str(value or "").strip().lower()
    if not clean:
        return None
    if _PAGE_REF_RE.fullmatch(clean) is None:
        raise GrowthPaidLivePlanError("meta-page-reference-invalid")
    return clean


async def _components(
    session: AsyncSession, campaign_id: str
) -> tuple[list[GrowthPaidAdSet], list[GrowthPaidCreative], list[GrowthPaidAd]]:
    ad_sets = list(
        await session.scalars(
            select(GrowthPaidAdSet)
            .where(GrowthPaidAdSet.campaign_id == campaign_id)
            .order_by(GrowthPaidAdSet.id)
        )
    )
    creatives = list(
        await session.scalars(
            select(GrowthPaidCreative)
            .where(GrowthPaidCreative.campaign_id == campaign_id)
            .order_by(GrowthPaidCreative.id)
        )
    )
    ads = list(
        await session.scalars(
            select(GrowthPaidAd)
            .where(GrowthPaidAd.campaign_id == campaign_id)
            .order_by(GrowthPaidAd.id)
        )
    )
    return ad_sets, creatives, ads


def _effective_stop_loss(
    campaign: GrowthPaidCampaign, pilot: GrowthControlledPilot
) -> dict[str, Any]:
    user_policy = dict(campaign.stop_loss_policy or {})
    user_max_cpa = int(user_policy.get("max_cpa_minor") or 0)
    user_min_roas = float(user_policy.get("min_roas") or 0.0)
    pilot_max_cpa = int(pilot.max_cpa_minor or 0)
    pilot_min_roas = float(pilot.min_roas or 0.0)
    effective_max_cpa = (
        min(user_max_cpa, pilot_max_cpa)
        if user_max_cpa > 0 and pilot_max_cpa > 0
        else max(user_max_cpa, pilot_max_cpa)
    )
    effective_min_roas = max(user_min_roas, pilot_min_roas)
    return {
        "user_max_cpa_minor": user_max_cpa or None,
        "pilot_max_cpa_minor": pilot_max_cpa or None,
        "effective_max_cpa_minor": effective_max_cpa or None,
        "user_min_roas": user_min_roas or None,
        "pilot_min_roas": pilot_min_roas or None,
        "effective_min_roas": effective_min_roas or None,
    }


def _normalized_plan_source(
    campaign: GrowthPaidCampaign,
    pilot: GrowthControlledPilot,
    ad_sets: list[GrowthPaidAdSet],
    creatives: list[GrowthPaidCreative],
    ads: list[GrowthPaidAd],
    page_ref: str,
) -> dict[str, Any]:
    return {
        "plan_version": PLAN_VERSION,
        "campaign": {
            "id": campaign.id,
            "organization_id": campaign.organization_id,
            "name": campaign.name,
            "objective": campaign.objective,
            "currency": campaign.currency,
            "total_budget_minor": campaign.total_budget_minor,
            "daily_budget_cap_minor": campaign.daily_budget_cap_minor,
            "stop_loss_policy": dict(campaign.stop_loss_policy or {}),
            "approval_status": campaign.approval_status,
            "approved_by_id": campaign.approved_by_id,
            "approved_at": (
                campaign.approved_at.isoformat() if campaign.approved_at else None
            ),
        },
        "pilot": {
            "id": pilot.id,
            "organization_id": pilot.organization_id,
            "provider": pilot.provider,
            "provider_scope": pilot.provider_scope,
            "scope_ref": pilot.scope_ref,
            "currency": pilot.currency,
            "max_total_budget_minor": pilot.max_total_budget_minor,
            "max_daily_budget_minor": pilot.max_daily_budget_minor,
            "max_cpa_minor": pilot.max_cpa_minor,
            "min_roas": pilot.min_roas,
        },
        "creative_identity_ref": page_ref,
        "ad_sets": [
            {
                "id": row.id,
                "version": row.version,
                "name": row.name,
                "provider": row.provider,
                "audience": dict(row.audience or {}),
                "placements": list(row.placements or []),
                "bid_strategy": row.bid_strategy,
                "daily_budget_cap_minor": row.daily_budget_cap_minor,
            }
            for row in ad_sets
        ],
        "creatives": [
            {
                "id": row.id,
                "version": row.version,
                "name": row.name,
                "format": row.format,
                "headline": row.headline,
                "body": row.body,
                "destination_url": row.destination_url,
                "utm": dict(row.utm or {}),
            }
            for row in creatives
        ],
        "ads": [
            {
                "id": row.id,
                "version": row.version,
                "name": row.name,
                "ad_set_id": row.ad_set_id,
                "creative_id": row.creative_id,
            }
            for row in ads
        ],
    }


def _digest(source: dict[str, Any]) -> str:
    raw = json.dumps(source, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


async def evaluate_live_plan(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
    pilot_id: str,
    *,
    creative_identity_ref: str | None = None,
) -> dict[str, Any]:
    """Evaluate campaign-to-pilot plan readiness without writing or provider calls."""
    _require_owner(actor)
    campaign = await session.get(GrowthPaidCampaign, campaign_id)
    pilot = await session.get(GrowthControlledPilot, pilot_id)
    if campaign is None:
        raise GrowthPaidLivePlanError("campaign-not-found")
    if pilot is None:
        raise GrowthPaidLivePlanError("pilot-not-found")

    page_ref = _safe_page_ref(creative_identity_ref)
    ad_sets, creatives, ads = await _components(session, campaign.id)
    ad_set_by_id = {row.id: row for row in ad_sets}
    creative_by_id = {row.id: row for row in creatives}
    blockers: list[str] = []

    owner_approval_gate = bool(
        campaign.approval_status == "approved"
        and campaign.approved_by_id
        and campaign.approved_at
    )
    if not owner_approval_gate:
        blockers.append("campaign-owner-approval-missing")

    campaign_safe_state_gate = not any(
        (
            campaign.real_spend_allowed,
            campaign.live_provider_call,
            campaign.live_campaign_mutation,
            campaign.automatic_budget_increase_allowed,
        )
    )
    if not campaign_safe_state_gate:
        blockers.append("campaign-live-state-already-mutated")

    organization_gate = bool(
        pilot.organization_id and pilot.organization_id == campaign.organization_id
    )
    if not organization_gate:
        blockers.append("campaign-pilot-organization-mismatch")

    pilot_scope_gate = bool(
        pilot.mode == "live_spend"
        and pilot.provider == "meta"
        and pilot.provider_scope == "managed_ad_account"
        and pilot.scope_ref
    )
    if not pilot_scope_gate:
        blockers.append("pilot-not-meta-managed-live-spend")

    readiness = await pilots.readiness(
        session, actor, pilot.id, require_launch_authorization=False
    )
    for gate_name, reason in (
        ("provider_gate", "provider-write-capability-unverified"),
        ("execution_adapter_gate", "provider-live-execution-adapter-unverified"),
        ("budget_gate", "pilot-budget-controls-missing"),
        ("stop_loss_gate", "pilot-stop-loss-controls-missing"),
        ("expiry_gate", "pilot-expired-or-expiry-missing"),
    ):
        if not readiness.get(gate_name):
            blockers.append(reason)

    currency_gate = bool(
        campaign.currency and pilot.currency and campaign.currency == pilot.currency
    )
    if not currency_gate:
        blockers.append("campaign-pilot-currency-mismatch")

    budget_gate = bool(
        pilot.max_total_budget_minor
        and pilot.max_daily_budget_minor
        and campaign.total_budget_minor <= pilot.max_total_budget_minor
        and campaign.daily_budget_cap_minor <= pilot.max_daily_budget_minor
    )
    if not budget_gate:
        blockers.append("campaign-budget-exceeds-pilot-cap")

    objective_gate = campaign.objective.strip().lower() == "traffic"
    if not objective_gate:
        blockers.append("meta-live-objective-not-supported")

    components_gate = bool(ad_sets and creatives and ads)
    if not components_gate:
        blockers.append("campaign-live-components-missing")

    meta_provider_gate = bool(ad_sets) and all(
        row.provider in META_PROVIDERS for row in ad_sets
    )
    if not meta_provider_gate:
        blockers.append("campaign-provider-not-meta")

    aggregate_daily = sum(int(row.daily_budget_cap_minor) for row in ad_sets)
    aggregate_budget_gate = bool(
        ad_sets
        and aggregate_daily <= campaign.daily_budget_cap_minor
        and pilot.max_daily_budget_minor
        and aggregate_daily <= pilot.max_daily_budget_minor
    )
    if not aggregate_budget_gate:
        blockers.append("campaign-adset-aggregate-budget-exceeds-cap")

    reference_gate = bool(ads) and all(
        ad.ad_set_id in ad_set_by_id and ad.creative_id in creative_by_id for ad in ads
    )
    if not reference_gate:
        blockers.append("campaign-component-reference-invalid")

    referenced_creative_ids = {ad.creative_id for ad in ads}
    destination_gate = bool(referenced_creative_ids) and all(
        bool(creative_by_id[item].destination_url)
        for item in referenced_creative_ids
        if item in creative_by_id
    )
    if not destination_gate:
        blockers.append("campaign-destination-url-required-for-meta-live")

    creative_identity_gate = page_ref is not None
    if not creative_identity_gate:
        blockers.append("meta-page-binding-missing")

    blockers = list(dict.fromkeys(blockers))
    stop_loss = _effective_stop_loss(campaign, pilot)
    operation_count = (
        1 + len(ad_sets) + len(referenced_creative_ids) + len(ads)
        if components_gate
        else 0
    )
    return {
        "campaign_id": campaign.id,
        "pilot_id": pilot.id,
        "plan_version": PLAN_VERSION,
        "plan_compilable": not blockers,
        "blocked_reasons": blockers,
        "owner_approval_gate": owner_approval_gate,
        "organization_gate": organization_gate,
        "pilot_scope_gate": pilot_scope_gate,
        "provider_gate": bool(readiness.get("provider_gate")),
        "execution_adapter_gate": bool(readiness.get("execution_adapter_gate")),
        "currency_gate": currency_gate,
        "budget_gate": budget_gate,
        "stop_loss_gate": bool(readiness.get("stop_loss_gate")),
        "objective_gate": objective_gate,
        "components_gate": components_gate,
        "meta_provider_gate": meta_provider_gate,
        "aggregate_budget_gate": aggregate_budget_gate,
        "reference_gate": reference_gate,
        "destination_gate": destination_gate,
        "creative_identity_gate": creative_identity_gate,
        "creative_identity_ref": page_ref,
        "effective_stop_loss": stop_loss,
        "aggregate_adset_daily_budget_minor": aggregate_daily,
        "operation_count": operation_count,
        "live_legal_gate": bool(readiness.get("legal_gate")),
        "launch_gate": bool(readiness.get("launch_gate")),
        "runtime_authorization_required": True,
        "live_execution_authorized": False,
        "provider_call_executed": False,
        "spend_executed": False,
        "automatic_execution_allowed": False,
    }


async def prepare_live_plan(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
    pilot_id: str,
    *,
    creative_identity_ref: str,
) -> dict[str, Any]:
    """Persist a digest-bound plan only when static campaign/pilot gates are green."""
    _require_owner(actor)
    campaign = await session.scalar(
        select(GrowthPaidCampaign)
        .where(GrowthPaidCampaign.id == campaign_id)
        .with_for_update()
    )
    pilot = await session.scalar(
        select(GrowthControlledPilot)
        .where(GrowthControlledPilot.id == pilot_id)
        .with_for_update()
    )
    if campaign is None:
        raise GrowthPaidLivePlanError("campaign-not-found")
    if pilot is None:
        raise GrowthPaidLivePlanError("pilot-not-found")

    # Re-evaluate only after both mutable rows are locked. The plan remains
    # non-authorizing, but this prevents a stale static snapshot from being persisted.
    evaluation = await evaluate_live_plan(
        session,
        actor,
        campaign_id,
        pilot_id,
        creative_identity_ref=creative_identity_ref,
    )
    if not evaluation["plan_compilable"]:
        raise GrowthPaidLivePlanError(
            "live-plan-not-compilable:" + ",".join(evaluation["blocked_reasons"])
        )
    ad_sets, creatives, ads = await _components(session, campaign.id)
    page_ref = _safe_page_ref(creative_identity_ref)
    assert page_ref is not None
    source = _normalized_plan_source(campaign, pilot, ad_sets, creatives, ads, page_ref)
    digest = _digest(source)
    referenced_creative_ids = sorted({row.creative_id for row in ads})
    plan = {
        "version": PLAN_VERSION,
        "pilot_id": pilot.id,
        "scope_ref": pilot.scope_ref,
        "creative_identity_ref": page_ref,
        "plan_digest": digest,
        "source_versions": {
            "campaign": campaign.version,
            "ad_sets": {row.id: row.version for row in ad_sets},
            "creatives": {row.id: row.version for row in creatives},
            "ads": {row.id: row.version for row in ads},
        },
        "source_ids": {
            "ad_sets": [row.id for row in ad_sets],
            "creatives": referenced_creative_ids,
            "ads": [row.id for row in ads],
        },
        "operation_count": evaluation["operation_count"],
        "effective_stop_loss": evaluation["effective_stop_loss"],
        "aggregate_adset_daily_budget_minor": evaluation[
            "aggregate_adset_daily_budget_minor"
        ],
        "required_initial_status": "PAUSED",
        "runtime_guard_required": True,
        "live_legal_gate_at_plan_time": evaluation["live_legal_gate"],
        "launch_gate_at_plan_time": evaluation["launch_gate"],
        "provider_call_executed": False,
        "spend_executed": False,
        "automatic_execution_allowed": False,
        "live_execution_authorized": False,
    }
    metadata = dict(campaign.campaign_metadata or {})
    metadata["live_execution_plan"] = plan
    campaign.campaign_metadata = paid._safe_campaign_json(metadata, "metadata")

    session.add(
        AuditEvent(
            organization_id=campaign.organization_id,
            user_id=actor.id,
            action="growth.paid_campaign.live_plan_prepared",
            resource_type="growth_paid_campaign",
            resource_id=campaign.id,
            details={
                "pilot_id": pilot.id,
                "plan_version": PLAN_VERSION,
                "plan_digest": digest,
                "operation_count": evaluation["operation_count"],
                "provider_call_executed": False,
                "spend_executed": False,
                "automatic_execution_allowed": False,
            },
        )
    )
    await session.flush()
    return {
        **evaluation,
        "plan_compilable": True,
        "plan_digest": digest,
        "plan_persisted": True,
        "live_execution_authorized": False,
        "provider_call_executed": False,
        "spend_executed": False,
        "automatic_execution_allowed": False,
    }


async def validate_prepared_plan(
    session: AsyncSession,
    actor: UserRecord,
    campaign_id: str,
) -> dict[str, Any]:
    """Recompute the current source digest; any post-plan mutation invalidates it."""
    _require_owner(actor)
    campaign = await session.get(GrowthPaidCampaign, campaign_id)
    if campaign is None:
        raise GrowthPaidLivePlanError("campaign-not-found")
    plan = dict((campaign.campaign_metadata or {}).get("live_execution_plan") or {})
    if plan.get("version") != PLAN_VERSION or not plan.get("plan_digest"):
        raise GrowthPaidLivePlanError("live-plan-missing")
    pilot_id = str(plan.get("pilot_id") or "")
    page_ref = _safe_page_ref(str(plan.get("creative_identity_ref") or ""))
    pilot = await session.get(GrowthControlledPilot, pilot_id)
    if pilot is None or page_ref is None:
        raise GrowthPaidLivePlanError("live-plan-binding-invalid")
    ad_sets, creatives, ads = await _components(session, campaign.id)
    current_digest = _digest(
        _normalized_plan_source(campaign, pilot, ad_sets, creatives, ads, page_ref)
    )
    digest_matches = current_digest == plan["plan_digest"]
    evaluation = await evaluate_live_plan(
        session,
        actor,
        campaign.id,
        pilot.id,
        creative_identity_ref=page_ref,
    )
    plan_valid = bool(digest_matches and evaluation["plan_compilable"])
    return {
        **evaluation,
        "plan_valid": plan_valid,
        "plan_digest_matches": digest_matches,
        "runtime_authorization_required": True,
        "live_execution_authorized": False,
        "provider_call_executed": False,
        "spend_executed": False,
        "automatic_execution_allowed": False,
    }
