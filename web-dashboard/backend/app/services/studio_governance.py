"""Phase 36M unified Studio capability catalogue and durable Owner policy.

This module deliberately reuses ``OwnerControlRecord`` instead of adding another
policy table.  User reads are side-effect free: defaults are merged with any
explicit Owner override.  External provider activation is not introduced here;
this gate remains provider-neutral and zero-cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.phase36_program import phase36_program_snapshot
from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    OwnerControlRecord,
    StudioAsset,
    StudioJob,
    uuid_str,
)

POLICY_DOMAIN = "studio-capabilities"
PLAN_CODES = frozenset({"free", "starter", "professional", "enterprise"})
PROVIDER_MODES = frozenset({"provider_neutral"})
MODERATION_MODES = frozenset({"standard", "strict"})
ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})


class StudioGovernanceError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    capability_id: str
    title: str
    category: str
    launch_surface: str
    departments: tuple[str, ...]
    phase36_capability_ids: tuple[str, ...]
    supported_plans: tuple[str, ...] = ("free", "starter", "professional", "enterprise")
    required_permissions: tuple[str, ...] = ()
    runtime_launchable: bool = True
    activation_reason: str | None = None
    default_daily_job_limit: int = 50
    default_max_concurrent_jobs: int = 4
    default_max_attempts: int = 3


CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        "software",
        "Software & Apps",
        "software",
        "studio",
        ("website", "code"),
        (
            "web-saas-pwa",
            "api-serverless",
            "mobile-apps",
            "desktop-apps",
            "browser-extensions",
            "bots-automation-cli-sdk",
        ),
    ),
    CapabilityDefinition(
        "prompt-text",
        "Prompt & Text",
        "creative",
        "studio",
        ("text",),
        ("prompt-factory",),
    ),
    CapabilityDefinition(
        "design-image",
        "Design, Image & Brand",
        "creative",
        "studio",
        ("ui-ux", "image", "branding"),
        (
            "image-generation-editing",
            "logo-branding",
            "infographic-experimental-graphics",
            "editable-design-exports",
        ),
    ),
    CapabilityDefinition(
        "audio",
        "Audio, Voice & Dubbing",
        "creative",
        "studio",
        ("audio",),
        (
            "stock-voice-tts",
            "governed-stt-transcript",
            "complete-stock-voice-dubbing",
            "audio-cleanup-master",
        ),
    ),
    CapabilityDefinition(
        "video-motion",
        "Video, Motion & Advertising",
        "creative",
        "studio",
        ("video", "animation", "advertising", "documentary"),
        (
            "text-image-logo-to-video",
            "long-form-ad-video",
            "cinema-motion-vfx",
            "video-continuity-resume",
            "video-final-export",
        ),
    ),
    CapabilityDefinition(
        "three-d-xr",
        "3D & XR",
        "creative",
        "studio",
        ("three-d",),
        ("two-d-animation-games", "three-d-production", "xr-ar-vr"),
    ),
    CapabilityDefinition(
        "music-song",
        "Music & Song",
        "creative",
        "studio-gated",
        (),
        (
            "lyria-3-music-generation",
            "stable-audio-instrumental-generation",
            "song-production",
            "podcast-jingle-narration",
        ),
        supported_plans=("starter", "professional", "enterprise"),
        runtime_launchable=False,
        activation_reason="external_activation_required",
    ),
    CapabilityDefinition(
        "courses",
        "Courses & Academy",
        "education",
        "academy",
        (),
        ("course-factory", "learning-assessment-certification"),
        supported_plans=("starter", "professional", "enterprise"),
        required_permissions=("academy:read",),
    ),
    CapabilityDefinition(
        "sector-solutions",
        "Business & Sector Solutions",
        "sectors",
        "studio-sectors",
        (),
        (
            "retail-supermarket",
            "restaurant-hospitality",
            "pharmacy",
            "school-university",
            "government-public-service",
            "logistics-industry-realestate-professional",
            "custom-domain-composer",
        ),
    ),
    CapabilityDefinition(
        "realtime",
        "Realtime Communication",
        "realtime",
        "projects",
        (),
        ("realtime-chat-calling", "realtime-streaming-recording"),
    ),
)

_DEFINITIONS = {item.capability_id: item for item in CAPABILITIES}
_DEPARTMENT_CAPABILITY = {
    department: item.capability_id
    for item in CAPABILITIES
    for department in item.departments
}


def default_policy(definition: CapabilityDefinition) -> dict[str, Any]:
    return {
        "eligible_plans": list(definition.supported_plans),
        "daily_job_limit": definition.default_daily_job_limit,
        "max_concurrent_jobs": definition.default_max_concurrent_jobs,
        "max_attempts": definition.default_max_attempts,
        "max_cost_usd": 0.0,
        "provider_mode": "provider_neutral",
        "moderation_mode": "standard",
    }


def _normalize_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise StudioGovernanceError(
            "invalid_policy", f"{field} must be a non-empty list", http_status=422
        )
    normalized = list(
        dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip())
    )
    if not normalized:
        raise StudioGovernanceError(
            "invalid_policy", f"{field} must be a non-empty list", http_status=422
        )
    return normalized


def normalize_policy(
    definition: CapabilityDefinition,
    payload: Mapping[str, Any] | None,
    *,
    enabled: bool,
    version: int = 0,
) -> dict[str, Any]:
    merged = {**default_policy(definition), **dict(payload or {})}
    plans = _normalize_string_list(merged.get("eligible_plans"), field="eligible_plans")
    if set(plans) - PLAN_CODES:
        raise StudioGovernanceError(
            "invalid_policy", "eligible_plans contains an unknown plan", http_status=422
        )
    if set(plans) - set(definition.supported_plans):
        raise StudioGovernanceError(
            "invalid_policy",
            "eligible_plans contains a plan unsupported by this capability",
            http_status=422,
        )
    provider_mode = str(merged.get("provider_mode") or "").strip()
    if provider_mode not in PROVIDER_MODES:
        raise StudioGovernanceError(
            "invalid_policy",
            "provider_mode is not activated for this gate",
            http_status=422,
        )
    moderation_mode = str(merged.get("moderation_mode") or "").strip()
    if moderation_mode not in MODERATION_MODES:
        raise StudioGovernanceError(
            "invalid_policy", "moderation_mode is invalid", http_status=422
        )
    try:
        daily_limit = int(merged["daily_job_limit"])
        concurrent_limit = int(merged["max_concurrent_jobs"])
        max_attempts = int(merged["max_attempts"])
        max_cost = float(merged["max_cost_usd"])
    except (TypeError, ValueError, KeyError) as exc:
        raise StudioGovernanceError(
            "invalid_policy", "numeric policy values are invalid", http_status=422
        ) from exc
    if not 1 <= daily_limit <= 10_000:
        raise StudioGovernanceError(
            "invalid_policy",
            "daily_job_limit is outside the allowed range",
            http_status=422,
        )
    if not 1 <= concurrent_limit <= 100:
        raise StudioGovernanceError(
            "invalid_policy",
            "max_concurrent_jobs is outside the allowed range",
            http_status=422,
        )
    if not 1 <= max_attempts <= 5:
        raise StudioGovernanceError(
            "invalid_policy",
            "max_attempts is outside the allowed range",
            http_status=422,
        )
    if not 0 <= max_cost <= 1_000:
        raise StudioGovernanceError(
            "invalid_policy",
            "max_cost_usd is outside the allowed range",
            http_status=422,
        )
    if provider_mode == "provider_neutral" and abs(max_cost) > 1e-12:
        raise StudioGovernanceError(
            "invalid_policy",
            "provider-neutral Studio policy must have zero external cost",
            http_status=422,
        )
    return {
        "enabled": bool(enabled),
        "eligible_plans": plans,
        "daily_job_limit": daily_limit,
        "max_concurrent_jobs": concurrent_limit,
        "max_attempts": max_attempts,
        "max_cost_usd": max_cost,
        "provider_mode": provider_mode,
        "moderation_mode": moderation_mode,
        "version": int(version),
    }


async def _policy_records(session: AsyncSession) -> dict[str, OwnerControlRecord]:
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == POLICY_DOMAIN
                )
            )
        ).all()
    )
    return {item.resource_id: item for item in rows}


async def owner_catalog(session: AsyncSession) -> list[dict[str, Any]]:
    records = await _policy_records(session)
    phase = phase36_program_snapshot()
    phase_caps = {
        item["capability_id"]: item
        for batch in phase["batches"]
        for item in batch["capabilities"]
    }
    result: list[dict[str, Any]] = []
    for definition in CAPABILITIES:
        record = records.get(definition.capability_id)
        policy = normalize_policy(
            definition,
            record.payload if record is not None else None,
            enabled=record.enabled if record is not None else True,
            version=record.version if record is not None else 0,
        )
        maturities = [
            phase_caps[item]["maturity"]
            for item in definition.phase36_capability_ids
            if item in phase_caps
        ]
        external_gates = sorted(
            {
                gate
                for item in definition.phase36_capability_ids
                if item in phase_caps
                for gate in phase_caps[item].get("external_gates", ())
            }
        )
        result.append(
            {
                "capability_id": definition.capability_id,
                "title": definition.title,
                "category": definition.category,
                "launch_surface": definition.launch_surface,
                "departments": list(definition.departments),
                "phase36_capability_ids": list(definition.phase36_capability_ids),
                "supported_plans": list(definition.supported_plans),
                "required_permissions": list(definition.required_permissions),
                "runtime_launchable": definition.runtime_launchable,
                "activation_reason": definition.activation_reason,
                "maturities": maturities,
                "external_gates": external_gates,
                "policy": policy,
                "policy_source": "owner" if record is not None else "default",
            }
        )
    return result


async def user_catalog(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    plan = actor.organization_plan.strip().lower()
    result = []
    for item in await owner_catalog(session):
        policy = dict(item["policy"])
        if not policy["enabled"]:
            availability_reason = "owner_disabled"
        elif plan not in set(item["supported_plans"]):
            availability_reason = "plan_not_supported"
        elif plan not in set(policy["eligible_plans"]):
            availability_reason = "plan_not_eligible"
        elif (
            item["required_permissions"]
            and "*" not in set(actor.permissions)
            and not set(item["required_permissions"]).issubset(set(actor.permissions))
        ):
            availability_reason = "permission_required"
        elif not item["runtime_launchable"]:
            availability_reason = (
                item["activation_reason"] or "external_activation_required"
            )
        else:
            availability_reason = "available"
        result.append(
            {
                **item,
                "available": availability_reason == "available",
                "availability_reason": availability_reason,
                "organization_plan": plan,
            }
        )
    return result


async def update_policy(
    session: AsyncSession,
    *,
    actor: UserRecord,
    capability_id: str,
    enabled: bool,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    definition = _DEFINITIONS.get(capability_id)
    if definition is None:
        raise StudioGovernanceError(
            "unknown_capability", "Unknown Studio capability", http_status=404
        )
    normalized = normalize_policy(definition, payload, enabled=enabled)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == POLICY_DOMAIN,
            OwnerControlRecord.resource_id == capability_id,
        )
        .with_for_update()
    )
    stored_payload = {
        key: value
        for key, value in normalized.items()
        if key not in {"enabled", "version"}
    }
    if record is None:
        record = OwnerControlRecord(
            id=uuid_str(),
            domain=POLICY_DOMAIN,
            resource_id=capability_id,
            status="active",
            enabled=enabled,
            payload=stored_payload,
            version=1,
        )
        session.add(record)
    else:
        record.enabled = enabled
        record.status = "active"
        record.payload = stored_payload
        record.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="owner.studio_capability.updated",
            resource_type="studio_capability_policy",
            resource_id=capability_id,
            details={
                "enabled": enabled,
                "eligible_plans": stored_payload["eligible_plans"],
                "daily_job_limit": stored_payload["daily_job_limit"],
                "max_concurrent_jobs": stored_payload["max_concurrent_jobs"],
                "max_attempts": stored_payload["max_attempts"],
                "max_cost_usd": stored_payload["max_cost_usd"],
                "provider_mode": stored_payload["provider_mode"],
                "moderation_mode": stored_payload["moderation_mode"],
            },
        )
    )
    await session.flush()
    return {
        "capability_id": capability_id,
        "policy": normalize_policy(
            definition, record.payload, enabled=record.enabled, version=record.version
        ),
        "policy_source": "owner",
    }


async def admit_studio_job(
    session: AsyncSession,
    actor: UserRecord,
    department: str,
) -> dict[str, Any]:
    capability_id = _DEPARTMENT_CAPABILITY.get(department)
    if capability_id is None:
        raise StudioGovernanceError(
            "unmapped_department", "Studio department is not governed", http_status=422
        )
    definition = _DEFINITIONS[capability_id]
    records = await _policy_records(session)
    record = records.get(capability_id)
    policy = normalize_policy(
        definition,
        record.payload if record is not None else None,
        enabled=record.enabled if record is not None else True,
        version=record.version if record is not None else 0,
    )
    plan = actor.organization_plan.strip().lower()
    if not policy["enabled"]:
        raise StudioGovernanceError(
            "capability_disabled", "This Studio capability is disabled by the Owner"
        )
    if plan not in set(policy["eligible_plans"]):
        raise StudioGovernanceError(
            "plan_not_eligible",
            "Your organization plan is not eligible for this Studio capability",
        )
    current = datetime.now(UTC)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    department_scope = tuple(definition.departments)
    daily_count = int(
        await session.scalar(
            select(func.count(StudioJob.id)).where(
                StudioJob.organization_id == actor.organization_id,
                StudioJob.department.in_(department_scope),
                StudioJob.created_at >= day_start,
            )
        )
        or 0
    )
    if daily_count >= policy["daily_job_limit"]:
        raise StudioGovernanceError(
            "daily_limit", "Studio daily capability limit reached", http_status=429
        )
    concurrent = int(
        await session.scalar(
            select(func.count(StudioJob.id)).where(
                StudioJob.organization_id == actor.organization_id,
                StudioJob.department.in_(department_scope),
                StudioJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    if concurrent >= policy["max_concurrent_jobs"]:
        raise StudioGovernanceError(
            "concurrency_limit",
            "Studio capability concurrency limit reached",
            http_status=429,
        )
    return {
        "capability_id": capability_id,
        "policy": policy,
        "daily_jobs_used": daily_count,
        "active_jobs": concurrent,
        "policy_source": "owner" if record is not None else "default",
    }


async def hub_snapshot(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    status_rows = (
        await session.execute(
            select(StudioJob.status, func.count(StudioJob.id))
            .where(StudioJob.organization_id == actor.organization_id)
            .group_by(StudioJob.status)
        )
    ).all()
    asset_count = int(
        await session.scalar(
            select(func.count(StudioAsset.id)).where(
                StudioAsset.organization_id == actor.organization_id,
                StudioAsset.status == "active",
            )
        )
        or 0
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider_mode": "provider_neutral",
        "capabilities": await user_catalog(session, actor),
        "jobs": {str(status): int(count) for status, count in status_rows},
        "active_assets": asset_count,
    }
