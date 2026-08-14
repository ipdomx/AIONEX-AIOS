"""GS-05 deterministic analytics normalization and learning ledger.

GS-05 consumes normalized evidence supplied by AIOS. It performs no provider fetch,
no campaign mutation, no automatic replay, and no budget change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthLearningEntry,
    GrowthOptimizationRecommendation,
    GrowthPerformanceObservation,
)
from app.services import growth_access
from app.services import growth_social_accounts as social_accounts

AUTO_OPTIMIZATION_ALLOWED = False
AUTO_REPLAY_ALLOWED = False
SOURCES = ("simulation", "first_party", "manual_import", "provider_normalized")
SUBJECT_TYPES = ("campaign", "content", "account", "experiment", "project")
OUTCOMES = ("success", "failure", "inconclusive")
FAILURE_REASON_TAXONOMY = (
    "insufficient-sample",
    "tracking-incomplete",
    "low-ctr",
    "low-conversion-rate",
    "no-conversions",
    "high-cpa",
    "roas-below-target",
    "negative-roas",
    "low-engagement-rate",
)


class GrowthAnalyticsError(RuntimeError):
    """Fail-closed GS-05 analytics error."""


async def _require(session: AsyncSession, actor: UserRecord) -> None:
    decision = await growth_access.effective_access(session, actor, "analytics.read")
    if not decision.allowed:
        raise GrowthAnalyticsError(f"access-denied:{decision.reason}")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _assert_safe(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if any(marker in lowered for marker in social_accounts.SENSITIVE_KEYS):
                raise GrowthAnalyticsError(f"sensitive-field-rejected:{path}.{key}")
            _assert_safe(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe(item, path=f"{path}[{index}]")


def _nonnegative_int(payload: dict[str, Any], key: str) -> int:
    value = int(payload.get(key) or 0)
    if value < 0:
        raise GrowthAnalyticsError(f"negative-metric:{key}")
    return value


def normalize_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    impressions = _nonnegative_int(payload, "impressions")
    reach = _nonnegative_int(payload, "reach")
    engagements = _nonnegative_int(payload, "engagements")
    clicks = _nonnegative_int(payload, "clicks")
    conversions = _nonnegative_int(payload, "conversions")
    spend_minor = _nonnegative_int(payload, "spend_minor")
    revenue_minor = _nonnegative_int(payload, "revenue_minor")

    ctr = clicks / impressions if impressions else 0.0
    engagement_rate = engagements / impressions if impressions else 0.0
    conversion_rate = conversions / clicks if clicks else 0.0
    cpc_minor = int(round(spend_minor / clicks)) if clicks else None
    cpa_minor = int(round(spend_minor / conversions)) if conversions else None
    roas = revenue_minor / spend_minor if spend_minor else None

    return {
        "impressions": impressions,
        "reach": reach,
        "engagements": engagements,
        "clicks": clicks,
        "conversions": conversions,
        "spend_minor": spend_minor,
        "revenue_minor": revenue_minor,
        "ctr": round(ctr, 6),
        "engagement_rate": round(engagement_rate, 6),
        "conversion_rate": round(conversion_rate, 6),
        "cpc_minor": cpc_minor,
        "cpa_minor": cpa_minor,
        "roas": round(roas, 6) if roas is not None else None,
    }


def evidence_quality(payload: dict[str, Any]) -> float:
    impressions = max(0, int(payload.get("impressions") or 0))
    if impressions < 100:
        sample = 0.25
    elif impressions < 1_000:
        sample = 0.5
    elif impressions < 10_000:
        sample = 0.75
    else:
        sample = 0.9

    evidence = list(payload.get("evidence") or [])
    if not evidence:
        reliability = 0.35
    else:
        values = [
            _clamp(float(item.get("reliability", 0.5)))
            for item in evidence
            if isinstance(item, dict)
        ]
        reliability = sum(values) / len(values) if values else 0.35
    return round(_clamp(0.65 * sample + 0.35 * reliability), 3)


def _targets(context: dict[str, Any]) -> dict[str, Any]:
    raw = dict(context.get("targets") or {})
    return {
        "min_impressions": max(1, int(raw.get("min_impressions", 100))),
        "min_ctr": max(0.0, float(raw.get("min_ctr", 0.005))),
        "min_conversion_rate": max(0.0, float(raw.get("min_conversion_rate", 0.02))),
        "min_engagement_rate": max(0.0, float(raw.get("min_engagement_rate", 0.0))),
        "max_cpa_minor": (
            max(1, int(raw["max_cpa_minor"]))
            if raw.get("max_cpa_minor") is not None
            else None
        ),
        "min_roas": (
            max(0.0, float(raw["min_roas"]))
            if raw.get("min_roas") is not None
            else None
        ),
    }


def classify_metrics(
    normalized: dict[str, Any],
    context: dict[str, Any],
    sample_quality: float,
) -> tuple[str, float, list[str]]:
    targets = _targets(context)
    reasons: list[str] = []
    impressions = int(normalized["impressions"])
    clicks = int(normalized["clicks"])
    conversions = int(normalized["conversions"])
    spend_minor = int(normalized["spend_minor"])

    if impressions < targets["min_impressions"]:
        reasons.append("insufficient-sample")
    if spend_minor > 0 and impressions == 0:
        reasons.append("tracking-incomplete")
    if (
        impressions >= targets["min_impressions"]
        and normalized["ctr"] < targets["min_ctr"]
    ):
        reasons.append("low-ctr")
    if (
        targets["min_engagement_rate"] > 0
        and impressions >= targets["min_impressions"]
        and normalized["engagement_rate"] < targets["min_engagement_rate"]
    ):
        reasons.append("low-engagement-rate")
    if clicks >= 20 and normalized["conversion_rate"] < targets["min_conversion_rate"]:
        reasons.append("low-conversion-rate")
    if clicks >= 20 and conversions == 0:
        reasons.append("no-conversions")
    if (
        targets["max_cpa_minor"] is not None
        and normalized["cpa_minor"] is not None
        and normalized["cpa_minor"] > targets["max_cpa_minor"]
    ):
        reasons.append("high-cpa")
    if targets["max_cpa_minor"] is not None and spend_minor > 0 and conversions == 0:
        if "high-cpa" not in reasons:
            reasons.append("high-cpa")
    if normalized["roas"] is not None and normalized["roas"] < 1.0:
        reasons.append("negative-roas")
    if (
        targets["min_roas"] is not None
        and normalized["roas"] is not None
        and normalized["roas"] < targets["min_roas"]
    ):
        reasons.append("roas-below-target")

    reasons = list(dict.fromkeys(reasons))
    if "insufficient-sample" in reasons or "tracking-incomplete" in reasons:
        outcome = "inconclusive"
        score = round(_clamp(0.25 + 0.35 * sample_quality), 3)
    elif reasons:
        outcome = "failure"
        penalty = min(0.45, 0.08 * len(reasons))
        score = round(_clamp(0.58 * sample_quality + 0.22 - penalty), 3)
    else:
        outcome = "success"
        score = round(_clamp(0.72 + 0.28 * sample_quality), 3)
        reasons = ["targets-met"]
    return outcome, score, reasons


def pattern_fingerprint(
    *,
    subject_type: str,
    provider: str | None,
    context: dict[str, Any],
    outcome: str,
    reason_codes: list[str],
) -> str:
    keys = (
        "objective",
        "audience_key",
        "creative_key",
        "offer_key",
        "geo_key",
        "placement_key",
    )
    pattern_context = {
        key: context.get(key) for key in keys if context.get(key) is not None
    }
    canonical = json.dumps(
        {
            "subject_type": subject_type,
            "provider": provider or "provider-neutral",
            "context": pattern_context,
            "outcome": outcome,
            "reason_codes": sorted(reason_codes),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def recommendation_for_pattern(
    *,
    outcome: str,
    sample_quality: float,
    success_count: int,
    failure_count: int,
    reason_codes: list[str],
) -> dict[str, Any]:
    reasons = list(reason_codes)
    if outcome == "success" and sample_quality >= 0.6:
        action = "replay_candidate"
        replay_eligible = True
        reasons.extend(["evidence-backed-success", "manual-approval-required"])
        confidence = round(_clamp(0.55 + 0.45 * sample_quality), 3)
    elif outcome == "failure" and failure_count >= 2:
        action = "avoid"
        replay_eligible = False
        reasons.extend(["repeat-failure-blocked", "do-not-repeat-same-pattern"])
        confidence = round(_clamp(0.5 + 0.4 * sample_quality), 3)
    elif outcome == "failure":
        action = "iterate"
        replay_eligible = False
        reasons.extend(["first-failure-requires-iteration"])
        confidence = round(_clamp(0.45 + 0.35 * sample_quality), 3)
    else:
        action = "measure"
        replay_eligible = False
        reasons.extend(["insufficient-evidence-for-replay"])
        confidence = round(_clamp(0.3 + 0.3 * sample_quality), 3)
    return {
        "action": action,
        "replay_eligible": replay_eligible,
        "confidence": confidence,
        "reason_codes": list(dict.fromkeys(reasons)),
        "success_count": success_count,
        "failure_count": failure_count,
        "auto_optimization_allowed": False,
        "auto_replay_allowed": False,
    }


def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={
                "auto_optimization_allowed": False,
                "auto_replay_allowed": False,
                "live_provider_call": False,
                **dict(details or {}),
            },
        )
    )


async def record_observation(
    session: AsyncSession,
    actor: UserRecord,
    payload: dict[str, Any],
) -> GrowthPerformanceObservation:
    await _require(session, actor)
    subject_type = str(payload.get("subject_type") or "").strip().lower()
    subject_id = str(payload.get("subject_id") or "").strip()
    source = str(payload.get("source") or "simulation").strip().lower()
    if subject_type not in SUBJECT_TYPES:
        raise GrowthAnalyticsError("unsupported-subject-type")
    if not subject_id:
        raise GrowthAnalyticsError("subject-id-required")
    if source not in SOURCES:
        raise GrowthAnalyticsError("unsupported-observation-source")
    period_start = payload.get("period_start")
    period_end = payload.get("period_end")
    if not isinstance(period_start, datetime) or not isinstance(period_end, datetime):
        raise GrowthAnalyticsError("observation-period-required")
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    if period_end <= period_start:
        raise GrowthAnalyticsError("invalid-observation-period")

    context = dict(payload.get("context") or {})
    extra_metrics = dict(payload.get("extra_metrics") or {})
    evidence = list(payload.get("evidence") or [])
    _assert_safe(context, path="context")
    _assert_safe(extra_metrics, path="extra_metrics")
    _assert_safe(evidence, path="evidence")
    normalized = normalize_metrics(payload)
    quality = evidence_quality(payload)
    followers_delta = int(payload.get("followers_delta") or 0)

    row = GrowthPerformanceObservation(
        organization_id=actor.organization_id,
        recorded_by_id=actor.id,
        subject_type=subject_type,
        subject_id=subject_id[:160],
        provider=(str(payload.get("provider") or "").strip().lower() or None),
        source=source,
        period_start=period_start,
        period_end=period_end,
        currency=str(payload.get("currency") or "USD").upper()[:3],
        impressions=normalized["impressions"],
        reach=normalized["reach"],
        engagements=normalized["engagements"],
        clicks=normalized["clicks"],
        conversions=normalized["conversions"],
        spend_minor=normalized["spend_minor"],
        revenue_minor=normalized["revenue_minor"],
        followers_delta=followers_delta,
        extra_metrics=extra_metrics,
        evidence=evidence,
        context=context,
        sample_quality=quality,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.analytics.observation_recorded",
        "growth_performance_observation",
        row.id,
        {"subject_type": subject_type, "source": source, "sample_quality": quality},
    )
    await session.flush()
    return row


async def analyze_observation(
    session: AsyncSession,
    actor: UserRecord,
    observation_id: str,
) -> tuple[GrowthLearningEntry, GrowthOptimizationRecommendation]:
    await _require(session, actor)
    observation = await session.scalar(
        select(GrowthPerformanceObservation).where(
            GrowthPerformanceObservation.id == observation_id,
            GrowthPerformanceObservation.organization_id == actor.organization_id,
        )
    )
    if observation is None:
        raise GrowthAnalyticsError("observation-not-found")
    existing = await session.scalar(
        select(GrowthLearningEntry).where(
            GrowthLearningEntry.observation_id == observation.id
        )
    )
    if existing is not None:
        recommendation = await session.scalar(
            select(GrowthOptimizationRecommendation).where(
                GrowthOptimizationRecommendation.learning_entry_id == existing.id
            )
        )
        if recommendation is None:
            raise GrowthAnalyticsError("learning-recommendation-missing")
        return existing, recommendation

    normalized = normalize_metrics(
        {
            "impressions": observation.impressions,
            "reach": observation.reach,
            "engagements": observation.engagements,
            "clicks": observation.clicks,
            "conversions": observation.conversions,
            "spend_minor": observation.spend_minor,
            "revenue_minor": observation.revenue_minor,
        }
    )
    outcome, score, reasons = classify_metrics(
        normalized, observation.context, observation.sample_quality
    )
    fingerprint = pattern_fingerprint(
        subject_type=observation.subject_type,
        provider=observation.provider,
        context=observation.context,
        outcome=outcome,
        reason_codes=reasons,
    )
    previous = (
        await session.scalars(
            select(GrowthLearningEntry).where(
                GrowthLearningEntry.organization_id == actor.organization_id,
                GrowthLearningEntry.fingerprint == fingerprint,
            )
        )
    ).all()
    success_count = sum(item.outcome == "success" for item in previous) + int(
        outcome == "success"
    )
    failure_count = sum(item.outcome == "failure" for item in previous) + int(
        outcome == "failure"
    )
    occurrence_index = len(previous) + 1

    learning = GrowthLearningEntry(
        organization_id=actor.organization_id,
        observation_id=observation.id,
        subject_type=observation.subject_type,
        subject_id=observation.subject_id,
        outcome=outcome,
        score=score,
        fingerprint=fingerprint,
        reason_codes=reasons,
        normalized_metrics=normalized,
        context=dict(observation.context or {}),
        occurrence_index=occurrence_index,
        success_count=success_count,
        failure_count=failure_count,
        version=1,
    )
    session.add(learning)
    await session.flush()
    advice = recommendation_for_pattern(
        outcome=outcome,
        sample_quality=observation.sample_quality,
        success_count=success_count,
        failure_count=failure_count,
        reason_codes=reasons,
    )
    recommendation = GrowthOptimizationRecommendation(
        organization_id=actor.organization_id,
        learning_entry_id=learning.id,
        subject_type=observation.subject_type,
        subject_id=observation.subject_id,
        fingerprint=fingerprint,
        action=advice["action"],
        replay_eligible=advice["replay_eligible"],
        confidence=advice["confidence"],
        reason_codes=advice["reason_codes"],
        evidence={
            "observation_id": observation.id,
            "sample_quality": observation.sample_quality,
            "normalized_metrics": normalized,
            "success_count": success_count,
            "failure_count": failure_count,
        },
        status="active",
        auto_optimization_allowed=False,
        auto_replay_allowed=False,
    )
    session.add(recommendation)
    await session.flush()
    _audit(
        session,
        actor,
        "growth.analytics.learning_recorded",
        "growth_learning_entry",
        learning.id,
        {
            "outcome": outcome,
            "fingerprint": fingerprint,
            "recommendation": advice["action"],
            "replay_eligible": advice["replay_eligible"],
        },
    )
    await session.flush()
    return learning, recommendation


def public_observation(row: GrowthPerformanceObservation) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "provider": row.provider,
        "source": row.source,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "currency": row.currency,
        "metrics": normalize_metrics(
            {
                "impressions": row.impressions,
                "reach": row.reach,
                "engagements": row.engagements,
                "clicks": row.clicks,
                "conversions": row.conversions,
                "spend_minor": row.spend_minor,
                "revenue_minor": row.revenue_minor,
            }
        ),
        "followers_delta": row.followers_delta,
        "extra_metrics": dict(row.extra_metrics or {}),
        "evidence": list(row.evidence or []),
        "context": dict(row.context or {}),
        "sample_quality": row.sample_quality,
        "live_provider_call": False,
    }


def public_learning(row: GrowthLearningEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "observation_id": row.observation_id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "outcome": row.outcome,
        "score": row.score,
        "fingerprint": row.fingerprint,
        "reason_codes": list(row.reason_codes or []),
        "normalized_metrics": dict(row.normalized_metrics or {}),
        "context": dict(row.context or {}),
        "occurrence_index": row.occurrence_index,
        "success_count": row.success_count,
        "failure_count": row.failure_count,
    }


def public_recommendation(row: GrowthOptimizationRecommendation) -> dict[str, Any]:
    return {
        "id": row.id,
        "learning_entry_id": row.learning_entry_id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "fingerprint": row.fingerprint,
        "action": row.action,
        "replay_eligible": row.replay_eligible,
        "confidence": row.confidence,
        "reason_codes": list(row.reason_codes or []),
        "evidence": dict(row.evidence or {}),
        "status": row.status,
        "auto_optimization_allowed": False,
        "auto_replay_allowed": False,
    }


async def list_observations(
    session: AsyncSession, actor: UserRecord, limit: int = 100
) -> list[dict[str, Any]]:
    await _require(session, actor)
    rows = (
        await session.scalars(
            select(GrowthPerformanceObservation)
            .where(
                GrowthPerformanceObservation.organization_id == actor.organization_id
            )
            .order_by(GrowthPerformanceObservation.period_end.desc())
            .limit(max(1, min(500, limit)))
        )
    ).all()
    return [public_observation(row) for row in rows]


async def list_recommendations(
    session: AsyncSession, actor: UserRecord, limit: int = 100
) -> list[dict[str, Any]]:
    await _require(session, actor)
    rows = (
        await session.scalars(
            select(GrowthOptimizationRecommendation)
            .where(
                GrowthOptimizationRecommendation.organization_id
                == actor.organization_id
            )
            .order_by(GrowthOptimizationRecommendation.created_at.desc())
            .limit(max(1, min(500, limit)))
        )
    ).all()
    return [public_recommendation(row) for row in rows]


async def pattern_summary(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    await _require(session, actor)
    rows = (
        await session.scalars(
            select(GrowthLearningEntry)
            .where(GrowthLearningEntry.organization_id == actor.organization_id)
            .order_by(GrowthLearningEntry.created_at)
        )
    ).all()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(
            row.fingerprint,
            {
                "fingerprint": row.fingerprint,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "occurrences": 0,
                "successes": 0,
                "failures": 0,
                "inconclusive": 0,
                "last_reason_codes": [],
                "last_score": 0.0,
            },
        )
        item["occurrences"] += 1
        if row.outcome == "success":
            item["successes"] += 1
        elif row.outcome == "failure":
            item["failures"] += 1
        else:
            item["inconclusive"] += 1
        item["last_reason_codes"] = list(row.reason_codes or [])
        item["last_score"] = row.score
    return sorted(
        grouped.values(),
        key=lambda item: (-item["occurrences"], item["fingerprint"]),
    )
