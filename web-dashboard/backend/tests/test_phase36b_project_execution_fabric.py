"""Phase 36B distributed live project-execution acceptance contracts."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import redis.asyncio as aioredis
from sqlalchemy import delete, func, select

from app.core.config import Settings, settings
from app.db.base import Base, SessionLocal
from app.db.models import (
    AuditEvent,
    Notification,
    Organization,
    Project,
    ProjectExecution,
    ProjectExecutionWorkerNode,
    User,
    Workspace,
)
from app.services import project_execution_admission as admission_module
from app.services.project_execution_admission import (
    ProjectExecutionAdmissionUnavailable,
    project_execution_admission_slot,
)
from app.services.project_execution_worker import (
    ProjectExecutionLeaseLost,
    ProjectExecutionWorker,
)


class _UnusedRunner:
    def run(self, **_kwargs):  # pragma: no cover - claims are completed directly here
        raise AssertionError("Phase 36B scheduler test must not invoke a provider runner")


class _ConcurrentRunner:
    """Fake-provider runner that proves two live executions overlap in wall time."""

    def __init__(self) -> None:
        self._barrier = threading.Barrier(2)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, **payload):
        callback = payload["stage_callback"]
        callback("provider_execution", 40)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self._barrier.wait(timeout=10)
            time.sleep(0.05)
            callback("release_review", 95)
            return {
                "success": True,
                "phase": 36,
                "mode": "full",
                "provider": "synthetic-fake-provider",
                "model": "none",
                "requests_count": 0,
                "retries_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calculated_cost": 0.0,
                "approved": True,
                "readiness_score": 1.0,
                "workforce": [],
                "all_governance_layers_executed": True,
                "production_modified": False,
            }
        finally:
            with self._lock:
                self.active -= 1


async def _seed_execution(
    suffix: str,
    *,
    max_attempts: int = 3,
    priority_rank: int = 200,
) -> tuple[Organization, User, Workspace, Project, ProjectExecution]:
    organization = Organization(
        id=f"p36b-org-{suffix}",
        name=f"Phase 36B {suffix}",
        slug=f"p36b-org-{suffix}",
        plan="enterprise",
        status="active",
    )
    user = User(
        id=f"p36b-user-{suffix}",
        organization_id=organization.id,
        role_id=None,
        email=f"p36b-{suffix}@example.com",
        name="Phase 36B Operator",
        password_hash="unused",
        status="active",
    )
    workspace = Workspace(
        id=f"p36b-ws-{suffix}",
        organization_id=organization.id,
        name="Phase 36B Workspace",
        slug=f"p36b-ws-{suffix}",
        status="active",
    )
    project = Project(
        id=f"p36b-project-{suffix}",
        organization_id=organization.id,
        workspace_id=workspace.id,
        owner_id=user.id,
        name="Distributed Project",
        slug=f"p36b-project-{suffix}",
        description="Exercise the durable distributed project execution fabric.",
        status="planning",
        priority="high",
        progress=0,
        tags=["phase36b"],
    )
    execution = ProjectExecution(
        id=f"p36b-exec-{suffix}",
        organization_id=organization.id,
        workspace_id=workspace.id,
        project_id=project.id,
        requested_by_id=user.id,
        mode="full",
        provider="openai",
        status="queued",
        stage="queued",
        progress=0,
        objective=project.description,
        external_processing_confirmed=True,
        budget_cap_usd=0.05,
        result_summary={},
        resource_class="project-build-cpu",
        priority_rank=priority_rank,
        attempts=0,
        max_attempts=max_attempts,
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        session.add_all([user, workspace])
        await session.flush()
        session.add(project)
        await session.flush()
        session.add(execution)
        await session.commit()
    return organization, user, workspace, project, execution


async def _cleanup_org(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.organization_id == organization_id)
        )
        await session.execute(
            delete(Notification).where(Notification.organization_id == organization_id)
        )
        await session.execute(
            delete(ProjectExecution).where(
                ProjectExecution.organization_id == organization_id
            )
        )
        await session.execute(delete(Project).where(Project.organization_id == organization_id))
        await session.execute(
            delete(Workspace).where(Workspace.organization_id == organization_id)
        )
        await session.execute(delete(User).where(User.organization_id == organization_id))
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()


async def _delete_workers(*worker_ids: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(ProjectExecutionWorkerNode).where(
                ProjectExecutionWorkerNode.id.in_(worker_ids)
            )
        )
        await session.commit()


def test_project_admission_requires_redis_pool_headroom() -> None:
    with pytest.raises(ValueError, match="must leave at least two Redis connections"):
        Settings(
            _env_file=None,
            SECRET_KEY="phase36b-settings-secret-key-with-at-least-32-characters",
            PROJECT_EXECUTION_ADMISSION_CONCURRENCY=12,
            REDIS_POOL_SIZE=12,
        )


def test_phase36b_schema_has_live_fabric_contract() -> None:
    executions = Base.metadata.tables["project_executions"]
    workers = Base.metadata.tables["project_execution_workers"]
    for column in (
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "resource_class",
        "priority_rank",
        "available_at",
        "dead_lettered_at",
    ):
        assert column in executions.c
    assert "last_heartbeat_at" in workers.c
    assert "active_count" in workers.c
    assert any(
        index.name == "ix_project_executions_dispatch_queue"
        for index in executions.indexes
    )
    assert any(
        index.name == "ix_project_executions_lease_recovery"
        for index in executions.indexes
    )


@pytest.mark.asyncio
async def test_project_admission_fails_closed_in_production_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable_redis():
        raise RuntimeError("redis is intentionally unavailable")

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(admission_module, "get_redis", unavailable_redis)
    with pytest.raises(ProjectExecutionAdmissionUnavailable):
        async with project_execution_admission_slot():
            raise AssertionError("production admission must not open without Redis")


@pytest.mark.asyncio
async def test_two_workers_execute_distinct_live_workflows_without_global_singleton() -> None:
    left_suffix = uuid4().hex[:8]
    right_suffix = uuid4().hex[:8]
    left_org, *_ = await _seed_execution(left_suffix, priority_rank=300)
    right_org, *_ = await _seed_execution(right_suffix, priority_rank=300)
    worker_a_id = f"phase36b-worker-a-{left_suffix}"
    worker_b_id = f"phase36b-worker-b-{right_suffix}"
    runner = _ConcurrentRunner()
    worker_a = ProjectExecutionWorker(runner=runner, worker_id=worker_a_id, capacity=1)
    worker_b = ProjectExecutionWorker(runner=runner, worker_id=worker_b_id, capacity=1)
    try:
        claim_a = await worker_a.claim()
        claim_b = await worker_b.claim()
        assert claim_a is not None
        assert claim_b is not None
        assert claim_a[0] != claim_b[0]

        await asyncio.gather(
            worker_a.execute_claim(*claim_a),
            worker_b.execute_claim(*claim_b),
        )
        assert runner.max_active == 2

        async with SessionLocal() as session:
            rows = list(
                (
                    await session.scalars(
                        select(ProjectExecution).where(
                            ProjectExecution.id.in_([claim_a[0], claim_b[0]])
                        )
                    )
                ).all()
            )
            assert len(rows) == 2
            assert {row.status for row in rows} == {"completed"}
            assert {row.lease_owner for row in rows} == {None}
            assert {row.attempts for row in rows} == {1}
            assert all(row.approved is True for row in rows)
    finally:
        await _cleanup_org(left_org.id)
        await _cleanup_org(right_org.id)
        await _delete_workers(worker_a_id, worker_b_id)


@pytest.mark.asyncio
async def test_expired_lease_recovery_rotates_token_and_rejects_stale_commit() -> None:
    suffix = uuid4().hex[:8]
    organization, *_ = await _seed_execution(suffix, max_attempts=3)
    worker_a_id = f"phase36b-recovery-a-{suffix}"
    worker_b_id = f"phase36b-recovery-b-{suffix}"
    worker_a = ProjectExecutionWorker(
        runner=_UnusedRunner(), worker_id=worker_a_id, capacity=1
    )
    worker_b = ProjectExecutionWorker(
        runner=_UnusedRunner(), worker_id=worker_b_id, capacity=1
    )
    try:
        first = await worker_a.claim()
        assert first is not None
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, first[0])
            assert row is not None
            first_fence = row.fencing_token
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        recovered = await worker_b.claim()
        assert recovered is not None
        assert recovered[0] == first[0]
        assert recovered[1] != first[1]

        with pytest.raises(ProjectExecutionLeaseLost):
            await worker_a.complete(first[0], first[1], {"approved": True})

        await worker_b.complete(
            recovered[0],
            recovered[1],
            {
                "success": True,
                "phase": 36,
                "mode": "full",
                "approved": True,
                "readiness_score": 1.0,
                "workforce": [],
                "production_modified": False,
            },
        )
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, recovered[0])
            assert row is not None
            assert row.status == "completed"
            assert row.fencing_token == first_fence + 1
            assert row.attempts == 2
            assert row.lease_owner is None
            assert row.lease_expires_at is None
    finally:
        await _cleanup_org(organization.id)
        await _delete_workers(worker_a_id, worker_b_id)


@pytest.mark.asyncio
async def test_killed_worker_process_is_recovered_by_another_worker(tmp_path) -> None:
    suffix = uuid4().hex[:8]
    organization, *_ = await _seed_execution(suffix, max_attempts=3)
    killed_worker_id = f"phase36b-killed-{suffix}"
    recovery_worker_id = f"phase36b-recovery-{suffix}"
    child_code = r"""
