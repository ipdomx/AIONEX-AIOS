"""Live production operations, observability, and assurance helpers for Phase 29G.

This module deliberately avoids Docker-socket access. Runtime inventory is derived
from the current host, configured service endpoints, PostgreSQL, Redis, and live
network probes. Destructive host/container operations fail closed unless an
explicit deployment control plane is added in a later approved architecture.
"""

from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.models import AuditEvent, MetricSample, OwnerControlRecord, RefreshSession, User
from app.db.redis import get_redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

HEALTHY = {"healthy", "ready", "ok", "operational"}


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    current = value or now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _read_float(path: str, fallback: float = 0.0) -> float:
    try:
        return float(Path(path).read_text(encoding="utf-8").strip().split()[0])
    except (OSError, ValueError, IndexError):
        return fallback


def host_snapshot() -> dict[str, Any]:
    uptime = _read_float("/proc/uptime")
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0
    cpu_count = max(1, os.cpu_count() or 1)
    memory_total = memory_available = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            amount = int(value.strip().split()[0]) * 1024
            if key == "MemTotal":
                memory_total = amount
            elif key == "MemAvailable":
                memory_available = amount
    except (OSError, ValueError, IndexError):
        pass
    memory_used = max(0, memory_total - memory_available)
    try:
        stat = os.statvfs("/")
        disk_total = stat.f_frsize * stat.f_blocks
        disk_free = stat.f_frsize * stat.f_bavail
    except OSError:
        disk_total = disk_free = 0
    disk_used = max(0, disk_total - disk_free)
    return {
        "id": "runtime-node",
        "name": socket.gethostname(),
        "hostname": socket.gethostname(),
        "ip": None,
        "status": "online",
        "os": f"{platform.system()} {platform.release()}",
        "cpu_usage": round(min(100.0, load1 / cpu_count * 100.0), 2),
        "memory_usage": round((memory_used / memory_total * 100.0), 2) if memory_total else 0.0,
        "disk_usage": round((disk_used / disk_total * 100.0), 2) if disk_total else 0.0,
        "network_rx": 0.0,
        "network_tx": 0.0,
        "uptime": int(uptime),
        "location": os.getenv("AIOS_REGION", "configured-runtime"),
        "provider": os.getenv("AIOS_INFRA_PROVIDER", "self-managed"),
        "load": {"1m": load1, "5m": load5, "15m": load15},
        "memory": {"total_bytes": memory_total, "used_bytes": memory_used},
        "disk": {"total_bytes": disk_total, "used_bytes": disk_used, "free_bytes": disk_free},
        "control_mode": "protected",
        "created_at": iso(),
    }


async def tcp_probe(host: str, port: int, timeout: float = 1.5) -> tuple[bool, float | None]:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        del reader
        return True, round((time.perf_counter() - started) * 1000, 2)
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return False, None


async def database_snapshot(session: AsyncSession) -> dict[str, Any]:
    started = time.perf_counter()
    await session.execute(text("SELECT 1"))
    latency = round((time.perf_counter() - started) * 1000, 2)
    dialect = session.get_bind().dialect.name
    database_size = connections = tables = 0
    if dialect == "postgresql":
        database_size = int(await session.scalar(text("SELECT pg_database_size(current_database())")) or 0)
        connections = int(
            await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()")) or 0
        )
        tables = int(
            await session.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
            )
            or 0
        )
    return {
        "id": "postgres-primary",
        "name": settings.POSTGRES_DB,
        "type": dialect,
        "host": settings.POSTGRES_HOST,
        "port": settings.POSTGRES_PORT,
        "status": "connected",
        "size": round(database_size / (1024 * 1024), 2),
        "connections": connections,
        "queries_per_second": 0,
        "slow_queries": 0,
        "backup_status": "managed",
        "last_backup": None,
        "tables": tables,
        "latency_ms": latency,
        "created_at": iso(),
    }


