"""Owner-controlled 3D access and GPU cost policy.

The default policy is deliberately restrictive: only the highest current public
plan (business) is eligible, and the Super Owner can change every access/cost
setting through the owner control plane.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OwnerControlRecord, uuid_str

THREE_D_POLICY_DOMAIN = "3d-service-policy"
THREE_D_POLICY_RESOURCE = "default"
THREE_D_ENTITLEMENT = "3d.generation"
DEFAULT_THREE_D_POLICY: dict[str, Any] = {
    "enabled": True,
    "allowed_plan_codes": ["business"],
    "required_entitlement": THREE_D_ENTITLEMENT,
    "allowed_user_ids": [],
    "denied_user_ids": [],
    "max_concurrent_jobs_per_user": 1,
    "max_runtime_seconds": 1800,
    "max_queue_seconds": 1200,
    "max_retries": 1,
    "max_estimated_job_cost_usd": 5.0,
    "daily_spend_limit_usd": 25.0,
    "monthly_spend_limit_usd": 500.0,
    "owner_alert_threshold_pct": 80,
    "monthly_jobs_per_user": 20,
    "max_input_megabytes": 12,
    "max_texture_size": 2048,
    "artifact_retention_days": 30,
    "signed_url_ttl_seconds": 900,
    "compression_policy": "compat",
}


def normalize_three_d_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = {**DEFAULT_THREE_D_POLICY, **(value or {})}
    plans = sorted(
        {
            str(x).strip().lower()
            for x in raw.get("allowed_plan_codes", [])
            if str(x).strip()
        }
    )
    allowed = sorted(
        {str(x).strip() for x in raw.get("allowed_user_ids", []) if str(x).strip()}
    )
    denied = sorted(
        {str(x).strip() for x in raw.get("denied_user_ids", []) if str(x).strip()}
    )
    policy = {
        "enabled": bool(raw["enabled"]),
        "allowed_plan_codes": plans or ["business"],
        "required_entitlement": str(
            raw.get("required_entitlement") or THREE_D_ENTITLEMENT
        ).strip(),
        "allowed_user_ids": allowed,
        "denied_user_ids": denied,
        "max_concurrent_jobs_per_user": max(
            1, min(int(raw["max_concurrent_jobs_per_user"]), 4)
        ),
        "max_runtime_seconds": max(60, min(int(raw["max_runtime_seconds"]), 3600)),
        "max_queue_seconds": max(10, min(int(raw["max_queue_seconds"]), 1800)),
        "max_retries": max(0, min(int(raw["max_retries"]), 3)),
        "max_estimated_job_cost_usd": max(
            0.01, min(float(raw["max_estimated_job_cost_usd"]), 100.0)
        ),
        "daily_spend_limit_usd": max(
            0.01, min(float(raw["daily_spend_limit_usd"]), 10000.0)
        ),
        "monthly_spend_limit_usd": max(
            0.01, min(float(raw["monthly_spend_limit_usd"]), 100000.0)
        ),
        "owner_alert_threshold_pct": max(
            1, min(int(raw["owner_alert_threshold_pct"]), 100)
        ),
        "monthly_jobs_per_user": max(1, min(int(raw["monthly_jobs_per_user"]), 1000)),
        "max_input_megabytes": max(1, min(int(raw["max_input_megabytes"]), 50)),
        "max_texture_size": max(512, min(int(raw["max_texture_size"]), 4096)),
        "artifact_retention_days": max(
            1, min(int(raw["artifact_retention_days"]), 365)
        ),
        "signed_url_ttl_seconds": max(
            60, min(int(raw["signed_url_ttl_seconds"]), 3600)
        ),
        "compression_policy": str(raw.get("compression_policy") or "compat")
        .strip()
        .lower(),
    }
    if policy["compression_policy"] not in {"compat", "meshopt"}:
        policy["compression_policy"] = "compat"
    if policy["required_entitlement"] == "":
        policy["required_entitlement"] = THREE_D_ENTITLEMENT
    return policy


def three_d_access_allowed(
    policy: dict[str, Any], *, user_id: str, plan_code: str, entitlements: list[str]
) -> bool:
    p = normalize_three_d_policy(policy)
    if not p["enabled"] or user_id in p["denied_user_ids"]:
        return False
    if user_id in p["allowed_user_ids"]:
        return True
    if plan_code.strip().lower() not in set(p["allowed_plan_codes"]):
        return False
    granted = set(entitlements)
    required = p["required_entitlement"]
    return "*" in granted or required in granted


async def _record(session: AsyncSession, *, lock: bool = False) -> OwnerControlRecord:
    stmt = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == THREE_D_POLICY_DOMAIN,
        OwnerControlRecord.resource_id == THREE_D_POLICY_RESOURCE,
    )
    if lock:
        stmt = stmt.with_for_update()
    record = await session.scalar(stmt)
    if record is None:
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain=THREE_D_POLICY_DOMAIN,
                resource_id=THREE_D_POLICY_RESOURCE,
                status="active",
                enabled=True,
                payload=DEFAULT_THREE_D_POLICY,
                version=1,
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(stmt)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="3D service policy unavailable",
        )
    normalized = normalize_three_d_policy(record.payload)
    if record.payload != normalized:
        record.payload = normalized
        record.version += 1
    return record


async def get_three_d_policy(session: AsyncSession) -> dict[str, Any]:
    return normalize_three_d_policy((await _record(session)).payload)


async def get_three_d_policy_for_update(session: AsyncSession) -> dict[str, Any]:
    """Lock the single owner policy row while admission/concurrency is evaluated."""
    return normalize_three_d_policy((await _record(session, lock=True)).payload)


async def update_three_d_policy(
    session: AsyncSession, updates: dict[str, Any]
) -> dict[str, Any]:
    record = await _record(session, lock=True)
    record.payload = normalize_three_d_policy({**record.payload, **updates})
    record.enabled = bool(record.payload["enabled"])
    record.status = "active" if record.enabled else "suspended"
    record.version += 1
    return dict(record.payload)
