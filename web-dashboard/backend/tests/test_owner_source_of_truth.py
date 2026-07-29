"""Contracts proving standard and Owner APIs share durable relational rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, require_super_owner
from app.db.base import SessionLocal
from app.db.models import (
    Alert,
    AuditEvent,
    BackupRecord,
    Meeting,
    MetricSample,
    Notification,
    Project,
    Workspace,
)
from app.db.seed import seed
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

ENDPOINTS = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"


def _effective_api_routes(app: FastAPI):
    for candidate in app.routes:
        route_contexts = getattr(candidate, "effective_route_contexts", None)
        if callable(route_contexts):
            yield from (
                route
                for route in route_contexts()
                if getattr(route, "dependant", None) is not None
            )
        elif isinstance(candidate, APIRoute):
            yield candidate


def _actor(
    role: str = "Super Owner",
    *,
    permissions: list[str] | None = None,
) -> UserRecord:
    return UserRecord(
        id="owner-1",
        email="owner@aionex.local",
        name="AIONEX Owner",
        role=role,
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX Corp",
        organization_plan="enterprise",
        permissions=permissions if permissions is not None else ["*"],
    )


def test_runtime_endpoint_sources_are_relational_and_mutations_are_protected() -> None:
    forbidden_sources = {
        "projects.py": ("runtime_store",),
        "workspaces.py": ("runtime_store",),
        "meetings.py": ("runtime_store",),
        "monitoring.py": ("production_runtime",),
        "backups.py": ("production_runtime",),
    }
    for filename, forbidden in forbidden_sources.items():
        source = (ENDPOINTS / filename).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{filename} still uses {marker}"

    notification_source = (ENDPOINTS / "notifications.py").read_text(encoding="utf-8")
    assert "ai_runtime.add_notification" not in notification_source
    assert "ai_runtime.list_notifications" not in notification_source
    assert "ai_runtime.mark_notification" not in notification_source

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    protected_mutations = {
        ("POST", "/api/v1/monitoring/metrics/{metric_name}"),
        ("POST", "/api/v1/monitoring/logs"),
        ("POST", "/api/v1/monitoring/alerts"),
        ("POST", "/api/v1/monitoring/alerts/{alert_id}/acknowledge"),
        ("POST", "/api/v1/monitoring/alerts/{alert_id}/resolve"),
        ("POST", "/api/v1/backups"),
        ("POST", "/api/v1/backups/{backup_id}/restore"),
        ("POST", "/api/v1/backups/dr/test"),
        ("POST", "/api/v1/backups/dr/failover"),
        ("POST", "/api/v1/backups/dr/failback"),
    }
    registered: set[tuple[str, str]] = set()
    for route in _effective_api_routes(app):
        for method in route.methods:
            key = (method, route.path)
            if key not in protected_mutations:
                continue
            registered.add(key)
            assert any(
                dependency.call is require_super_owner
                for dependency in route.dependant.dependencies
            ), route.path
    assert registered == protected_mutations


@pytest.mark.asyncio
async def test_standard_mutations_are_immediately_visible_to_owner_api() -> None:
    await seed()
    suffix = uuid4().hex
    actor_holder = {"actor": _actor()}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    workspace_id: str | None = None
    project_id: str | None = None
    meeting_id: str | None = None
    notification_id: str | None = None
    alert_id: str | None = None
    backup_id: str | None = None
    owner_backup_id: str | None = None
    metric_id: str | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            workspace_response = await client.post(
                "/api/v1/workspaces",
                json={"name": f"Shared Workspace {suffix}"},
            )
            assert workspace_response.status_code == 201, workspace_response.text
            workspace_id = workspace_response.json()["id"]

            project_response = await client.post(
                "/api/v1/projects",
                json={
                    "name": f"Shared Project {suffix}",
                    "workspace_id": workspace_id,
                    "priority": "high",
                    "tags": ["source-of-truth"],
                },
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["id"]

            owner_projects = await client.get("/api/v1/owner/resources/projects")
            assert owner_projects.status_code == 200, owner_projects.text
            assert project_id in {item["id"] for item in owner_projects.json()["items"]}
            owner_pause = await client.post(
                f"/api/v1/owner/resources/projects/{project_id}/actions",
                json={"action": "pause", "payload": {}},
            )
            assert owner_pause.status_code == 200, owner_pause.text
            standard_project = await client.get(f"/api/v1/projects/{project_id}")
            assert standard_project.status_code == 200, standard_project.text
            assert standard_project.json()["status"] == "paused"

            actor_holder["actor"] = _actor(
                "Manager",
                permissions=["meetings:read", "meetings:write"],
            )
            meeting_response = await client.post(
                "/api/v1/meetings",
                json={
                    "title": f"Shared Approval {suffix}",
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "attendee_ids": [],
                    "start_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            assert meeting_response.status_code == 201, meeting_response.text
            meeting_id = meeting_response.json()["id"]
            assert meeting_response.json()["status"] == "pending_approval"

            actor_holder["actor"] = _actor()
            owner_approvals = await client.get("/api/v1/owner/approvals")
            assert owner_approvals.status_code == 200, owner_approvals.text
            assert meeting_id in {
                item["id"] for item in owner_approvals.json()["approvals"]
            }
            owner_approval = await client.patch(
                f"/api/v1/owner/approvals/{meeting_id}",
                json={"status": "approved", "reason": "Source-of-truth verification"},
            )
            assert owner_approval.status_code == 200, owner_approval.text
            standard_meeting = await client.get(f"/api/v1/meetings/{meeting_id}")
            assert standard_meeting.status_code == 200, standard_meeting.text
            assert standard_meeting.json()["status"] == "scheduled"
            assert standard_meeting.json()["approved_by_owner"] is True

            notification_response = await client.post(
                "/api/v1/notifications",
                json={
                    "type": "source-of-truth",
                    "title": f"Shared Notification {suffix}",
                    "message": "Stored in the consolidated notification table.",
                },
            )
            assert notification_response.status_code == 201, notification_response.text
            notification_id = notification_response.json()["id"]
            owner_notifications = await client.get(
                "/api/v1/owner/resources/notifications"
            )
            assert owner_notifications.status_code == 200, owner_notifications.text
            assert notification_id in {
                item["id"] for item in owner_notifications.json()["items"]
            }
            owner_mark_read = await client.post(
                f"/api/v1/owner/resources/notifications/{notification_id}/actions",
                json={"action": "mark-read", "payload": {}},
            )
            assert owner_mark_read.status_code == 200, owner_mark_read.text
            standard_notifications = await client.get("/api/v1/notifications")
            assert (
                standard_notifications.status_code == 200
            ), standard_notifications.text
            standard_notification = next(
                item
                for item in standard_notifications.json()
                if item["id"] == notification_id
            )
            assert standard_notification["read"] is True

            alert_response = await client.post(
                "/api/v1/monitoring/alerts",
                params={
                    "title": f"Shared Alert {suffix}",
                    "description": "SQL source-of-truth verification",
                    "severity": "critical",
                    "source": "test",
                },
            )
            assert alert_response.status_code == 200, alert_response.text
            alert_id = alert_response.json()["id"]
            owner_incidents = await client.get("/api/v1/owner/resources/incidents")
            assert owner_incidents.status_code == 200, owner_incidents.text
            assert alert_id in {item["id"] for item in owner_incidents.json()["items"]}
            owner_acknowledge = await client.post(
                f"/api/v1/owner/resources/incidents/{alert_id}/actions",
                json={"action": "acknowledge", "payload": {}},
            )
            assert owner_acknowledge.status_code == 200, owner_acknowledge.text
            standard_alerts = await client.get("/api/v1/monitoring/alerts")
            assert standard_alerts.status_code == 200, standard_alerts.text
            standard_alert = next(
                item for item in standard_alerts.json() if item["id"] == alert_id
            )
            assert standard_alert["status"] == "investigating"

            backup_response = await client.post(
                "/api/v1/backups",
                params={"name": f"shared-{suffix}", "scope": "platform"},
            )
            assert backup_response.status_code == 202, backup_response.text
            backup_id = backup_response.json()["id"]
            assert backup_response.json()["status"] == "pending"
            owner_recovery = await client.get("/api/v1/owner/resources/recovery")
            assert owner_recovery.status_code == 200, owner_recovery.text
            assert backup_id in {item["id"] for item in owner_recovery.json()["items"]}
            owner_backup = await client.post(
                "/api/v1/owner/resources/recovery/platform/actions",
                json={
                    "action": "create-backup",
                    "payload": {
                        "kind": f"owner-shared-{suffix}",
                        "scope": f"owner-platform-{suffix}",
                    },
                },
            )
            assert owner_backup.status_code == 200, owner_backup.text
            owner_backup_id = next(
                item["id"]
                for item in owner_backup.json()["items"]
                if item["kind"] == f"owner-shared-{suffix}"
            )
            standard_backups = await client.get("/api/v1/backups")
            assert standard_backups.status_code == 200, standard_backups.text
            assert owner_backup_id in {item["id"] for item in standard_backups.json()}

            metric_response = await client.post(
                f"/api/v1/monitoring/metrics/shared-{suffix}",
                params={
                    "value": 42.5,
                    "resource": "source-of-truth-test",
                    "status": "healthy",
                },
            )
            assert metric_response.status_code == 200, metric_response.text
            metric_id = metric_response.json()["id"]
            owner_realtime = await client.get("/api/v1/owner/realtime")
            assert owner_realtime.status_code == 200, owner_realtime.text
            assert metric_id in {
                item["id"] for item in owner_realtime.json()["metrics"]
            }
    finally:
        async with SessionLocal() as session:
            resource_ids = [
                value
                for value in (
                    workspace_id,
                    project_id,
                    meeting_id,
                    alert_id,
                    backup_id,
                    owner_backup_id,
                )
                if value is not None
            ]
            if resource_ids:
                await session.execute(
                    delete(AuditEvent).where(AuditEvent.resource_id.in_(resource_ids))
                )
            if meeting_id:
                await session.execute(delete(Meeting).where(Meeting.id == meeting_id))
            if project_id:
                await session.execute(delete(Project).where(Project.id == project_id))
            if workspace_id:
                await session.execute(
                    delete(Workspace).where(Workspace.id == workspace_id)
                )
            if notification_id:
                await session.execute(
                    delete(Notification).where(Notification.id == notification_id)
                )
            if alert_id:
                await session.execute(delete(Alert).where(Alert.id == alert_id))
            if backup_id:
                await session.execute(
                    delete(BackupRecord).where(BackupRecord.id == backup_id)
                )
            if owner_backup_id:
                await session.execute(
                    delete(BackupRecord).where(BackupRecord.id == owner_backup_id)
                )
            if metric_id:
                await session.execute(
                    delete(MetricSample).where(MetricSample.id == metric_id)
                )
            await session.commit()