async def redis_snapshot() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        redis = await get_redis()
        healthy = bool(await redis.ping())
        latency = round((time.perf_counter() - started) * 1000, 2)
        try:
            info = await redis.info("memory")
            used_memory = int(info.get("used_memory", 0))
        except Exception:
            used_memory = 0
        return {
            "id": "redis-primary",
            "name": "Redis",
            "type": "redis",
            "host": "redis",
            "port": 6379,
            "status": "connected" if healthy else "error",
            "size": round(used_memory / (1024 * 1024), 2),
            "connections": 0,
            "queries_per_second": 0,
            "slow_queries": 0,
            "backup_status": "not-applicable",
            "last_backup": None,
            "latency_ms": latency,
            "created_at": iso(),
        }
    except Exception:
        return {
            "id": "redis-primary",
            "name": "Redis",
            "type": "redis",
            "host": "redis",
            "port": 6379,
            "status": "error",
            "size": 0.0,
            "connections": 0,
            "queries_per_second": 0,
            "slow_queries": 0,
            "backup_status": "not-applicable",
            "last_backup": None,
            "latency_ms": None,
            "created_at": iso(),
        }


async def service_inventory(session: AsyncSession) -> list[dict[str, Any]]:
    db = await database_snapshot(session)
    redis = await redis_snapshot()
    probes = [
        ("backend", "Backend API", "backend", 8000, "application"),
        ("frontend", "Owner Dashboard", "frontend", 3000, "application"),
        ("portal", "User Portal", "portal", 3000, "application"),
        ("nginx-public", "Nginx Public", "nginx", 8080, "gateway"),
        ("nginx-owner", "Nginx Owner", "nginx", 8081, "gateway"),
        ("nginx-portal", "Nginx Portal", "nginx", 8082, "gateway"),
    ]
    results = await asyncio.gather(*(tcp_probe(host, port) for _, _, host, port, _ in probes))
    rows: list[dict[str, Any]] = []
    for (component_id, name, host, port, kind), (healthy, latency) in zip(probes, results):
        rows.append(
            {
                "id": component_id,
                "name": name,
                "image": "runtime-managed",
                "status": "running" if healthy else "unavailable",
                "server": socket.gethostname(),
                "cpu": 0.0,
                "memory": 0,
                "restart_count": None,
                "health": "healthy" if healthy else "unhealthy",
                "created_at": iso(),
                "kind": kind,
                "endpoint": f"{host}:{port}",
                "latency_ms": latency,
                "control_supported": False,
                "control_reason": "Direct Docker/host control is intentionally not delegated to the application container.",
            }
        )
    rows.extend(
        [
            {
                "id": db["id"],
                "name": "PostgreSQL",
                "image": "postgresql",
                "status": "running" if db["status"] == "connected" else "unavailable",
                "server": socket.gethostname(),
                "cpu": 0.0,
                "memory": 0,
                "restart_count": None,
                "health": "healthy" if db["status"] == "connected" else "unhealthy",
                "created_at": iso(),
                "kind": "database",
                "endpoint": f"{db['host']}:{db['port']}",
                "latency_ms": db.get("latency_ms"),
                "control_supported": False,
                "control_reason": "Database lifecycle is protected; backup/recovery uses the dedicated governed API.",
            },
            {
                "id": redis["id"],
                "name": "Redis",
                "image": "redis",
                "status": "running" if redis["status"] == "connected" else "unavailable",
                "server": socket.gethostname(),
                "cpu": 0.0,
                "memory": 0,
                "restart_count": None,
                "health": "healthy" if redis["status"] == "connected" else "unhealthy",
                "created_at": iso(),
                "kind": "cache",
                "endpoint": f"{redis['host']}:{redis['port']}",
                "latency_ms": redis.get("latency_ms"),
                "control_supported": False,
                "control_reason": "Core cache lifecycle is protected from application-level stop/restart commands.",
            },
        ]
    )
    return rows