import asyncio
import os

from app.services.project_execution_worker import ProjectExecutionWorker

class NoRun:
    def run(self, **_kwargs):
        raise AssertionError("killed worker must never execute provider work")

async def main():
    worker = ProjectExecutionWorker(
        runner=NoRun(),
        worker_id=os.environ["P36B_CHILD_WORKER_ID"],
        capacity=1,
    )
    claim = await worker.claim()
    if claim is None:
        raise RuntimeError("no project execution was claimable")
    print(claim[0], flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
"""
    environment = os.environ.copy()
    environment["P36B_CHILD_WORKER_ID"] = killed_worker_id
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        child_code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        assert process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), timeout=15)
        execution_id = line.decode("utf-8").strip()
        assert execution_id
        async with SessionLocal() as session:
            claimed = await session.get(ProjectExecution, execution_id)
            assert claimed is not None
            assert claimed.lease_token
            stale_token = claimed.lease_token


        process.send_signal(signal.SIGKILL)
        return_code = await asyncio.wait_for(process.wait(), timeout=10)
        assert return_code < 0

        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, execution_id)
            assert row is not None
            assert row.status == "running"
            assert row.lease_owner == killed_worker_id
            first_fence = row.fencing_token
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        recovery = ProjectExecutionWorker(
            runner=_UnusedRunner(), worker_id=recovery_worker_id, capacity=1
        )
        recovered = await recovery.claim()
        assert recovered is not None
        assert recovered[0] == execution_id
        assert recovered[1] != stale_token
        stale_worker = ProjectExecutionWorker(
            runner=_UnusedRunner(), worker_id=killed_worker_id, capacity=1
        )
        with pytest.raises(ProjectExecutionLeaseLost):
            await stale_worker.complete(
                execution_id, stale_token, {"approved": True}
            )
        await recovery.complete(
            recovered[0],
            recovered[1],
            {
                "success": True,
                "phase": 36,
                "mode": "full",
                "approved": True,
                "readiness_score": 1.0,
                "workforce": [],
                "production_modified": False,
            },
        )
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, execution_id)
            assert row is not None
            assert row.status == "completed"
            assert row.fencing_token == first_fence + 1
            assert row.attempts == 2
            assert row.lease_owner is None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await _cleanup_org(organization.id)
        await _delete_workers(killed_worker_id, recovery_worker_id)


@pytest.mark.asyncio
async def test_transient_retry_exhaustion_enters_dead_letter_and_metrics() -> None:
    suffix = uuid4().hex[:8]
    organization, *_ = await _seed_execution(suffix, max_attempts=2)
    worker_id = f"phase36b-retry-{suffix}"
    worker = ProjectExecutionWorker(
        runner=_UnusedRunner(), worker_id=worker_id, capacity=2
    )
    try:
        await worker.register_worker(active_count=1)
        first = await worker.claim()
        assert first is not None
        await worker.fail(first[0], first[1], ConnectionError("synthetic transient"))
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, first[0])
            assert row is not None
            assert row.status == "queued"
            assert row.stage == "retry_queued"
            assert row.attempts == 1
            row.available_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        second = await worker.claim()
        assert second is not None
        assert second[0] == first[0]
        await worker.fail(second[0], second[1], ConnectionError("synthetic transient"))
        async with SessionLocal() as session:
            row = await session.get(ProjectExecution, first[0])
            assert row is not None
            assert row.status == "failed"
            assert row.stage == "dead_lettered"
            assert row.dead_lettered_at is not None
            assert row.attempts == 2

        snapshot = await worker.fabric_snapshot()
        assert snapshot["dead_lettered"] >= 1
        assert snapshot["workers_online"] >= 1
        assert snapshot["worker_capacity"] >= 2
    finally:
        await worker.mark_worker_stopped()
        await _cleanup_org(organization.id)
        await _delete_workers(worker_id)


@pytest.mark.asyncio
async def test_one_thousand_concurrent_tenant_jobs_are_durably_admitted_without_loss() -> None:
    batch = uuid4().hex[:8]
    count = 1000
    shards = 4
    per_shard = count // shards
    admission_key = f"aionex:phase36b:test-admission:{batch}"
    org_prefix = f"p36bl-{batch}-"
    user_prefix = f"p36bu-{batch}-"
    workspace_prefix = f"p36bw-{batch}-"
    project_prefix = f"p36bp-{batch}-"
    execution_prefix = f"p36be-{batch}-"

    organizations = [
        Organization(
            id=f"{org_prefix}{index}",
            name=f"Phase36B Load Tenant {index}",
            slug=f"p36b-load-{batch}-{index}",
            plan="enterprise",
            status="active",
        )
        for index in range(count)
    ]
    users = [
        User(
            id=f"{user_prefix}{index}",
            organization_id=f"{org_prefix}{index}",
            role_id=None,
            email=f"p36b-load-{batch}-{index}@example.com",
            name="Synthetic Load User",
            password_hash="unused",
            status="active",
        )
        for index in range(count)
    ]
    workspaces = [
        Workspace(
            id=f"{workspace_prefix}{index}",
            organization_id=f"{org_prefix}{index}",
            name="Synthetic Workspace",
            slug=f"p36b-load-ws-{batch}-{index}",
            status="active",
        )
        for index in range(count)
    ]
    projects = [
        Project(
            id=f"{project_prefix}{index}",
            organization_id=f"{org_prefix}{index}",
            workspace_id=f"{workspace_prefix}{index}",
            owner_id=f"{user_prefix}{index}",
            name=f"Synthetic Project {index}",
            slug=f"p36b-load-project-{batch}-{index}",
            description="Synthetic Phase 36B multi-process admission workload.",
            status="planning",
            priority="medium",
            progress=0,
            tags=["phase36b", "synthetic-load"],
        )
        for index in range(count)
    ]
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=4,
    )
    processes: list[asyncio.subprocess.Process] = []
    try:
        await redis_client.delete(admission_key)
        async with SessionLocal() as session:
            session.add_all(organizations)
            await session.flush()
            session.add_all(users)
            await session.flush()
            session.add_all(workspaces)
            await session.flush()
            session.add_all(projects)
            await session.commit()

        child = Path(__file__).with_name("phase36b_admission_process.py")
        start_epoch = time.time() + 1.5
        for shard in range(shards):
            environment = os.environ.copy()
            environment.update(
                {
                    "DATABASE_POOLING_ENABLED": "true",
                    "DATABASE_POOL_SIZE": "12",
                    "DATABASE_MAX_OVERFLOW": "2",
                    "DATABASE_POOL_TIMEOUT_SECONDS": "5",
                    "DATABASE_POOL_CONNECTION_BUDGET": "60",
                    "WORKERS": "4",
                    "REDIS_POOL_SIZE": "18",
                    "PROJECT_EXECUTION_ADMISSION_CONCURRENCY": "14",
                    "PROJECT_EXECUTION_ADMISSION_GLOBAL_LIMIT": "48",
                    "PROJECT_EXECUTION_ADMISSION_WAIT_SECONDS": "30",
                    "PROJECT_EXECUTION_ADMISSION_REDIS_KEY": admission_key,
                }
            )
            processes.append(
                await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(child),
                    str(shard * per_shard),
                    str((shard + 1) * per_shard),
                    batch,
                    str(start_epoch),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=environment,
                )
            )

        all_ids: list[str] = []
        latencies: list[float] = []
        for process in processes:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
            assert process.returncode == 0, stderr.decode("utf-8", errors="replace")
            result_line = next(
                (
                    line
                    for line in stdout.decode("utf-8", errors="replace").splitlines()
                    if line.startswith("P36B_CHILD_RESULT=")
                ),
                None,
            )
            assert result_line is not None
            payload = json.loads(result_line.split("=", 1)[1])
            all_ids.extend(str(item) for item in payload["ids"])
            latencies.extend(float(item) for item in payload["latencies"])

        assert len(all_ids) == count
        assert len(set(all_ids)) == count
        assert len(latencies) == count
        ordered = sorted(latencies)
        p50 = ordered[int(count * 0.50) - 1]
        p95 = ordered[int(count * 0.95) - 1]
        p99 = ordered[int(count * 0.99) - 1]
        print(
            "P36B_1000_MULTI_PROCESS_ADMISSION "
            f"p50={p50:.3f}s p95={p95:.3f}s p99={p99:.3f}s "
            f"max={ordered[-1]:.3f}s"
        )
        assert p95 < 5.0
        assert int(await redis_client.zcard(admission_key)) == 0

        async with SessionLocal() as session:
            admitted = int(
                await session.scalar(
                    select(func.count(ProjectExecution.id)).where(
                        ProjectExecution.id.like(f"{execution_prefix}%")
                    )
                )
                or 0
            )
            tenants = int(
                await session.scalar(
                    select(func.count(func.distinct(ProjectExecution.organization_id))).where(
                        ProjectExecution.id.like(f"{execution_prefix}%")
                    )
                )
                or 0
            )
            queued = int(
                await session.scalar(
                    select(func.count(ProjectExecution.id)).where(
                        ProjectExecution.id.like(f"{execution_prefix}%"),
                        ProjectExecution.status == "queued",
                    )
                )
                or 0
            )
            attempts = int(
                await session.scalar(
                    select(func.coalesce(func.sum(ProjectExecution.attempts), 0)).where(
                        ProjectExecution.id.like(f"{execution_prefix}%")
                    )
                )
                or 0
            )
            assert admitted == count
            assert tenants == count
            assert queued == count
            assert attempts == 0
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()
        await redis_client.delete(admission_key)
        await redis_client.close()
        async with SessionLocal() as session:
            await session.execute(
                delete(ProjectExecution).where(
                    ProjectExecution.id.like(f"{execution_prefix}%")
                )
            )
            await session.execute(
                delete(Project).where(Project.id.like(f"{project_prefix}%"))
            )
            await session.execute(
                delete(Workspace).where(Workspace.id.like(f"{workspace_prefix}%"))
            )
            await session.execute(delete(User).where(User.id.like(f"{user_prefix}%")))
            await session.execute(
                delete(Organization).where(Organization.id.like(f"{org_prefix}%"))
            )
            await session.commit()
