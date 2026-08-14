"""GS-02 deterministic campaign intelligence and simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AuditEvent, GrowthCampaignBrief, GrowthCampaignSimulation
from app.services import growth_access

REAL_SPEND_ALLOWED = False
SCENARIOS = ("conservative", "expected", "upside")


class GrowthCampaignError(RuntimeError):
    """Fail-closed GS-02 campaign intelligence error."""


@dataclass(frozen=True)
class SimulationResult:
    scenario: str
    confidence: float
    reach_min: int
    reach_max: int
    clicks_min: int
    clicks_max: int
    conversions_min: int
    conversions_max: int
    cpa_minor: int | None
    reason_codes: list[str]
    assumptions: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "confidence": self.confidence,
            "estimated_reach_min": self.reach_min,
            "estimated_reach_max": self.reach_max,
            "estimated_clicks_min": self.clicks_min,
            "estimated_clicks_max": self.clicks_max,
            "estimated_conversions_min": self.conversions_min,
            "estimated_conversions_max": self.conversions_max,
            "estimated_cpa_minor": self.cpa_minor,
            "reason_codes": self.reason_codes,
            "assumptions": self.assumptions,
            "real_spend_allowed": False,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _evidence_score(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.35
    weighted = 0.0
    total = 0.0
    for item in evidence:
        weight = _clamp(float(item.get("weight", 1.0)), 0.1, 5.0)
        reliability = _clamp(float(item.get("reliability", 0.5)), 0.0, 1.0)
        weighted += weight * reliability
        total += weight
    return _clamp(weighted / max(total, 0.1), 0.25, 0.95)


def _hypothesis_quality(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.2
    complete = 0
    for item in items:
        if (
            str(
                item.get("name") or item.get("segment") or item.get("channel") or ""
            ).strip()
            and str(item.get("rationale") or "").strip()
        ):
            complete += 1
    return _clamp(complete / len(items), 0.2, 1.0)


def simulate_payload(payload: dict[str, Any], scenario: str) -> SimulationResult:
    if scenario not in SCENARIOS:
        raise GrowthCampaignError("unsupported-scenario")
    budget_minor = max(0, int(payload.get("budget_minor") or 0))
    if budget_minor <= 0:
        raise GrowthCampaignError("budget-required")
    markets = [
        str(x).strip() for x in payload.get("target_markets") or [] if str(x).strip()
    ]
    audiences = list(payload.get("audience_hypotheses") or [])
    competitors = list(payload.get("competitor_hypotheses") or [])
    channels = list(payload.get("channel_hypotheses") or [])
    offers = list(payload.get("offer_hypotheses") or [])
    evidence = list(payload.get("evidence") or [])

    evidence_score = _evidence_score(evidence)
    hypothesis_score = (
        _hypothesis_quality(audiences)
        + _hypothesis_quality(competitors)
        + _hypothesis_quality(channels)
        + _hypothesis_quality(offers)
    ) / 4.0
    geo_score = _clamp(len(markets) / 3.0, 0.35, 1.0)
    confidence = round(
        _clamp(
            0.45 * evidence_score + 0.4 * hypothesis_score + 0.15 * geo_score,
            0.25,
            0.92,
        ),
        3,
    )

    multipliers = {
        "conservative": (1.4, 0.006, 0.025),
        "expected": (2.3, 0.011, 0.045),
        "upside": (3.2, 0.017, 0.07),
    }
    reach_per_currency, ctr, cvr = multipliers[scenario]
    budget_units = budget_minor / 100.0
    quality_factor = _clamp(0.65 + 0.5 * confidence, 0.65, 1.1)
    base_reach = max(1, int(budget_units * 1000 * reach_per_currency * quality_factor))
    reach_min = int(base_reach * 0.72)
    reach_max = int(base_reach * 1.28)
    clicks_min = max(0, int(reach_min * ctr * 0.8))
    clicks_max = max(clicks_min, int(reach_max * ctr * 1.2))
    conversions_min = max(0, int(clicks_min * cvr * 0.75))
    conversions_max = max(conversions_min, int(clicks_max * cvr * 1.25))
    midpoint_conversions = (conversions_min + conversions_max) / 2.0
    cpa_minor = (
        int(budget_minor / midpoint_conversions) if midpoint_conversions >= 1 else None
    )

    reasons: list[str] = ["simulation-only", "no-provider-spend"]
    if evidence_score < 0.55:
        reasons.append("limited-evidence")
    missing_hypothesis_axis = any(
        not axis for axis in (audiences, competitors, offers, channels)
    )
    if hypothesis_score < 0.6 or missing_hypothesis_axis:
        reasons.append("weak-hypothesis-coverage")
    if len(markets) == 0:
        reasons.append("market-unspecified")
    if len(channels) == 0:
        reasons.append("channel-unspecified")

    assumptions = {
        "budget_minor": budget_minor,
        "currency": str(payload.get("currency") or "USD").upper(),
        "evidence_score": round(evidence_score, 3),
        "hypothesis_score": round(hypothesis_score, 3),
        "geo_score": round(geo_score, 3),
        "ctr_assumption": ctr,
        "conversion_rate_assumption": cvr,
        "model_version": "gs02-deterministic-v1",
    }
    return SimulationResult(
        scenario,
        confidence,
        reach_min,
        reach_max,
        clicks_min,
        clicks_max,
        conversions_min,
        conversions_max,
        cpa_minor,
        reasons,
        assumptions,
    )


def brief_fingerprint(payload: dict[str, Any]) -> str:
    canonical = "|".join(
        [
            str(payload.get("objective") or "").strip().lower(),
            str(payload.get("product_summary") or "").strip().lower(),
            ",".join(
                sorted(
                    str(x).strip().lower() for x in payload.get("target_markets") or []
                )
            ),
            str(int(payload.get("budget_minor") or 0)),
            str(payload.get("currency") or "USD").upper(),
        ]
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


async def _require(session: AsyncSession, actor: UserRecord, capability: str) -> None:
    decision = await growth_access.effective_access(session, actor, capability)
    if not decision.allowed:
        raise GrowthCampaignError(f"access-denied:{decision.reason}")


async def create_brief(
    session: AsyncSession, actor: UserRecord, payload: dict[str, Any]
) -> GrowthCampaignBrief:
    await _require(session, actor, "campaign.research")
    name = str(payload.get("name") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    product_summary = str(payload.get("product_summary") or "").strip()
    if not name or not objective or not product_summary:
        raise GrowthCampaignError("brief-fields-required")
    budget_minor = max(0, int(payload.get("budget_minor") or 0))
    brief = GrowthCampaignBrief(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        project_id=payload.get("project_id"),
        name=name[:240],
        objective=objective[:80],
        product_summary=product_summary,
        target_markets=list(payload.get("target_markets") or []),
        audience_hypotheses=list(payload.get("audience_hypotheses") or []),
        competitor_hypotheses=list(payload.get("competitor_hypotheses") or []),
        offer_hypotheses=list(payload.get("offer_hypotheses") or []),
        channel_hypotheses=list(payload.get("channel_hypotheses") or []),
        budget_minor=budget_minor,
        currency=str(payload.get("currency") or "USD").upper()[:3],
        evidence=list(payload.get("evidence") or []),
        status="draft",
        version=1,
    )
    session.add(brief)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="growth.campaign.brief_created",
            resource_type="growth_campaign_brief",
            resource_id=brief.id,
            details={
                "objective": objective[:80],
                "fingerprint": brief_fingerprint(payload),
                "real_spend_allowed": False,
            },
        )
    )
    await session.flush()
    return brief


async def simulate_brief(
    session: AsyncSession, actor: UserRecord, brief_id: str, scenario: str
) -> GrowthCampaignSimulation:
    await _require(session, actor, "campaign.simulation")
    brief = await session.scalar(
        select(GrowthCampaignBrief).where(
            GrowthCampaignBrief.id == brief_id,
            GrowthCampaignBrief.organization_id == actor.organization_id,
        )
    )
    if brief is None:
        raise GrowthCampaignError("brief-not-found")
    payload = {
        "budget_minor": brief.budget_minor,
        "currency": brief.currency,
        "target_markets": brief.target_markets,
        "audience_hypotheses": brief.audience_hypotheses,
        "competitor_hypotheses": brief.competitor_hypotheses,
        "offer_hypotheses": brief.offer_hypotheses,
        "channel_hypotheses": brief.channel_hypotheses,
        "evidence": brief.evidence,
    }
    result = simulate_payload(payload, scenario)
    record = GrowthCampaignSimulation(
        organization_id=actor.organization_id,
        brief_id=brief.id,
        requested_by_id=actor.id,
        scenario=result.scenario,
        confidence=result.confidence,
        estimated_reach_min=result.reach_min,
        estimated_reach_max=result.reach_max,
        estimated_clicks_min=result.clicks_min,
        estimated_clicks_max=result.clicks_max,
        estimated_conversions_min=result.conversions_min,
        estimated_conversions_max=result.conversions_max,
        estimated_cpa_minor=result.cpa_minor,
        reason_codes=result.reason_codes,
        assumptions=result.assumptions,
        result=result.as_dict(),
        real_spend_allowed=False,
    )
    session.add(record)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="growth.campaign.simulated",
            resource_type="growth_campaign_simulation",
            resource_id=record.id,
            details={
                "brief_id": brief.id,
                "scenario": scenario,
                "confidence": result.confidence,
                "real_spend_allowed": False,
            },
        )
    )
    await session.flush()
    return record


async def list_briefs(
    session: AsyncSession, actor: UserRecord
) -> list[GrowthCampaignBrief]:
    await _require(session, actor, "campaign.research")
    return list(
        (
            await session.scalars(
                select(GrowthCampaignBrief)
                .where(
                    GrowthCampaignBrief.organization_id == actor.organization_id,
                )
                .order_by(GrowthCampaignBrief.created_at.desc())
                .limit(100)
            )
        ).all()
    )
