from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthPaidAd,
    GrowthPaidAdSet,
    GrowthPaidCampaign,
    GrowthPaidCreative,
    GrowthPaidDecision,
    GrowthPaidExperiment,
    GrowthPaidLaunchSimulation,
)
from app.services import growth_access


class GrowthPaidCampaignError(Exception):
    """GS-08 validation/access error."""


MAX_MONEY_MINOR = 9_000_000_000_000_000_000
MAX_ROAS = 1_000_000.0

SAFE_PROVIDERS = {
    "facebook",
    "instagram",
    "linkedin",
    "tiktok",
    "youtube",
    "x",
    "snapchat",
    "pinterest",
    "reddit",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(raw).hexdigest()


async def _require(session: AsyncSession, actor: UserRecord) -> None:
    decision = await growth_access.effective_access(session, actor, "ads.manage")
    if not decision.allowed:
        raise GrowthPaidCampaignError(f"access-denied:{decision.reason}")


def _safe_budget(total: int, daily: int) -> None:
    if total <= 0 or daily <= 0:
        raise GrowthPaidCampaignError("budget-must-be-positive")
    if total > MAX_MONEY_MINOR or daily > MAX_MONEY_MINOR:
        raise GrowthPaidCampaignError("budget-too-large")
    if daily > total:
        raise GrowthPaidCampaignError("daily-cap-exceeds-total-budget")


def _safe_policy(policy: dict[str, Any]) -> dict[str, Any]:
    max_cpa = max(0, int(policy.get("max_cpa_minor", 0)))
    max_daily = max(0, int(policy.get("max_daily_spend_minor", 0)))
    max_total = max(0, int(policy.get("max_total_spend_minor", 0)))
    min_roas = float(policy.get("min_roas", 0.0))
    if any(value > MAX_MONEY_MINOR for value in (max_cpa, max_daily, max_total)):
        raise GrowthPaidCampaignError("stop-loss-money-too-large")
    if not math.isfinite(min_roas) or min_roas < 0 or min_roas > MAX_ROAS:
        raise GrowthPaidCampaignError("min-roas-invalid")
    return {
        "max_cpa_minor": max_cpa,
        "min_roas": min_roas,
        "max_daily_spend_minor": max_daily,
        "max_total_spend_minor": max_total,
    }


def _safe_destination_url(value: object) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    if len(clean) > 2048:
        raise GrowthPaidCampaignError("destination-url-too-long")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GrowthPaidCampaignError("destination-url-invalid")
    if parsed.username or parsed.password:
        raise GrowthPaidCampaignError("destination-url-credentials-forbidden")
    return clean


def _budget_assessment(
    campaign: GrowthPaidCampaign, metrics: dict[str, Any], action: str
) -> dict[str, Any]:
    """Advisory-only assessment of the user's chosen budget. Never mutates it."""
    cpa = metrics.get("cpa_minor")
    roas = float(metrics.get("roas") or 0.0)
    conversions = int(metrics.get("conversions") or 0)
    policy = dict(campaign.stop_loss_policy or {})
    max_cpa = int(policy.get("max_cpa_minor") or 0)
    min_roas = float(policy.get("min_roas") or 0.0)

    if action == "pause":
        recommendation = "decrease_or_rework"
        rationale = "simulated-performance-below-user-thresholds"
    elif action == "scale_candidate":
        recommendation = "increase_candidate"
        rationale = "simulated-positive-unit-economics"
    elif conversions > 0:
        recommendation = "keep_and_measure"
        rationale = "results-present-but-confidence-insufficient-to-scale"
    else:
        recommendation = "rework_before_increase"
        rationale = "no-simulated-conversions"

    return {
        "recommendation": recommendation,
        "rationale": rationale,
        "user_total_budget_minor": campaign.total_budget_minor,
        "user_daily_budget_minor": campaign.daily_budget_cap_minor,
        "observed_cpa_minor": cpa,
        "observed_roas": roas,
        "user_max_cpa_minor": max_cpa or None,
        "user_min_roas": min_roas or None,
        "owner_approval_required": True,
        "advisory_only": True,
        "analysis_basis": "synthetic_prelaunch_v2",
        "real_performance_data_used": False,
        "guaranteed_results": False,
        "budget_mutated": False,
        "automatic_execution_allowed": False,
    }


async def create_campaign(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthPaidCampaign:
    await _require(session, actor)
    total = int(payload["total_budget_minor"])
    daily = int(payload["daily_budget_cap_minor"])
    _safe_budget(total, daily)
    row = GrowthPaidCampaign(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        brief_id=payload.get("brief_id"),
        name=str(payload["name"]).strip(),
        objective=str(payload["objective"]).strip(),
        currency=str(payload.get("currency", "USD")).upper()[:3],
        total_budget_minor=total,
        daily_budget_cap_minor=daily,
        simulated_spend_minor=0,
        status="draft",
        approval_status="not_requested",
        stop_loss_policy=_safe_policy(dict(payload.get("stop_loss_policy") or {})),
        campaign_metadata=dict(payload.get("metadata") or {}),
        real_spend_allowed=False,
        live_provider_call=False,
        live_campaign_mutation=False,
        automatic_budget_increase_allowed=False,
    )
    session.add(row)
    await session.flush()
    return row


async def prepare_and_simulate_campaign(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> dict[str, Any]:
    """Atomically prepare one paid campaign and run advisory-only AIOS simulation."""
    total = int(payload["total_budget_minor"])
    daily = int(payload["daily_budget_cap_minor"])
    max_cpa = int(payload.get("max_cpa_minor") or 0)
    min_roas = float(payload.get("min_roas") or 0.0)
    campaign = await create_campaign(
        session,
        actor,
        {
            "name": payload["campaign_name"],
            "objective": payload["objective"],
            "currency": payload.get("currency", "USD"),
            "total_budget_minor": total,
            "daily_budget_cap_minor": daily,
            "stop_loss_policy": {
                "max_cpa_minor": max_cpa,
                "min_roas": min_roas,
            },
            "metadata": {
                "prepared_by": "user-campaign-advisor",
                "aios_advice_only": True,
                "budget_mutation_allowed": False,
            },
        },
    )
    if max_cpa and max_cpa > total:
        raise GrowthPaidCampaignError("max-cpa-exceeds-total-budget")

    countries = [
        str(item).strip().upper() for item in payload.get("target_countries", [])
    ]
    if not countries or any(len(item) != 2 or not item.isalpha() for item in countries):
        raise GrowthPaidCampaignError("target-countries-invalid")
    placements = [
        str(item).strip().lower()
        for item in payload.get("placements", [])
        if str(item).strip()
    ]
    if not placements:
        placements = ["feed"]

    ad_set = await add_ad_set(
        session,
        actor,
        campaign.id,
        {
            "name": payload.get("ad_set_name") or f"{campaign.name} Ad Set",
            "provider": payload.get("provider", "instagram"),
            "audience": {"countries": countries},
            "placements": placements,
            "bid_strategy": payload.get("bid_strategy", "lowest_cost"),
            "daily_budget_cap_minor": daily,
        },
    )
    creative = await add_creative(
        session,
        actor,
        campaign.id,
        {
            "name": payload.get("creative_name") or f"{campaign.name} Creative",
            "format": payload.get("creative_format", "image"),
            "headline": payload.get("headline", ""),
            "body": payload.get("body", ""),
            "destination_url": _safe_destination_url(payload.get("destination_url")),
            "utm": dict(payload.get("utm") or {}),
            "approved": False,
        },
    )
    ad = await add_ad(
        session,
        actor,
        campaign.id,
        {
            "name": payload.get("ad_name") or f"{campaign.name} Ad",
            "ad_set_id": ad_set.id,
            "creative_id": creative.id,
        },
    )
    simulation, decision = await simulate_launch(
        session, actor, campaign.id, days=int(payload.get("days") or 3)
    )
    return {
        "campaign": campaign,
        "ad_set": ad_set,
        "creative": creative,
        "ad": ad,
        "simulation": simulation,
        "decision": decision,
    }


async def approve_campaign(
    session: AsyncSession, actor: UserRecord, campaign_id: str
) -> GrowthPaidCampaign:
    if actor.role != "Super Owner":
        raise GrowthPaidCampaignError("super-owner-approval-required")
    row = await session.get(GrowthPaidCampaign, campaign_id)
    if row is None:
        raise GrowthPaidCampaignError("campaign-not-found")
    row.approval_status = "approved"
    row.approved_by_id = actor.id
    row.approved_at = _now()
    row.status = "approved"
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=actor.id,
            action="growth.paid_campaign.owner_approved",
            resource_type="growth_paid_campaign",
            resource_id=row.id,
            details={
                "owner_approval_required": True,
                "user_budget_preserved": True,
                "automatic_execution_allowed": False,
            },
        )
    )
    await session.flush()
    return row


async def add_ad_set(
    session: AsyncSession, actor: UserRecord, campaign_id: str, payload: dict[str, Any]
) -> GrowthPaidAdSet:
    await _require(session, actor)
    campaign = await _campaign(session, actor, campaign_id)
    provider = str(payload["provider"]).lower()
    if provider not in SAFE_PROVIDERS:
        raise GrowthPaidCampaignError("unsupported-provider")
    daily = int(payload["daily_budget_cap_minor"])
    if daily <= 0 or daily > campaign.daily_budget_cap_minor:
        raise GrowthPaidCampaignError("adset-daily-cap-invalid")
    row = GrowthPaidAdSet(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        name=str(payload["name"]).strip(),
        provider=provider,
        audience=dict(payload.get("audience") or {}),
        placements=list(payload.get("placements") or []),
        bid_strategy=str(payload.get("bid_strategy", "lowest_cost")),
        daily_budget_cap_minor=daily,
        simulated_spend_minor=0,
        status="draft",
    )
    session.add(row)
    await session.flush()
    return row


async def add_creative(
    session: AsyncSession, actor: UserRecord, campaign_id: str, payload: dict[str, Any]
) -> GrowthPaidCreative:
    await _require(session, actor)
    campaign = await _campaign(session, actor, campaign_id)
    row = GrowthPaidCreative(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        name=str(payload["name"]).strip(),
        format=str(payload.get("format", "image")),
        headline=str(payload.get("headline", "")),
        body=str(payload.get("body", "")),
        media_refs=list(payload.get("media_refs") or []),
        destination_url=_safe_destination_url(payload.get("destination_url")),
        utm=dict(payload.get("utm") or {}),
        approval_status="approved" if payload.get("approved") else "not_requested",
        status="ready",
    )
    session.add(row)
    await session.flush()
    return row


async def add_ad(
    session: AsyncSession, actor: UserRecord, campaign_id: str, payload: dict[str, Any]
) -> GrowthPaidAd:
    await _require(session, actor)
    campaign = await _campaign(session, actor, campaign_id)
    ad_set = await session.get(GrowthPaidAdSet, str(payload["ad_set_id"]))
    creative = await session.get(GrowthPaidCreative, str(payload["creative_id"]))
    if (
        not ad_set
        or not creative
        or ad_set.campaign_id != campaign.id
        or creative.campaign_id != campaign.id
    ):
        raise GrowthPaidCampaignError("campaign-resource-mismatch")
    row = GrowthPaidAd(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        ad_set_id=ad_set.id,
        creative_id=creative.id,
        name=str(payload["name"]).strip(),
        status="ready",
    )
    session.add(row)
    await session.flush()
    return row


async def create_experiment(
    session: AsyncSession, actor: UserRecord, campaign_id: str, payload: dict[str, Any]
) -> GrowthPaidExperiment:
    await _require(session, actor)
    campaign = await _campaign(session, actor, campaign_id)
    ad_ids = [str(x) for x in payload.get("variant_ad_ids") or []]
    if len(ad_ids) < 2:
        raise GrowthPaidCampaignError("experiment-needs-two-variants")
    for ad_id in ad_ids:
        ad = await session.get(GrowthPaidAd, ad_id)
        if not ad or ad.campaign_id != campaign.id:
            raise GrowthPaidCampaignError("experiment-ad-mismatch")
    allocation = {ad_id: round(1 / len(ad_ids), 6) for ad_id in sorted(ad_ids)}
    row = GrowthPaidExperiment(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        name=str(payload["name"]).strip(),
        hypothesis=str(payload["hypothesis"]).strip(),
        variant_ad_ids=sorted(ad_ids),
        allocation=allocation,
        primary_metric=str(payload.get("primary_metric", "conversion_rate")),
        status="ready",
        result={},
    )
    session.add(row)
    await session.flush()
    return row


async def simulate_launch(
    session: AsyncSession, actor: UserRecord, campaign_id: str, *, days: int = 3
) -> tuple[GrowthPaidLaunchSimulation, GrowthPaidDecision]:
    await _require(session, actor)
    campaign = await _campaign(session, actor, campaign_id)
    # Simulation/advice is intentionally available before owner approval.
    # Approval is a launch gate, not a prerequisite for AIOS analysis.
    ads = (
        await session.scalars(
            select(GrowthPaidAd)
            .where(GrowthPaidAd.campaign_id == campaign.id)
            .order_by(GrowthPaidAd.id)
        )
    ).all()
    if not ads:
        raise GrowthPaidCampaignError("campaign-has-no-ads")
    days = max(1, min(int(days), 30))
    configuration_ads: list[dict[str, Any]] = []
    for ad in ads:
        ad_set = await session.get(GrowthPaidAdSet, ad.ad_set_id)
        creative = await session.get(GrowthPaidCreative, ad.creative_id)
        configuration_ads.append(
            {
                "provider": ad_set.provider if ad_set else "unknown",
                "audience": dict(ad_set.audience or {}) if ad_set else {},
                "placements": sorted(ad_set.placements or []) if ad_set else [],
                "bid_strategy": ad_set.bid_strategy if ad_set else "",
                "adset_daily_budget_minor": (
                    ad_set.daily_budget_cap_minor if ad_set else 0
                ),
                "creative_format": creative.format if creative else "",
                "headline": creative.headline if creative else "",
                "body": creative.body if creative else "",
                "has_destination_url": bool(creative and creative.destination_url),
            }
        )
    seed = _seed(
        {
            "analysis_basis": "synthetic_prelaunch_v2",
            "objective": campaign.objective,
            "currency": campaign.currency,
            "total_budget_minor": campaign.total_budget_minor,
            "daily_budget_cap_minor": campaign.daily_budget_cap_minor,
            "stop_loss_policy": dict(campaign.stop_loss_policy or {}),
            "days": days,
            "ads": configuration_ads,
        }
    )
    total_cap = min(campaign.total_budget_minor, campaign.daily_budget_cap_minor * days)
    simulated_spend = min(
        total_cap, max(1, int(total_cap * (0.55 + (int(seed[:4], 16) % 30) / 100)))
    )
    impressions = simulated_spend * (8 + int(seed[4:6], 16) % 10)
    ctr = 0.008 + (int(seed[6:8], 16) % 24) / 1000
    clicks = int(impressions * ctr)
    conv_rate = 0.015 + (int(seed[8:10], 16) % 80) / 1000
    conversions = int(clicks * conv_rate)
    revenue = conversions * (5000 + (int(seed[10:12], 16) % 5000))
    cpa = int(simulated_spend / conversions) if conversions else None
    roas = round(revenue / simulated_spend, 4) if simulated_spend else 0.0
    metrics: dict[str, Any] = {
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "simulated_spend_minor": simulated_spend,
        "simulated_revenue_minor": revenue,
        "ctr": round(ctr, 4),
        "conversion_rate": round(conv_rate, 4),
        "cpa_minor": cpa,
        "roas": roas,
        "analysis_basis": "synthetic_prelaunch_v2",
        "real_performance_data_used": False,
        "guaranteed_results": False,
        "provider_call_executed": False,
        "real_spend_executed": False,
    }
    # AIOS advises on the user's chosen budget; it never rewrites it automatically.
    policy = campaign.stop_loss_policy or {}
    reasons: list[str] = []
    stop = False
    if (
        policy.get("max_cpa_minor")
        and cpa is not None
        and cpa > int(policy["max_cpa_minor"])
    ):
        stop = True
        reasons.append("cpa-stop-loss")
    if policy.get("min_roas") and roas < float(policy["min_roas"]):
        stop = True
        reasons.append("roas-stop-loss")
    if simulated_spend > campaign.total_budget_minor:
        stop = True
        reasons.append("total-budget-cap")
    if stop:
        action = "pause"
    elif roas >= max(2.0, float(policy.get("min_roas") or 0.0)) and conversions > 0:
        action = "scale_candidate"
        reasons.append("positive-unit-economics")
    elif conversions > 0:
        action = "hold"
        reasons.append("insufficient-confidence-to-scale")
    else:
        action = "iterate"
        reasons.append("no-conversions")
    metrics["budget_assessment"] = _budget_assessment(campaign, metrics, action)
    campaign_metadata = dict(campaign.campaign_metadata or {})
    campaign_metadata["latest_budget_assessment"] = metrics["budget_assessment"]
    campaign.campaign_metadata = campaign_metadata
    sim = GrowthPaidLaunchSimulation(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        requested_by_id=actor.id,
        seed=seed,
        simulated_days=days,
        simulated_spend_minor=simulated_spend,
        result=metrics,
        reason_codes=reasons,
        real_spend_allowed=False,
        live_provider_call=False,
        live_campaign_mutation=False,
    )
    session.add(sim)
    await session.flush()
    decision = GrowthPaidDecision(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        simulation_id=sim.id,
        action=action,
        reason_codes=reasons,
        metrics=metrics,
        approval_required=True,
        automatic_execution_allowed=False,
        real_spend_allowed=False,
    )
    session.add(decision)
    campaign.simulated_spend_minor = simulated_spend
    if campaign.approval_status != "approved":
        campaign.approval_status = "pending_owner"
        campaign.status = "awaiting_owner_approval"
    await session.flush()
    return sim, decision


async def _campaign(
    session: AsyncSession, actor: UserRecord, campaign_id: str
) -> GrowthPaidCampaign:
    row = await session.get(GrowthPaidCampaign, campaign_id)
    if not row or row.organization_id != actor.organization_id:
        raise GrowthPaidCampaignError("campaign-not-found")
    return row


def public_campaign(row: GrowthPaidCampaign) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "objective": row.objective,
        "status": row.status,
        "approval_status": row.approval_status,
        "owner_approval_required": True,
        "aios_advice_only": True,
        "user_budget_preserved": True,
        "currency": row.currency,
        "total_budget_minor": row.total_budget_minor,
        "daily_budget_cap_minor": row.daily_budget_cap_minor,
        "simulated_spend_minor": row.simulated_spend_minor,
        "real_spend_allowed": False,
        "live_provider_call": False,
        "live_campaign_mutation": False,
        "automatic_budget_increase_allowed": False,
    }
