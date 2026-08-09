"""Phase 34E durable observability, circuit breaking, cleanup and spend guards for 3D."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditEvent,
    OwnerControlRecord,
    ThreeDArtifact,
    ThreeDGenerationJob,
    uuid_str,
)
from app.services import communications
from app.services.three_d_policy import get_three_d_policy
from app.services.three_d_storage import ThreeDObjectStore

PROVIDER_STATE_DOMAIN = "3d-provider-runtime"
PROVIDER_STATE_RESOURCE = "hunyuan3d"
SUPPORTED_PROVIDER_RESOURCES = {"hunyuan3d", "triposr"}


def now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def request_fingerprint(
    *,
    organization_id: str,
    user_id: str,
    project_id: str,
    image_sha256: str,
    seed: int,
    texture_size: int,
    compression_policy: str,
    provider: str = "",
) -> str:
    value = ":".join(
        [
            organization_id,
            user_id,
            project_id,
            image_sha256.lower(),
            str(seed),
            str(texture_size),
            compression_policy.strip().lower(),
            provider.strip().lower(),
        ]
    )
    return sha256(value.encode()).hexdigest()


def normalize_idempotency_key(
    raw: str | None,
    *,
    fingerprint: str,
    namespace: str,
    window_seconds: int = 600,
) -> str:
    value = (raw or "").strip()
    scope = namespace.strip()
    if not scope:
        raise HTTPException(
            status_code=422, detail={"code": "THREE_D_IDEMPOTENCY_SCOPE_INVALID"}
        )
    if not value:
        bucket = int(now().timestamp()) // max(30, int(window_seconds))
        return sha256(f"auto:{scope}:{fingerprint}:{bucket}".encode()).hexdigest()
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise HTTPException(
            status_code=422, detail={"code": "THREE_D_IDEMPOTENCY_KEY_INVALID"}
        )
    return sha256(f"explicit:{scope}:{value}".encode()).hexdigest()


def normalize_trace_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return str(uuid_str())
    if any(ord(char) < 32 for char in value):
        raise HTTPException(
            status_code=422, detail={"code": "THREE_D_TRACE_ID_INVALID"}
        )
    if len(value) <= 64:
        return value
    return sha256(value.encode()).hexdigest()


def _provider_resource(provider: str) -> str:
    value = provider.strip().lower()
    if value == "runpod":
        value = "hunyuan3d"
    if value not in SUPPORTED_PROVIDER_RESOURCES:
        raise RuntimeError("Unsupported 3D provider runtime state")
    return value


async def _provider_record(
    session: AsyncSession,
    *,
    provider: str = PROVIDER_STATE_RESOURCE,
    lock: bool = False,
) -> OwnerControlRecord:
    resource_id = _provider_resource(provider)
    stmt = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN,
        OwnerControlRecord.resource_id == resource_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    record = await session.scalar(stmt)
    if record is None:
        await session.execute(
            pg_insert(OwnerControlRecord)
            .values(
                id=uuid_str(),
                domain=PROVIDER_STATE_DOMAIN,
                resource_id=resource_id,
                status="closed",
                enabled=True,
                payload={
                    "state": "closed",
                    "consecutive_failures": 0,
                    "opened_at": None,
                    "open_until": None,
                    "last_failure_at": None,
                    "last_success_at": None,
                    "last_error_code": None,
                },
                version=1,
            )
            .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        )
        record = await session.scalar(stmt)
    if record is None:
        raise RuntimeError("3D provider runtime state unavailable")
    return record


def _provider_payload(record: OwnerControlRecord) -> dict[str, Any]:
    payload = dict(record.payload or {})
    return {
        "state": str(payload.get("state") or "closed"),
        "consecutive_failures": int(payload.get("consecutive_failures") or 0),
        "opened_at": payload.get("opened_at"),
        "open_until": payload.get("open_until"),
        "last_failure_at": payload.get("last_failure_at"),
        "last_success_at": payload.get("last_success_at"),
        "last_error_code": payload.get("last_error_code"),
    }


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


async def provider_circuit_snapshot(
    session: AsyncSession,
    *,
    provider: str = PROVIDER_STATE_RESOURCE,
    lock: bool = False,
) -> dict[str, Any]:
    record = await _provider_record(session, provider=provider, lock=lock)
    payload = _provider_payload(record)
    open_until = _parse_iso(payload["open_until"])
    if payload["state"] == "open" and open_until and open_until <= now():
        payload["state"] = "half_open"
        record.status = "half_open"
        record.payload = payload
        record.version += 1
    payload["available"] = payload["state"] in {"closed", "half_open"}
    return payload


async def assert_provider_available(
    session: AsyncSession, *, provider: str = PROVIDER_STATE_RESOURCE
) -> dict[str, Any]:
    state = await provider_circuit_snapshot(session, provider=provider, lock=True)
    if state["state"] == "open":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "THREE_D_PROVIDER_CIRCUIT_OPEN",
                "message": "3D generation is temporarily paused while the GPU provider recovers.",
                "retry_after": state.get("open_until"),
            },
        )
    return state


async def record_provider_success(
    session: AsyncSession, *, provider: str = PROVIDER_STATE_RESOURCE
) -> dict[str, Any]:
    record = await _provider_record(session, provider=provider, lock=True)
    payload = _provider_payload(record)
    payload.update(
        {
            "state": "closed",
            "consecutive_failures": 0,
            "open_until": None,
            "last_success_at": now().isoformat(),
            "last_error_code": None,
        }
    )
    record.payload = payload
    record.status = "closed"
    record.enabled = True
    record.version += 1
    return payload


async def record_provider_failure(
    session: AsyncSession, *, error_code: str, provider: str = PROVIDER_STATE_RESOURCE
) -> tuple[dict[str, Any], bool]:
    policy = await get_three_d_policy(session)
    record = await _provider_record(session, provider=provider, lock=True)
    payload = _provider_payload(record)
    failures = int(payload["consecutive_failures"]) + 1
    opened = failures >= int(policy["provider_failure_threshold"])
    moment = now()
    payload.update(
        {
            "consecutive_failures": failures,
            "last_failure_at": moment.isoformat(),
            "last_error_code": error_code,
        }
    )
    if opened:
        payload["state"] = "open"
        payload["opened_at"] = moment.isoformat()
        payload["open_until"] = (
            moment + timedelta(seconds=int(policy["provider_circuit_open_seconds"]))
        ).isoformat()
        record.status = "open"
    else:
        payload["state"] = "closed"
        record.status = "closed"
    record.payload = payload
    record.enabled = not opened
    record.version += 1
    return payload, opened


async def reset_provider_circuit(
    session: AsyncSession,
    *,
    actor_id: str,
    organization_id: str,
    provider: str = PROVIDER_STATE_RESOURCE,
) -> dict[str, Any]:
    resource_id = _provider_resource(provider)
    record = await _provider_record(session, provider=resource_id, lock=True)
    payload = _provider_payload(record)
    payload.update(
        {
            "state": "closed",
            "consecutive_failures": 0,
            "opened_at": None,
            "open_until": None,
            "last_error_code": None,
            "last_success_at": now().isoformat(),
        }
    )
    record.payload = payload
    record.status = "closed"
    record.enabled = True
    record.version += 1
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.3d.circuit_reset",
            resource_type="3d_provider_runtime",
            resource_id=resource_id,
            details={"state": "closed", "provider": resource_id},
        )
    )
    return payload


async def find_duplicate_job(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    project_id: str,
    idempotency_key: str,
    fingerprint: str,
    window_seconds: int,
) -> ThreeDGenerationJob | None:
    direct = await session.scalar(
        select(ThreeDGenerationJob).where(
            ThreeDGenerationJob.organization_id == organization_id,
            ThreeDGenerationJob.requested_by_id == user_id,
            ThreeDGenerationJob.project_id == project_id,
            ThreeDGenerationJob.idempotency_key == idempotency_key,
        )
    )
    if direct is not None:
        if direct.request_fingerprint and direct.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={"code": "THREE_D_IDEMPOTENCY_KEY_REUSED"},
            )
        return direct
    threshold = now() - timedelta(seconds=max(30, int(window_seconds)))
    return await session.scalar(
        select(ThreeDGenerationJob)
        .where(
            ThreeDGenerationJob.organization_id == organization_id,
            ThreeDGenerationJob.requested_by_id == user_id,
            ThreeDGenerationJob.project_id == project_id,
            ThreeDGenerationJob.request_fingerprint == fingerprint,
            ThreeDGenerationJob.created_at >= threshold,
            ThreeDGenerationJob.status.in_(
                {
                    "queued",
                    "running",
                    "cancel_requested",
                    "completed",
                    "needs_clarification",
                }
            ),
        )
        .order_by(ThreeDGenerationJob.created_at.desc())
        .limit(1)
    )


async def spend_snapshot(session: AsyncSession) -> dict[str, float]:
    moment = now()
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    month = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    terminal_excluded = {"cancelled", "failed", "needs_clarification"}
    daily = float(
        await session.scalar(
            select(
                func.coalesce(func.sum(ThreeDGenerationJob.estimated_cost_usd), 0.0)
            ).where(
                ThreeDGenerationJob.created_at >= day,
                ThreeDGenerationJob.status.notin_(terminal_excluded),
            )
        )
        or 0.0
    )
    monthly = float(
        await session.scalar(
            select(
                func.coalesce(func.sum(ThreeDGenerationJob.estimated_cost_usd), 0.0)
            ).where(
                ThreeDGenerationJob.created_at >= month,
                ThreeDGenerationJob.status.notin_(terminal_excluded),
            )
        )
        or 0.0
    )
    return {"daily_usd": round(daily, 6), "monthly_usd": round(monthly, 6)}


async def maybe_emit_spend_alerts(
    session: AsyncSession, *, organization_id: str
) -> list[Any]:
    policy = await get_three_d_policy(session)
    spend = await spend_snapshot(session)
    threshold = float(policy["owner_alert_threshold_pct"]) / 100.0
    moment = now()
    alerts: list[Any] = []
    checks = (
        (
            "daily",
            spend["daily_usd"],
            float(policy["daily_spend_limit_usd"]),
            moment.strftime("%Y-%m-%d"),
        ),
        (
            "monthly",
            spend["monthly_usd"],
            float(policy["monthly_spend_limit_usd"]),
            moment.strftime("%Y-%m"),
        ),
    )
    for period, value, limit, bucket in checks:
        if limit <= 0 or value < limit * threshold:
            continue
        severity = "critical" if value >= limit else "warning"
        alerts += await communications.notify_audience(
            session,
            organization_id=organization_id,
            audience="owner",
            event_key=f"3d.spend.{period}",
            category="three-d",
            title=f"3D {period} GPU spend threshold reached",
            message=f"3D {period} GPU spend is ${value:.4f} against the Owner limit of ${limit:.2f}.",
            severity=severity,
            source_type="3d_cost_guard",
            source_id=bucket,
            correlation_id=f"3d-spend:{period}:{bucket}",
            dedupe_prefix=f"3d-spend:{period}:{bucket}",
            payload={"period": period, "spend_usd": value, "limit_usd": limit},
            actor_id=None,
        )
    return alerts


async def provider_outage_alert(
    session: AsyncSession,
    *,
    organization_id: str,
    state: dict[str, Any],
    provider: str = PROVIDER_STATE_RESOURCE,
) -> list[Any]:
    resource_id = _provider_resource(provider)
    return await communications.notify_audience(
        session,
        organization_id=organization_id,
        audience="owner",
        event_key="3d.provider.circuit_open",
        category="three-d",
        title="3D GPU provider circuit opened",
        message="AIOS paused new 3D GPU submissions after repeated provider failures. Recovery will be probed automatically.",
        severity="critical",
        source_type="3d_provider_runtime",
        source_id=resource_id,
        correlation_id=f"3d-provider:{resource_id}:{state.get('opened_at')}",
        dedupe_prefix=f"3d-provider-open:{resource_id}:{str(state.get('opened_at'))[:16]}",
        payload={
            "provider": resource_id,
            "state": state.get("state"),
            "open_until": state.get("open_until"),
            "failures": state.get("consecutive_failures"),
        },
        actor_id=None,
    )


async def cleanup_expired_three_d_data(
    session: AsyncSession, storage: ThreeDObjectStore
) -> dict[str, int]:
    policy = await get_three_d_policy(session)
    batch = int(policy["cleanup_batch_size"])
    moment = now()
    expired = list(
        (
            await session.scalars(
                select(ThreeDArtifact)
                .where(
                    ThreeDArtifact.status == "ready",
                    ThreeDArtifact.expires_at.is_not(None),
                    ThreeDArtifact.expires_at <= moment,
                )
                .order_by(ThreeDArtifact.expires_at)
                .limit(batch)
            )
        ).all()
    )
    artifacts_deleted = 0
    for artifact in expired:
        await asyncio.to_thread(storage.delete, artifact.object_key)
        artifact.status = "expired"
        artifacts_deleted += 1
        session.add(
            AuditEvent(
                organization_id=artifact.organization_id,
                user_id=None,
                action="3d.artifact.expired",
                resource_type="three_d_artifact",
                resource_id=artifact.id,
                details={
                    "project_id": artifact.project_id,
                    "size_bytes": artifact.size_bytes,
                },
            )
        )
    stale_before = moment - timedelta(
        hours=int(policy["temporary_input_retention_hours"])
    )
    stale_jobs = list(
        (
            await session.scalars(
                select(ThreeDGenerationJob)
                .where(
                    ThreeDGenerationJob.updated_at <= stale_before,
                    ThreeDGenerationJob.status.in_(
                        {"completed", "failed", "cancelled"}
                    ),
                )
                .order_by(ThreeDGenerationJob.updated_at)
                .limit(batch)
            )
        ).all()
    )
    stale_inputs_deleted = 0
    for job in stale_jobs:
        await asyncio.to_thread(storage.delete, job.input_object_key)
        stale_inputs_deleted += 1
    await session.commit()
    return {
        "artifacts_expired": artifacts_deleted,
        "stale_inputs_cleaned": stale_inputs_deleted,
    }


async def operations_snapshot(session: AsyncSession) -> dict[str, Any]:
    policy = await get_three_d_policy(session)
    provider_circuits = {
        provider: await provider_circuit_snapshot(session, provider=provider)
        for provider in sorted(SUPPORTED_PROVIDER_RESOURCES)
    }
    circuit = provider_circuits[PROVIDER_STATE_RESOURCE]
    spend = await spend_snapshot(session)
    rows = list((await session.scalars(select(ThreeDGenerationJob))).all())
    completed = [row for row in rows if row.status == "completed"]
    failed = [row for row in rows if row.status == "failed"]
    cancelled = [row for row in rows if row.status == "cancelled"]
    active = [
        row for row in rows if row.status in {"queued", "running", "cancel_requested"}
    ]
    terminal = completed + failed
    success_rate = (len(completed) / len(terminal) * 100.0) if terminal else 100.0
    durations = [
        max(0.0, (row.completed_at - row.started_at).total_seconds())
        for row in completed
        if row.completed_at and row.started_at
    ]
    gpu = [
        float(row.provider_execution_ms or 0) / 1000.0
        for row in completed
        if row.provider_execution_ms is not None
    ]
    cold = [
        float(row.provider_delay_ms or 0) / 1000.0
        for row in completed
        if row.provider_delay_ms is not None
    ]

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    return {
        "circuit": circuit,
        "provider_circuits": provider_circuits,
        "spend": {
            **spend,
            "daily_limit_usd": policy["daily_spend_limit_usd"],
            "monthly_limit_usd": policy["monthly_spend_limit_usd"],
            "alert_threshold_pct": policy["owner_alert_threshold_pct"],
        },
        "jobs": {
            "total": len(rows),
            "active": len(active),
            "completed": len(completed),
            "failed": len(failed),
            "cancelled": len(cancelled),
            "success_rate_pct": round(success_rate, 2),
            "avg_duration_seconds": avg(durations),
            "avg_gpu_runtime_seconds": avg(gpu),
            "avg_provider_delay_seconds": avg(cold),
        },
        "cleanup": {
            "artifact_retention_days": policy["artifact_retention_days"],
            "temporary_input_retention_hours": policy[
                "temporary_input_retention_hours"
            ],
            "interval_seconds": policy["cleanup_interval_seconds"],
        },
    }


async def prometheus_snapshot(session: AsyncSession) -> str:
    snap = await operations_snapshot(session)
    jobs = snap["jobs"]
    spend = snap["spend"]
    provider_circuits = snap["provider_circuits"]
    lines = [
        "# HELP aionex_3d_jobs_total Current durable 3D job count by terminal state.",
        "# TYPE aionex_3d_jobs_total gauge",
        f'aionex_3d_jobs_total{{status="completed"}} {jobs["completed"]}',
        f'aionex_3d_jobs_total{{status="failed"}} {jobs["failed"]}',
        f'aionex_3d_jobs_total{{status="cancelled"}} {jobs["cancelled"]}',
        f'aionex_3d_jobs_total{{status="active"}} {jobs["active"]}',
        "# TYPE aionex_3d_success_rate_percent gauge",
        f'aionex_3d_success_rate_percent {jobs["success_rate_pct"]}',
        "# TYPE aionex_3d_job_duration_seconds gauge",
        f'aionex_3d_job_duration_seconds {jobs["avg_duration_seconds"]}',
        "# TYPE aionex_3d_gpu_runtime_seconds gauge",
        f'aionex_3d_gpu_runtime_seconds {jobs["avg_gpu_runtime_seconds"]}',
        "# TYPE aionex_3d_provider_cold_start_seconds gauge",
        f'aionex_3d_provider_cold_start_seconds {jobs["avg_provider_delay_seconds"]}',
        "# TYPE aionex_3d_provider_circuit_state gauge",
        *[
            f'aionex_3d_provider_circuit_state{{provider="{provider}"}} '
            + str(
                0
                if state["state"] == "closed"
                else 1 if state["state"] == "half_open" else 2
            )
            for provider, state in provider_circuits.items()
        ],
        "# TYPE aionex_3d_spend_usd gauge",
        f'aionex_3d_spend_usd{{period="daily"}} {spend["daily_usd"]}',
        f'aionex_3d_spend_usd{{period="monthly"}} {spend["monthly_usd"]}',
    ]
    return "\n".join(lines) + "\n"
