"""Focused contracts for production-grade Owner mutations and release evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.owner import control_plane, final_platform_integration
from app.core.auth import UserRecord
from app.db.models import (
    BackupRecord,
    DisasterRecoveryRun,
    MetricSample,
    Organization,
    OwnerCommandRecord,
    OwnerControlRecord,
    Project,
    Role,
)


def _actor() -> UserRecord:
    return UserRecord(
        id="owner-1",
        email="owner@aionex.local",
        name="AIONEX Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX Corp",
        organization_plan="enterprise",
        permissions=["*"],
    )


def _control_record(
    domain: str,
    resource_id: str,
    *,
    status: str = "not_assessed",
    payload: dict[str, Any] | None = None,
) -> OwnerControlRecord:
    return OwnerControlRecord(
        domain=domain,
        resource_id=resource_id,
        status=status,
        enabled=True,
        payload=payload or {},
        version=1,
    )


def test_secret_reference_accepts_external_vault_ids_and_rejects_plaintext() -> None:
    assert (
        control_plane._validated_secret_reference("vault://aionex/production/openai")
        == "vault://aionex/production/openai"
    )
    arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:aionex/production/openai-AbCd"
    )
    assert control_plane._validated_secret_reference(arn) == arn

    for unsafe in (
        "plain-text-password",
        "https://user:password@example.com/secret",
        "vault://aionex/production/openai?token=inline",
    ):
        with pytest.raises(HTTPException) as rejected:
            control_plane._validated_secret_reference(unsafe)
        assert rejected.value.status_code == 422


@pytest.mark.asyncio
async def test_billing_plan_change_rejects_unknown_or_missing_plan() -> None:
    organization = Organization(
        id="customer-org",
        name="Customer",
        slug="customer",
        plan="professional",
        status="active",
    )

    class OrganizationSession:
        async def get(self, _model: object, resource_id: str) -> Organization | None:
            return organization if resource_id == organization.id else None

    for payload in ({}, {"plan": "unlimited-fantasy"}):
        with pytest.raises(HTTPException) as rejected:
            await control_plane._apply_live_action(
                OrganizationSession(),  # type: ignore[arg-type]
                _actor(),
                "billing",
                organization.id,
                "change-plan",
                payload,
            )
        assert rejected.value.status_code == 422
        assert organization.plan == "professional"


def test_timeline_categories_preserve_resource_semantics() -> None:
    assert control_plane._timeline_category("project", "project.update") == "project"
    assert control_plane._timeline_category("meeting", "meeting.approve") == "approval"
    assert control_plane._timeline_category("alert", "alert.resolve") == "incident"
    assert control_plane._timeline_category("role", "role.update") == "user"
    assert (
        control_plane._timeline_category("service", "auth.session.revoke") == "security"
    )
    assert control_plane._timeline_category("service", "service.restart") == "service"


def test_metric_health_never_defaults_missing_evidence_to_healthy() -> None:
    assert control_plane._metric_health_status({}) == "unknown"
    assert control_plane._metric_health_status({"status": "unexpected"}) == "unknown"
    assert control_plane._metric_health_status({"status": "degraded"}) == "warning"
    assert control_plane._metric_health_status({"status": "failed"}) == "critical"
    assert control_plane._metric_health_status({"status": "ready"}) == "healthy"


def test_notification_channels_reject_unknown_values() -> None:
    valid = control_plane.OwnerNotificationRuleUpdate(
        channels=["in_app", "email", "push", "whatsapp"]
    )
    assert valid.channels == ["in_app", "email", "push", "whatsapp"]

    with pytest.raises(ValidationError):
        control_plane.OwnerNotificationRuleUpdate(channels=["sms"])


@pytest.mark.asyncio
async def test_compliance_evidence_is_validated_deduplicated_and_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _control_record(
        "compliance",
        "soc-audit-test",
        payload={"evidence": 0, "evidenceReferences": []},
    )

    async def get_record(*_args: object) -> OwnerControlRecord:
        return record

    monkeypatch.setattr(control_plane, "_control_record", get_record)
    reference = "evidence://audit/report-2026-07-29"

    first = await control_plane._apply_live_action(
        object(),  # type: ignore[arg-type]
        _actor(),
        "compliance",
        record.resource_id,
        "record-evidence",
        {"reference": reference},
    )
    duplicate = await control_plane._apply_live_action(
        object(),  # type: ignore[arg-type]
        _actor(),
        "compliance",
        record.resource_id,
        "record-evidence",
        {"reference": reference},
    )

    assert first["evidence"] == 1
    assert first["status"] == "partial"
    assert "evidenceRecorded" not in first
    assert control_plane._redact_sensitive(first)["evidenceReferences"] == "[REDACTED]"
    assert duplicate["duplicate"] is True
    assert record.payload["evidenceReferences"] == [reference]

    attested = await control_plane._apply_live_action(
        object(),  # type: ignore[arg-type]
        _actor(),
        "compliance",
        record.resource_id,
        "attest",
        {"status": "compliant"},
    )
    assert attested["status"] == "compliant"

    empty_record = _control_record(
        "compliance",
        "empty-control",
        payload={"evidence": 0, "evidenceReferences": []},
    )

    async def get_empty(*_args: object) -> OwnerControlRecord:
        return empty_record

    monkeypatch.setattr(control_plane, "_control_record", get_empty)
    with pytest.raises(HTTPException) as forged_evidence:
        await control_plane._apply_live_action(
            object(),  # type: ignore[arg-type]
            _actor(),
            "compliance",
            empty_record.resource_id,
            "save",
            {
                "status": "compliant",
                "evidence": 999,
                "evidenceReferences": ["forged-reference"],
            },
        )
    assert forged_evidence.value.status_code == 409
    assert empty_record.payload["evidence"] == 0

    with pytest.raises(HTTPException) as no_evidence:
        await control_plane._apply_live_action(
            object(),  # type: ignore[arg-type]
            _actor(),
            "compliance",
            empty_record.resource_id,
            "attest",
            {"status": "compliant"},
        )
    assert no_evidence.value.status_code == 409

    with pytest.raises(HTTPException) as inline_secret:
        await control_plane._apply_live_action(
            object(),  # type: ignore[arg-type]
            _actor(),
            "compliance",
            empty_record.resource_id,
            "record-evidence",
            {"reference": "https://user:password@example.com/report"},
        )
    assert inline_secret.value.status_code == 422


class _AuditSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_unified_owner_mutation_records_accepted_completed_and_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _AuditSession()
    saw_accepted = False

    async def success(command: OwnerCommandRecord) -> dict[str, Any]:
        nonlocal saw_accepted
        saw_accepted = command.status == "accepted"
        return {"safe": "retained", "password": "must-not-persist"}

    result = await control_plane._run_audited_mutation(
        session,  # type: ignore[arg-type]
        actor=_actor(),
        domain="test-domain",
        resource_id="resource-1",
        action="update",
        request={"token": "must-not-persist", "safe": "retained"},
        mutation=success,
    )

    command = next(
        item for item in session.added if isinstance(item, OwnerCommandRecord)
    )
    assert saw_accepted is True
    assert result["password"] == "must-not-persist"
    assert command.status == "completed"
    assert command.request == {"token": "[REDACTED]", "safe": "retained"}
    assert command.result == {"safe": "retained", "password": "[REDACTED]"}
    assert session.commits == 1

    failed: dict[str, Any] = {}

    async def persist_failed(
        _session: object,
        *,
        command: OwnerCommandRecord,
        actor: UserRecord,
        request: dict[str, Any],
        exc: Exception,
    ) -> None:
        failed.update(
            command=command,
            actor=actor,
            request=control_plane._redact_sensitive(request),
            exc=exc,
        )

    async def failure(_command: OwnerCommandRecord) -> dict[str, Any]:
        raise HTTPException(status_code=409, detail="blocked")

    monkeypatch.setattr(control_plane, "_persist_failed_command", persist_failed)
    with pytest.raises(HTTPException):
        await control_plane._run_audited_mutation(
            _AuditSession(),  # type: ignore[arg-type]
            actor=_actor(),
            domain="test-domain",
            resource_id="resource-2",
            action="delete",
            request={"reference": "secret-inline-value"},
            mutation=failure,
        )
    assert failed["command"].status == "accepted"
    assert failed["request"]["reference"] == "[REDACTED]"


class _ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class _ReleaseEvidenceSession:
    def __init__(
        self,
        backup: BackupRecord | None,
        recovery_runs: list[DisasterRecoveryRun],
    ) -> None:
        self.backup = backup
        self.recovery_runs = recovery_runs

    async def scalar(self, _statement: object) -> BackupRecord | None:
        return self.backup

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.recovery_runs)


class _PerformanceEvidenceSession:
    def __init__(self, samples: list[MetricSample]) -> None:
        self.samples = samples

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.samples)


@pytest.mark.asyncio
async def test_performance_gate_requires_explicit_healthy_telemetry() -> None:
    gate = _control_record("release", "performance", status="pending")

    await control_plane._validate_release_gate(  # type: ignore[arg-type]
        _PerformanceEvidenceSession(
            [
                MetricSample(
                    name="request-latency",
                    resource="api",
                    value=120,
                    labels={},
                )
            ]
        ),
        gate,
    )
    assert gate.status == "blocked"
    assert gate.payload["evidence"]["unknownStatusSampleCount"] == 1

    await control_plane._validate_release_gate(  # type: ignore[arg-type]
        _PerformanceEvidenceSession(
            [
                MetricSample(
                    name="error-rate",
                    resource="api",
                    value=10,
                    labels={"status": "failed"},
                )
            ]
        ),
        gate,
    )
    assert gate.status == "blocked"
    assert gate.payload["evidence"]["unhealthySampleCount"] == 1

    await control_plane._validate_release_gate(  # type: ignore[arg-type]
        _PerformanceEvidenceSession(
            [
                MetricSample(
                    name="request-latency",
                    resource="api",
                    value=120,
                    labels={"status": "healthy"},
                )
            ]
        ),
        gate,
    )
    assert gate.status == "passed"


@pytest.mark.asyncio
async def test_backup_release_gate_requires_recent_backup_and_matching_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def artifact_ready(
        backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is True
        return backup is not None

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_ready)
    backup = BackupRecord(
        id="backup-1",
        kind="full",
        scope="platform",
        status="completed",
        location="/protected/backup.dump",
        checksum="a" * 64,
        size_bytes=128,
        completed_at=datetime.now(UTC),
    )
    wrong_restore = DisasterRecoveryRun(
        id="run-wrong",
        operation="restore_validation",
        status="completed",
        details={"backup_id": "different-backup", "validated": True},
        completed_at=datetime.now(UTC),
    )
    mismatched_integrity_restore = DisasterRecoveryRun(
        id="run-mismatched-integrity",
        operation="restore_validation",
        status="completed",
        details={
            "backup_id": backup.id,
            "validated": True,
            "checksum": "b" * 64,
            "size_bytes": backup.size_bytes,
        },
        completed_at=datetime.now(UTC),
    )
    matching_restore = DisasterRecoveryRun(
        id="run-matching",
        operation="restore_validation",
        status="completed",
        details={
            "backup_id": backup.id,
            "validated": True,
            "checksum": backup.checksum,
            "size_bytes": backup.size_bytes,
        },
        completed_at=datetime.now(UTC),
    )

    missing_backup_gate = _control_record(
        "release",
        "backup",
        status="pending",
        payload={"name": "Backup & Restore Verification"},
    )
    await control_plane._validate_release_gate(
        _ReleaseEvidenceSession(None, []),  # type: ignore[arg-type]
        missing_backup_gate,
    )
    assert missing_backup_gate.status == "blocked"

    mismatched_gate = _control_record(
        "release",
        "backup",
        status="pending",
        payload={"name": "Backup & Restore Verification"},
    )
    await control_plane._validate_release_gate(
        _ReleaseEvidenceSession(backup, [wrong_restore]),  # type: ignore[arg-type]
        mismatched_gate,
    )
    assert mismatched_gate.status == "blocked"

    mismatched_integrity_gate = _control_record(
        "release",
        "backup",
        status="pending",
        payload={"name": "Backup & Restore Verification"},
    )
    await control_plane._validate_release_gate(
        _ReleaseEvidenceSession(backup, [mismatched_integrity_restore]),  # type: ignore[arg-type]
        mismatched_integrity_gate,
    )
    assert mismatched_integrity_gate.status == "blocked"

    verified_gate = _control_record(
        "release",
        "backup",
        status="pending",
        payload={"name": "Backup & Restore Verification"},
    )
    result = await control_plane._validate_release_gate(
        _ReleaseEvidenceSession(backup, [matching_restore]),  # type: ignore[arg-type]
        verified_gate,
    )
    assert verified_gate.status == "passed"
    assert result["evidence"]["backupId"] == backup.id
    assert result["evidence"]["recoveryRunId"] == matching_restore.id
    assert result["evidence"]["windowHours"] == 24


@pytest.mark.asyncio
async def test_backup_release_gate_blocks_failed_live_artifact_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = BackupRecord(
        id="backup-corrupt",
        kind="full",
        scope="platform",
        status="completed",
        location="/protected/corrupt.dump",
        checksum="a" * 64,
        size_bytes=128,
        completed_at=datetime.now(UTC),
    )
    matching_restore = DisasterRecoveryRun(
        id="run-for-corrupt",
        operation="restore_validation",
        status="completed",
        details={
            "backup_id": backup.id,
            "validated": True,
            "checksum": backup.checksum,
            "size_bytes": backup.size_bytes,
        },
        completed_at=datetime.now(UTC),
    )

    async def artifact_missing(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is True
        return False

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_missing)
    gate = _control_record("release", "backup", status="pending")
    result = await control_plane._validate_release_gate(
        _ReleaseEvidenceSession(backup, [matching_restore]),  # type: ignore[arg-type]
        gate,
    )

    assert gate.status == "blocked"
    assert result["evidence"]["artifactIntegrity"] == "failed"
    assert result["evidence"]["recoveryRunId"] is None
    assert "integrity" in result["lastResult"].lower()


@pytest.mark.asyncio
async def test_release_approval_always_revalidates_live_non_owner_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _control_record(
        "release",
        "approval",
        status="pending",
        payload={"name": "Final Owner Approval"},
    )
    calls = 0

    async def get_record(*_args: object) -> OwnerControlRecord:
        return approval

    async def blocked(_session: object) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return [{"id": "backup", "name": "Backup", "status": "blocked"}]

    monkeypatch.setattr(control_plane, "_control_record", get_record)
    monkeypatch.setattr(
        control_plane,
        "_revalidate_non_owner_release_gates",
        blocked,
    )
    with pytest.raises(HTTPException) as blocked_approval:
        await control_plane._apply_live_action(
            object(),  # type: ignore[arg-type]
            _actor(),
            "release",
            "approval",
            "approve",
            {},
        )
    assert blocked_approval.value.status_code == 409
    assert calls == 1
    assert approval.status != "passed"

    async def passed(_session: object) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return [
            {"id": gate, "name": gate.title(), "status": "passed"}
            for gate in ("validation", "security", "performance", "backup")
        ]

    monkeypatch.setattr(
        control_plane,
        "_revalidate_non_owner_release_gates",
        passed,
    )
    approved = await control_plane._apply_live_action(
        object(),  # type: ignore[arg-type]
        _actor(),
        "release",
        "approval",
        "approve",
        {},
    )
    assert approved["status"] == "passed"
    assert calls == 2


@pytest.mark.asyncio
async def test_final_close_is_durable_and_non_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _control_record(
        "release",
        "approval",
        status="pending",
        payload={"name": "Final Owner Approval"},
    )
    live_approvals = 0

    async def get_record(*_args: object) -> OwnerControlRecord:
        return approval

    async def approve(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal live_approvals
        live_approvals += 1
        approval.status = "passed"
        return {"id": "approval", "status": "passed"}

    async def run(
        _session: object,
        *,
        mutation: Any,
        **_kwargs: object,
    ) -> dict[str, Any]:
        command = OwnerCommandRecord(
            actor_id="owner-1",
            domain="final-platform-integration",
            resource_id="platform",
            action="close",
            request={},
            status="accepted",
        )
        return await mutation(command)

    async def snapshot(_session: object):
        closed_at = approval.payload.get("platformClosedAt")
        return final_platform_integration.FinalIntegrationSnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            completion=100,
            closed=bool(closed_at),
            state="closed" if closed_at else "open",
            closed_at=closed_at,
            closed_by=approval.payload.get("platformClosedBy"),
            targets=[],
        )

    monkeypatch.setattr(final_platform_integration, "_control_record", get_record)
    monkeypatch.setattr(final_platform_integration, "_apply_live_action", approve)
    monkeypatch.setattr(final_platform_integration, "_run_audited_mutation", run)
    monkeypatch.setattr(final_platform_integration, "_snapshot", snapshot)

    response = await final_platform_integration.run_final_platform_integration_command(
        final_platform_integration.FinalIntegrationCommand(
            target_id="platform",
            action="close",
        ),
        actor=_actor(),
        session=object(),  # type: ignore[arg-type]
    )
    assert response.closed is True
    assert response.state == "closed"
    assert response.closed_by == "owner-1"
    assert live_approvals == 1

    with pytest.raises(HTTPException) as repeated:
        await final_platform_integration.run_final_platform_integration_command(
            final_platform_integration.FinalIntegrationCommand(
                target_id="platform",
                action="close",
            ),
            actor=_actor(),
            session=object(),  # type: ignore[arg-type]
        )
    assert repeated.value.status_code == 409
    assert live_approvals == 1


class _ProjectCommandSession:
    def __init__(self, projects: list[Any]) -> None:
        self.projects = projects

    async def scalars(self, statement: Any) -> _ScalarRows:
        parameters = statement.compile().params
        eligible = set(parameters["status_1"])
        return _ScalarRows(
            [project for project in self.projects if project.status in eligible]
        )


@pytest.mark.asyncio
async def test_global_pause_and_resume_preserve_non_runnable_project_states() -> None:
    projects = [
        SimpleNamespace(id="active", status="active"),
        SimpleNamespace(id="paused", status="paused"),
        SimpleNamespace(id="planning", status="planning"),
        SimpleNamespace(id="review", status="review"),
        SimpleNamespace(id="completed", status="completed"),
        SimpleNamespace(id="deleted", status="deleted"),
    ]
    session = _ProjectCommandSession(projects)

    paused = await control_plane._apply_live_action(
        session,  # type: ignore[arg-type]
        _actor(),
        "global-command",
        "all",
        "pause",
        {},
    )
    assert paused == {"updated": 1}
    assert {project.id: project.status for project in projects} == {
        "active": "paused",
        "paused": "paused",
        "planning": "planning",
        "review": "review",
        "completed": "completed",
        "deleted": "deleted",
    }

    resumed = await control_plane._apply_live_action(
        session,  # type: ignore[arg-type]
        _actor(),
        "global-command",
        "all",
        "resume",
        {},
    )
    assert resumed == {"updated": 2}
    assert {project.id: project.status for project in projects} == {
        "active": "active",
        "paused": "active",
        "planning": "planning",
        "review": "review",
        "completed": "completed",
        "deleted": "deleted",
    }


class _SingleProjectSession:
    def __init__(self, project: Any) -> None:
        self.project = project

    async def get(self, model: object, resource_id: str) -> Any:
        if model is Project and resource_id == self.project.id:
            return self.project
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["archived", "completed", "deleted", "inactive"])
async def test_terminal_projects_cannot_be_paused_or_reactivated(status: str) -> None:
    project = SimpleNamespace(id=f"project-{status}", status=status)
    session = _SingleProjectSession(project)

    for action in ("pause", "resume"):
        with pytest.raises(HTTPException) as rejected:
            await control_plane._apply_live_action(
                session,  # type: ignore[arg-type]
                _actor(),
                "projects",
                project.id,
                action,
                {},
            )
        assert rejected.value.status_code == 409
        assert project.status == status


class _RoleActionSession:
    def __init__(self, role: Role) -> None:
        self.role = role

    async def get(self, model: object, resource_id: str) -> Any:
        if model is Role and resource_id == self.role.id:
            return self.role
        return None


@pytest.mark.asyncio
async def test_deleted_role_cannot_be_reactivated_from_owner_access() -> None:
    role = Role(id="deleted-role", name="Former Role", status="deleted")
    with pytest.raises(HTTPException) as rejected:
        await control_plane._apply_live_action(
            _RoleActionSession(role),  # type: ignore[arg-type]
            _actor(),
            "access",
            role.id,
            "toggle",
            {},
        )
    assert rejected.value.status_code == 409
    assert role.status == "deleted"


@pytest.mark.asyncio
async def test_revoked_secret_reference_cannot_be_reactivated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _control_record("secrets", "revoked-secret", status="revoked")

    async def get_record(*_args: object) -> OwnerControlRecord:
        return record

    monkeypatch.setattr(control_plane, "_control_record", get_record)
    with pytest.raises(HTTPException) as rejected:
        await control_plane._apply_control_action(
            object(),  # type: ignore[arg-type]
            "secrets",
            record.resource_id,
            "rotate",
            {},
        )
    assert rejected.value.status_code == 409
    assert record.status == "revoked"


@pytest.mark.asyncio
async def test_restore_validation_is_tied_to_a_completed_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def artifact_ready(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is False
        return True

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_ready)
    backup = BackupRecord(
        id="backup-for-validation",
        kind="full",
        scope="platform",
        status="completed",
        completed_at=datetime.now(UTC),
    )

    class RecoverySession:
        def __init__(self, selected_backup: BackupRecord | None) -> None:
            self.selected_backup = selected_backup
            self.added: list[object] = []
            self.scalar_calls = 0

        async def scalar(self, _statement: object) -> object | None:
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return None
            return self.selected_backup

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            return None

    missing_session = RecoverySession(None)
    with pytest.raises(HTTPException) as missing:
        await control_plane._apply_live_action(
            missing_session,  # type: ignore[arg-type]
            _actor(),
            "recovery",
            "latest",
            "validate-restore",
            {},
        )
    assert missing.value.status_code == 409

    session = RecoverySession(backup)
    result = await control_plane._apply_live_action(
        session,  # type: ignore[arg-type]
        _actor(),
        "recovery",
        "latest",
        "validate-restore",
        {},
    )
    run = next(item for item in session.added if isinstance(item, DisasterRecoveryRun))
    assert result["backup_id"] == backup.id
    assert run.operation == "restore_validation"
    assert run.details == {
        "backup_id": backup.id,
        "dry_run": True,
        "requested_by": "owner-1",
    }

    async def artifact_missing(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is False
        return False

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_missing)
    with pytest.raises(HTTPException) as corrupt:
        await control_plane._apply_live_action(
            RecoverySession(backup),  # type: ignore[arg-type]
            _actor(),
            "recovery",
            "latest",
            "validate-restore",
            {},
        )
    assert corrupt.value.status_code == 409
    assert "readiness" in corrupt.value.detail


@pytest.mark.asyncio
async def test_recovery_collection_always_includes_latest_restorable_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    backup = BackupRecord(
        id="restorable-backup",
        kind="full",
        scope="platform",
        status="completed",
        location="/protected/backup.dump",
        checksum="a" * 64,
        size_bytes=128,
        created_at=now - timedelta(days=2),
        completed_at=now - timedelta(days=2),
    )
    newer_runs = [
        DisasterRecoveryRun(
            id=f"run-{index}",
            operation="test",
            status="failed",
            details={"validated": False},
            created_at=now - timedelta(minutes=index),
        )
        for index in range(100)
    ]

    class RecoveryListSession:
        def __init__(self) -> None:
            self.row_sets = [[backup], newer_runs]

        async def scalars(self, _statement: object) -> _ScalarRows:
            return _ScalarRows(self.row_sets.pop(0))

        async def scalar(self, _statement: object) -> BackupRecord:
            return backup

    async def artifact_ready(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is False
        return True

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_ready)
    items = await control_plane._recovery_items(  # type: ignore[arg-type]
        RecoveryListSession()
    )

    assert len(items) == 100
    restorable = next(item for item in items if item["id"] == backup.id)
    assert restorable["artifactReady"] is True
    assert "location" not in restorable

    async def artifact_missing(
        _backup: BackupRecord | None,
        *,
        verify_checksum: bool,
    ) -> bool:
        assert verify_checksum is False
        return False

    monkeypatch.setattr(control_plane, "_backup_artifact_ready", artifact_missing)
    unavailable = await control_plane._recovery_items(  # type: ignore[arg-type]
        RecoveryListSession()
    )
    missing_artifact = next(item for item in unavailable if item["id"] == backup.id)
    assert missing_artifact["artifactReady"] is False


@pytest.mark.asyncio
async def test_release_rejection_and_license_plan_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def release_controls(
        _session: object,
        domain: str,
    ) -> list[dict[str, Any]]:
        assert domain == "release"
        return [
            {
                "id": "validation",
                "name": "Validation",
                "status": "passed",
                "updatedAt": datetime.now(UTC).isoformat(),
            },
            {
                "id": "approval",
                "name": "Owner Approval",
                "status": "rejected",
                "updatedAt": datetime.now(UTC).isoformat(),
                "platformClosedAt": "2026-07-29T12:00:00+00:00",
            },
        ]

    monkeypatch.setattr(control_plane, "_control_items", release_controls)
    release = (await control_plane.releases(_actor(), object()))[0]  # type: ignore[arg-type]
    assert release["status"] == "rejected"
    assert release["closed"] is True
    assert release["closedAt"] == "2026-07-29T12:00:00+00:00"

    async def billing(*_args: object) -> list[dict[str, Any]]:
        return [
            {
                "id": plan.lower(),
                "organization": plan,
                "plan": plan,
                "seats": 1,
                "activeSeats": 1,
                "status": "active",
                "protected": False,
            }
            for plan in (
                "Enterprise",
                "Professional",
                "Team",
                "Starter",
                "Free",
            )
        ]

    monkeypatch.setattr(control_plane, "_billing_items", billing)
    licenses = await control_plane.licenses(_actor(), object())  # type: ignore[arg-type]
    assert {item["plan"] for item in licenses} == {
        "enterprise",
        "professional",
        "starter",
    }


@pytest.mark.asyncio
async def test_approval_history_keeps_durable_decisions_visible() -> None:
    now = datetime.now(UTC)
    meetings = [
        SimpleNamespace(
            id=f"meeting-{status}",
            title=status,
            organizer_id="requester-1",
            project_id=None,
            organization_id="aionex-org",
            status=status,
            created_at=now,
            updated_at=now,
            approved_at=now if status == "scheduled" else None,
        )
        for status in (
            "pending_approval",
            "scheduled",
            "rejected",
            "changes_requested",
        )
    ]

    class ApprovalSession:
        async def scalars(self, statement: object) -> _ScalarRows:
            if "approval_requests" in str(statement):
                return _ScalarRows([])
            return _ScalarRows(meetings)

    items = await control_plane._approval_items(ApprovalSession())  # type: ignore[arg-type]
    assert {item["status"] for item in items} == {
        "pending",
        "approved",
        "rejected",
        "changes_requested",
    }
    assert (
        next(item for item in items if item["status"] == "approved")["decidedAt"]
        == now.isoformat()
    )


def test_all_owner_integration_commands_use_unified_audit_executor() -> None:
    owner_api = Path(__file__).resolve().parents[1] / "app" / "api" / "owner"
    for filename in (
        "platform_integration.py",
        "operations_integration.py",
        "security_integration.py",
        "production_runtime.py",
        "final_platform_integration.py",
    ):
        source = (owner_api / filename).read_text(encoding="utf-8")
        assert "_run_audited_mutation(" in source
        assert "_record_command(" not in source
