from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import OwnerControlRecord
from app.services.three_d_policy import DEFAULT_THREE_D_POLICY, normalize_three_d_policy
from app.services.three_d_resilience import (
    PROVIDER_STATE_DOMAIN,
    assert_provider_available,
    normalize_idempotency_key,
    normalize_trace_id,
    operations_snapshot,
    provider_circuit_snapshot,
    record_provider_failure,
    record_provider_success,
    request_fingerprint,
)


def test_phase34e_policy_normalizes_resilience_controls():
    policy = normalize_three_d_policy(
        {
            **DEFAULT_THREE_D_POLICY,
            "duplicate_window_seconds": 1,
            "provider_failure_threshold": 99,
            "provider_circuit_open_seconds": 1,
            "cleanup_interval_seconds": 1,
            "cleanup_batch_size": 9999,
            "temporary_input_retention_hours": 999,
        }
    )
    assert policy["duplicate_window_seconds"] == 30
    assert policy["provider_failure_threshold"] == 20
    assert policy["provider_circuit_open_seconds"] == 30
    assert policy["cleanup_interval_seconds"] == 30
    assert policy["cleanup_batch_size"] == 1000
    assert policy["temporary_input_retention_hours"] == 168


def test_request_fingerprint_and_automatic_idempotency_are_stable_within_window(
    monkeypatch,
):
    fingerprint = request_fingerprint(
        organization_id="o",
        user_id="u",
        project_id="p",
        image_sha256="a" * 64,
        seed=7,
        texture_size=1024,
        compression_policy="compat",
    )
    assert len(fingerprint) == 64
    explicit1 = normalize_idempotency_key(
        "client-key",
        fingerprint=fingerprint,
        namespace="org:user:project",
        window_seconds=600,
    )
    explicit2 = normalize_idempotency_key(
        "client-key",
        fingerprint=fingerprint,
        namespace="org:user:project",
        window_seconds=600,
    )
    assert explicit1 == explicit2 and len(explicit1) == 64
    auto1 = normalize_idempotency_key(
        None, fingerprint=fingerprint, namespace="org:user:project", window_seconds=600
    )
    auto2 = normalize_idempotency_key(
        None, fingerprint=fingerprint, namespace="org:user:project", window_seconds=600
    )
    assert auto1 == auto2 and auto1 != fingerprint
    other = normalize_idempotency_key(
        "client-key",
        fingerprint="b" * 64,
        namespace="other-org:user:project",
        window_seconds=600,
    )
    assert other != explicit1
    assert normalize_trace_id("trace-123") == "trace-123"
    long_trace = "x" * 160
    assert len(normalize_trace_id(long_trace)) == 64
    assert normalize_trace_id(long_trace) == normalize_trace_id(long_trace)


def test_idempotency_is_tenant_scoped_and_trace_ids_fit_storage_contract():
    from app.services.three_d_resilience import normalize_trace_id

    fingerprint = "f" * 64
    left = normalize_idempotency_key(
        "same-client-key",
        fingerprint=fingerprint,
        namespace="org-a:user:project",
        window_seconds=600,
    )
    right = normalize_idempotency_key(
        "same-client-key",
        fingerprint=fingerprint,
        namespace="org-b:user:project",
        window_seconds=600,
    )
    assert left != right
    assert normalize_trace_id("trace-123") == "trace-123"
    assert len(normalize_trace_id("x" * 160)) == 64
    with pytest.raises(HTTPException):
        normalize_trace_id("bad\ntrace")