async def record_observation_cycle(session: AsyncSession) -> list[MetricSample]:
    host = host_snapshot()
    db = await database_snapshot(session)
    redis = await redis_snapshot()
    inventory = await service_inventory(session)
    status = "healthy" if all(item["health"] == "healthy" for item in inventory) else "degraded"
    samples = [
        MetricSample(name="runtime.cpu.percent", resource="runtime-node", value=float(host["cpu_usage"]), labels={"status": "healthy"}),
        MetricSample(name="runtime.memory.percent", resource="runtime-node", value=float(host["memory_usage"]), labels={"status": "healthy"}),
        MetricSample(name="runtime.disk.percent", resource="runtime-node", value=float(host["disk_usage"]), labels={"status": "healthy"}),
        MetricSample(name="postgres.latency.ms", resource="postgres-primary", value=float(db.get("latency_ms") or 0.0), labels={"status": "healthy" if db["status"] == "connected" else "critical"}),
        MetricSample(name="redis.latency.ms", resource="redis-primary", value=float(redis.get("latency_ms") or 0.0), labels={"status": "healthy" if redis["status"] == "connected" else "critical"}),
        MetricSample(name="runtime.components.healthy", resource="platform", value=float(sum(item["health"] == "healthy" for item in inventory)), labels={"status": status, "total": str(len(inventory))}),
    ]
    session.add_all(samples)
    session.add(
        AuditEvent(
            organization_id=None,
            user_id=None,
            action="operations.observation",
            resource_type="runtime",
            resource_id="platform",
            details={
                "level": "info" if status == "healthy" else "warning",
                "service": "operations-observer",
                "message": f"Observed {len(inventory)} production components",
                "trace_id": f"obs-{int(time.time())}",
                "status": status,
                "healthy_components": sum(item["health"] == "healthy" for item in inventory),
                "total_components": len(inventory),
            },
        )
    )
    cutoff = now() - timedelta(days=30)
    await session.execute(
        MetricSample.__table__.delete().where(MetricSample.timestamp < cutoff)
    )
    return samples


async def runtime_topology(session: AsyncSession) -> dict[str, Any]:
    inventory = await service_inventory(session)
    nodes = [
        {
            "id": item["id"],
            "name": item["name"],
            "kind": item["kind"],
            "health": item["health"],
            "endpoint": item["endpoint"],
        }
        for item in inventory
    ]
    edges = [
        {"from": "nginx-public", "to": "backend", "protocol": "http"},
        {"from": "nginx-owner", "to": "backend", "protocol": "http"},
        {"from": "nginx-owner", "to": "frontend", "protocol": "http"},
        {"from": "nginx-portal", "to": "portal", "protocol": "http"},
        {"from": "backend", "to": "postgres-primary", "protocol": "postgresql"},
        {"from": "backend", "to": "redis-primary", "protocol": "redis"},
    ]
    return {"generated_at": iso(), "nodes": nodes, "edges": edges}


async def security_events(
    session: AsyncSession,
    *,
    organization_id: str,
    super_owner: bool,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(AuditEvent).where(AuditEvent.action == "security.event")
    if not super_owner:
        statement = statement.where(AuditEvent.organization_id == organization_id)
    rows = list((await session.scalars(statement.order_by(AuditEvent.created_at.desc()).limit(limit))).all())
    result = []
    for row in rows:
        details = row.details or {}
        score = int(details.get("risk_score", 0))
        result.append(
            {
                "id": row.id,
                "timestamp": iso(row.created_at),
                "type": details.get("event_type", "security.event"),
                "risk_score": score,
                "risk_level": "critical" if score >= 80 else "high" if score >= 60 else "medium" if score >= 30 else "low",
                "result": details.get("result", "detected"),
                "user_id": row.user_id,
                "ip": row.ip_address,
                "organization_id": row.organization_id,
            }
        )
    return result


async def revoke_refresh_session(
    session: AsyncSession,
    *,
    session_id: str,
    actor_id: str,
    organization_id: str,
    super_owner: bool,
) -> RefreshSession | None:
    statement = (
        select(RefreshSession)
        .join(User, User.id == RefreshSession.user_id)
        .where(RefreshSession.id == session_id)
    )
    if not super_owner:
        statement = statement.where(User.organization_id == organization_id)
    record = await session.scalar(statement.with_for_update())
    if record is None:
        return None
    if record.revoked_at is None:
        record.revoked_at = now()
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="security.session.revoked",
            resource_type="refresh_session",
            resource_id=record.id,
            details={"status": "completed"},
        )
    )
    return record


async def maintenance_record(session: AsyncSession) -> OwnerControlRecord:
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == "runtime-maintenance",
            OwnerControlRecord.resource_id == "runtime-node",
        )
    )
    if record is None:
        record = OwnerControlRecord(
            domain="runtime-maintenance",
            resource_id="runtime-node",
            status="active",
            enabled=False,
            payload={"name": socket.gethostname(), "maintenance": False},
            version=1,
        )
        session.add(record)
        await session.flush()
    return record