@pytest.mark.asyncio
async def test_provider_circuit_opens_blocks_half_opens_and_recovers():
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN
            )
        )
        policy_row = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == "3d-service-policy",
                OwnerControlRecord.resource_id == "default",
            )
        )
        original_payload = dict(policy_row.payload) if policy_row is not None else None
        if policy_row is None:
            from app.services.three_d_policy import get_three_d_policy

            await get_three_d_policy(session)
            policy_row = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == "3d-service-policy",
                    OwnerControlRecord.resource_id == "default",
                )
            )
        assert policy_row is not None
        policy_row.payload = {
            **dict(policy_row.payload or {}),
            "provider_failure_threshold": 2,
            "provider_circuit_open_seconds": 30,
        }
        await session.commit()
        try:
            first, opened = await record_provider_failure(
                session, error_code="TEST_ONE"
            )
            assert opened is False and first["state"] == "closed"
            second, opened = await record_provider_failure(
                session, error_code="TEST_TWO"
            )
            assert opened is True and second["state"] == "open"
            await session.commit()
            with pytest.raises(HTTPException) as blocked:
                await assert_provider_available(session)
            assert blocked.value.status_code == 503
            record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN
                )
            )
            payload = dict(record.payload)
            from app.services.three_d_resilience import now

            payload["open_until"] = (now() - timedelta(seconds=1)).isoformat()
            record.payload = payload
            await session.commit()
            half = await provider_circuit_snapshot(session, lock=True)
            assert half["state"] == "half_open" and half["available"] is True
            recovered = await record_provider_success(session)
            assert (
                recovered["state"] == "closed"
                and recovered["consecutive_failures"] == 0
            )
            await session.commit()
        finally:
            if original_payload is not None:
                policy_row = await session.scalar(
                    select(OwnerControlRecord).where(
                        OwnerControlRecord.domain == "3d-service-policy",
                        OwnerControlRecord.resource_id == "default",
                    )
                )
                if policy_row is not None:
                    policy_row.payload = original_payload
            await session.execute(
                delete(OwnerControlRecord).where(
                    OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_operations_snapshot_is_numeric_and_prometheus_ready():
    async with SessionLocal() as session:
        snapshot = await operations_snapshot(session)
        assert snapshot["jobs"]["total"] >= 0
        assert 0 <= snapshot["jobs"]["success_rate_pct"] <= 100
        assert snapshot["spend"]["daily_usd"] >= 0
        assert snapshot["circuit"]["state"] in {"closed", "open", "half_open"}


@pytest.mark.asyncio
async def test_cleanup_expired_objects_and_spend_threshold_alert(monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import delete, select

    from app.db.models import (
        Organization,
        Project,
        ThreeDArtifact,
        ThreeDGenerationJob,
        User,
        Workspace,
        uuid_str,
    )
    from app.services import communications
    from app.services.three_d_resilience import (
        cleanup_expired_three_d_data,
        maybe_emit_spend_alerts,
    )

    deleted_keys: list[str] = []
    delivered: list[dict] = []

    class FakeStorage:
        def delete(self, key: str) -> None:
            deleted_keys.append(key)

    async def fake_notify(_session, **kwargs):
        delivered.append(kwargs)
        return []

    monkeypatch.setattr(communications, "notify_audience", fake_notify)
    suffix = uuid_str()
    async with SessionLocal() as session:
        organization = Organization(
            id=uuid_str(),
            name=f"Phase34E {suffix[:8]}",
            slug=f"phase34e-{suffix}",
            plan="business",
            status="active",
        )
        session.add(organization)
        await session.flush()
        workspace = Workspace(
            id=uuid_str(),
            organization_id=organization.id,
            name="Phase34E",
            slug=f"phase34e-{suffix}",
            status="active",
        )
        session.add(workspace)
        await session.flush()
        user = User(
            id=uuid_str(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            email=f"phase34e-{suffix}@example.invalid",
            name="Phase34E",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid_str(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="Phase34E",
            slug=f"phase34e-{suffix}",
            status="planning",
            priority="medium",
            progress=0,
            tags=[],
            risk="normal",
            review_status="not_requested",
            version=1,
        )
        session.add(project)
        await session.flush()
        job = ThreeDGenerationJob(
            id=uuid_str(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            project_id=project.id,
            requested_by_id=user.id,
            provider="runpod",
            status="completed",
            stage="completed",
            progress=100,
            input_object_key=f"3d/{organization.id}/{project.id}/input.png",
            input_content_type="image/png",
            input_size_bytes=100,
            input_sha256="a" * 64,
            request_options={},
            estimated_cost_usd=21.0,
            metering_status="metered",
            attempts=1,
            max_attempts=1,
            version=1,
            started_at=datetime.now(UTC) - timedelta(minutes=2),
            completed_at=datetime.now(UTC) - timedelta(minutes=1),
            updated_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.add(job)
        await session.flush()
        artifact = ThreeDArtifact(
            id=uuid_str(),
            organization_id=organization.id,
            project_id=project.id,
            job_id=job.id,
            created_by_id=user.id,
            filename="final.glb",
            media_type="model/gltf-binary",
            object_key=f"3d/{organization.id}/{project.id}/{job.id}/final.glb",
            checksum="b" * 64,
            size_bytes=1000,
            status="ready",
            artifact_metadata={},
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(artifact)
        policy_row = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == "3d-service-policy",
                OwnerControlRecord.resource_id == "default",
            )
        )
        original_policy = dict(policy_row.payload) if policy_row is not None else None
        if policy_row is not None:
            policy_row.payload = {
                **dict(policy_row.payload or {}),
                "daily_spend_limit_usd": 25.0,
                "monthly_spend_limit_usd": 500.0,
                "owner_alert_threshold_pct": 80,
                "temporary_input_retention_hours": 24,
            }
        await session.commit()
        try:
            cleanup = await cleanup_expired_three_d_data(session, FakeStorage())
            assert cleanup == {"artifacts_expired": 1, "stale_inputs_cleaned": 1}
            assert artifact.object_key in deleted_keys
            assert job.input_object_key in deleted_keys
            await session.refresh(artifact)
            assert artifact.status == "expired"

            await maybe_emit_spend_alerts(session, organization_id=organization.id)
            assert any(item["event_key"] == "3d.spend.daily" for item in delivered)
            daily = next(
                item for item in delivered if item["event_key"] == "3d.spend.daily"
            )
            assert daily["audience"] == "owner"
            assert daily["severity"] == "warning"
        finally:
            if original_policy is not None:
                policy_row = await session.scalar(
                    select(OwnerControlRecord).where(
                        OwnerControlRecord.domain == "3d-service-policy",
                        OwnerControlRecord.resource_id == "default",
                    )
                )
                if policy_row is not None:
                    policy_row.payload = original_policy
            await session.execute(
                delete(ThreeDArtifact).where(ThreeDArtifact.job_id == job.id)
            )
            await session.execute(
                delete(ThreeDGenerationJob).where(ThreeDGenerationJob.id == job.id)
            )
            await session.execute(delete(Project).where(Project.id == project.id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await session.execute(
                delete(Organization).where(Organization.id == organization.id)
            )
            await session.commit()
