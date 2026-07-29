"""Relational runtime endpoint contracts and organization isolation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    Organization,
    Project,
    Report,
    Task,
    User,
    Workflow,
    Workspace,
)

ENDPOINTS = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"
RUNTIME_ENDPOINTS = ("tasks.py", "workflows.py", "reports.py", "dashboard.py")


def _actor(
    user_id: str,
    organization_id: str,
    organization_name: str,
    *,
    permissions: list[str] | None = None,
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.com",
        name=f"{organization_name} Operator",
        role="Manager",
        password_hash="unused",
        organization_id=organization_id,
        organization_name=organization_name,
        organization_plan="enterprise",
        permissions=(
            permissions
            if permissions is not None
            else [
                "tasks:read",
                "tasks:write",
                "workflows:read",
                "workflows:write",
                "reports:read",
                "reports:write",
                "audit:read",
            ]
        ),
    )


async def _delete_tenants(organization_ids: list[str]) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Task).where(Task.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Workflow).where(Workflow.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Report).where(Report.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Project).where(Project.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Workspace).where(Workspace.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(User).where(User.organization_id.in_(organization_ids))
        )
        await session.execute(
            delete(Organization).where(Organization.id.in_(organization_ids))
        )
        await session.commit()


async def _create_tenants(suffix: str):
    organization_a = Organization(
        id=f"rt-org-a-{suffix}",
        name=f"Runtime A {suffix}",
        slug=f"runtime-a-{suffix}",
        plan="enterprise",
        status="active",
    )
    organization_b = Organization(
        id=f"rt-org-b-{suffix}",
        name=f"Runtime B {suffix}",
        slug=f"runtime-b-{suffix}",
        plan="enterprise",
        status="active",
    )
    user_a = User(
        id=f"rt-user-a-{suffix}",
        organization_id=organization_a.id,
        role_id=None,
        email=f"runtime-a-{suffix}@example.com",
        name="Runtime A Operator",
        password_hash="unused",
        status="active",
    )
    user_b = User(
        id=f"rt-user-b-{suffix}",
        organization_id=organization_b.id,
        role_id=None,
        email=f"runtime-b-{suffix}@example.com",
        name="Runtime B Operator",
        password_hash="unused",
        status="active",
    )
    workspace_a = Workspace(
        id=f"rt-ws-a-{suffix}",
        organization_id=organization_a.id,
        name="Runtime Workspace A",
        slug=f"runtime-workspace-a-{suffix}",
        status="active",
    )
    workspace_b = Workspace(
        id=f"rt-ws-b-{suffix}",
        organization_id=organization_b.id,
        name="Runtime Workspace B",
        slug=f"runtime-workspace-b-{suffix}",
        status="active",
    )
    project_a = Project(
        id=f"rt-project-a-{suffix}",
        organization_id=organization_a.id,
        workspace_id=workspace_a.id,
        owner_id=user_a.id,
        name="Runtime Project A",
        slug=f"runtime-project-a-{suffix}",
        status="active",
        priority="high",
        progress=42,
        tags=["runtime-sql"],
    )
    project_b = Project(
        id=f"rt-project-b-{suffix}",
        organization_id=organization_b.id,
        workspace_id=workspace_b.id,
        owner_id=user_b.id,
        name="Runtime Project B",
        slug=f"runtime-project-b-{suffix}",
        status="active",
        priority="high",
        progress=77,
        tags=["runtime-sql"],
    )
    async with SessionLocal() as session:
        session.add_all([organization_a, organization_b])
        await session.flush()
        session.add_all([user_a, user_b, workspace_a, workspace_b])
        await session.flush()
        session.add_all([project_a, project_b])
        await session.commit()
    return (
        organization_a,
        organization_b,
        user_a,
        user_b,
        workspace_a,
        workspace_b,
        project_a,
        project_b,
    )


def test_runtime_endpoint_sources_no_longer_use_the_in_memory_store() -> None:
    for filename in RUNTIME_ENDPOINTS:
        source = (ENDPOINTS / filename).read_text(encoding="utf-8")
        assert "runtime_store" not in source, filename
        assert "from app.core.runtime_store" not in source, filename


@pytest.mark.asyncio
async def test_runtime_sql_crud_visibility_rbac_and_dashboard_contracts() -> None:
    suffix = uuid4().hex[:12]
    organization_ids = [f"rt-org-a-{suffix}", f"rt-org-b-{suffix}"]
    (
        organization_a,
        organization_b,
        user_a,
        user_b,
        workspace_a,
        workspace_b,
        project_a,
        project_b,
    ) = await _create_tenants(suffix)

    actor_holder = {"actor": _actor(user_a.id, organization_a.id, organization_a.name)}
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor_holder["actor"]

    task_ids: dict[str, str] = {}
    workflow_ids: dict[str, str] = {}
    report_ids: dict[str, str] = {}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            task_a_response = await client.post(
                "/api/v1/tasks",
                json={
                    "title": "Persistent task A",
                    "priority": "critical",
                    "assignee_id": user_a.id,
                    "project_id": project_a.id,
                    "workspace_id": workspace_a.id,
                    "organization_id": organization_a.id,
                    "tags": ["sql"],
                },
            )
            assert task_a_response.status_code == 201, task_a_response.text
            task_a = task_a_response.json()
            task_ids["a"] = task_a["id"]
            assert {
                "id",
                "title",
                "description",
                "status",
                "priority",
                "assignee_id",
                "assignee",
                "project_id",
                "project",
                "workspace_id",
                "organization_id",
                "due_date",
                "tags",
                "comments",
                "created_at",
                "updated_at",
                "deleted",
            } <= set(task_a)
            assert task_a["project"] == project_a.name
            assert task_a["assignee"] == user_a.name

            task_update = await client.put(
                f"/api/v1/tasks/{task_a['id']}",
                json={"title": "Persistent task A updated", "status": "done"},
            )
            assert task_update.status_code == 200, task_update.text
            assert task_update.json()["status"] == "done"

            workflow_a_response = await client.post(
                "/api/v1/workflows",
                json={
                    "name": "Persistent workflow A",
                    "workspace_id": workspace_a.id,
                    "project_id": project_a.id,
                    "trigger": "manual",
                    "steps": [{"id": "validate", "type": "validation"}],
                },
            )
            assert workflow_a_response.status_code == 201, workflow_a_response.text
            workflow_a = workflow_a_response.json()
            workflow_ids["a"] = workflow_a["id"]
            assert {
                "id",
                "name",
                "description",
                "status",
                "organization_id",
                "workspace_id",
                "project_id",
                "trigger",
                "steps",
                "run_count",
                "last_run_at",
                "created_at",
                "updated_at",
                "deleted",
            } <= set(workflow_a)

            workflow_update = await client.put(
                f"/api/v1/workflows/{workflow_a['id']}",
                json={"name": "Persistent workflow A updated"},
            )
            assert workflow_update.status_code == 200, workflow_update.text
            assert workflow_update.json()["name"].endswith("updated")
            workflow_run = await client.post(
                f"/api/v1/workflows/{workflow_a['id']}/run"
            )
            assert workflow_run.status_code == 200, workflow_run.text
            assert workflow_run.json()["status"] == "accepted"
            assert workflow_run.json()["workflow"]["run_count"] == 1
            assert workflow_run.json()["workflow"]["last_run_at"] is not None

            workspace_workflow_response = await client.post(
                "/api/v1/workflows",
                json={
                    "name": "Workspace-only workflow",
                    "workspace_id": workspace_a.id,
                },
            )
            assert (
                workspace_workflow_response.status_code == 201
            ), workspace_workflow_response.text
            workspace_workflow = workspace_workflow_response.json()
            assert workspace_workflow["project_id"] is None
            assert workspace_workflow["workspace_id"] == workspace_a.id
            persisted_workspace_workflow = await client.get(
                f"/api/v1/workflows/{workspace_workflow['id']}"
            )
            assert persisted_workspace_workflow.status_code == 200
            assert persisted_workspace_workflow.json()["workspace_id"] == workspace_a.id
            workflow_page = (await client.get("/api/v1/workflows?limit=100")).json()
            assert any(
                item["id"] == workspace_workflow["id"]
                and item["workspace_id"] == workspace_a.id
                for item in workflow_page
            )
            assert (
                await client.delete(f"/api/v1/workflows/{workspace_workflow['id']}")
            ).status_code == 200

            report_a_response = await client.post(
                "/api/v1/reports",
                json={
                    "name": "Persistent report A",
                    "type": "operations",
                    "workspace_id": workspace_a.id,
                    "project_id": project_a.id,
                    "summary": "SQL-backed report",
                    "metrics": {"progress": 42},
                },
            )
            assert report_a_response.status_code == 201, report_a_response.text
            report_a = report_a_response.json()
            report_ids["a"] = report_a["id"]
            assert {
                "id",
                "name",
                "type",
                "organization_id",
                "workspace_id",
                "project_id",
                "status",
                "generated_by",
                "summary",
                "metrics",
                "created_at",
                "updated_at",
            } <= set(report_a)
            assert report_a["generated_by"] == user_a.id

            for endpoint, payload in (
                (
                    "/api/v1/tasks",
                    {
                        "title": "Cross-scope task",
                        "project_id": project_b.id,
                    },
                ),
                (
                    "/api/v1/workflows",
                    {
                        "name": "Cross-scope workflow",
                        "project_id": project_b.id,
                    },
                ),
                (
                    "/api/v1/reports",
                    {
                        "name": "Cross-scope report",
                        "project_id": project_b.id,
                    },
                ),
            ):
                response = await client.post(endpoint, json=payload)
                assert response.status_code == 404, (endpoint, response.text)

            scope_violation = await client.post(
                "/api/v1/tasks",
                json={
                    "title": "Wrong organization",
                    "organization_id": organization_b.id,
                },
            )
            assert scope_violation.status_code == 403

            actor_holder["actor"] = _actor(
                user_b.id,
                organization_b.id,
                organization_b.name,
            )
            task_b_response = await client.post(
                "/api/v1/tasks",
                json={
                    "title": "Persistent task B",
                    "project_id": project_b.id,
                    "workspace_id": workspace_b.id,
                },
            )
            assert task_b_response.status_code == 201, task_b_response.text
            task_ids["b"] = task_b_response.json()["id"]
            workflow_b_response = await client.post(
                "/api/v1/workflows",
                json={
                    "name": "Persistent workflow B",
                    "project_id": project_b.id,
                    "workspace_id": workspace_b.id,
                },
            )
            assert workflow_b_response.status_code == 201, workflow_b_response.text
            workflow_ids["b"] = workflow_b_response.json()["id"]
            report_b_response = await client.post(
                "/api/v1/reports",
                json={
                    "name": "Persistent report B",
                    "project_id": project_b.id,
                    "workspace_id": workspace_b.id,
                },
            )
            assert report_b_response.status_code == 201, report_b_response.text
            report_ids["b"] = report_b_response.json()["id"]

            actor_holder["actor"] = _actor(
                user_a.id,
                organization_a.id,
                organization_a.name,
            )
            task_list = (await client.get("/api/v1/tasks?limit=100")).json()
            workflow_list = (await client.get("/api/v1/workflows?limit=100")).json()
            report_list = (await client.get("/api/v1/reports?limit=100")).json()
            assert {item["id"] for item in task_list} == {task_ids["a"]}
            assert {item["id"] for item in workflow_list} == {workflow_ids["a"]}
            assert {item["id"] for item in report_list} == {report_ids["a"]}

            for endpoint in (
                f"/api/v1/tasks/{task_ids['b']}",
                f"/api/v1/workflows/{workflow_ids['b']}",
                f"/api/v1/reports/{report_ids['b']}",
            ):
                response = await client.get(endpoint)
                assert response.status_code == 404, (endpoint, response.text)

            stats_response = await client.get("/api/v1/dashboard/stats")
            assert stats_response.status_code == 200, stats_response.text
            stats = stats_response.json()
            assert stats == {
                "total_workspaces": 1,
                "total_projects": 1,
                "active_projects": 1,
                "total_tasks": 1,
                "completed_tasks": 1,
                "in_progress_tasks": 0,
                "todo_tasks": 0,
                "total_workflows": 1,
                "active_workflows": 1,
                "total_meetings": 0,
                "pending_meetings": 0,
                "total_reports": 1,
                "average_project_progress": 42.0,
                "activity_count": 8,
            }

            activity_response = await client.get("/api/v1/dashboard/activity")
            assert activity_response.status_code == 200, activity_response.text
            activity = activity_response.json()
            assert len(activity) == stats["activity_count"]
            assert {item["user_id"] for item in activity} == {user_a.id}
            assert all(
                {
                    "id",
                    "type",
                    "title",
                    "description",
                    "user_id",
                    "user",
                    "timestamp",
                }
                <= set(item)
                for item in activity
            )

            charts_response = await client.get("/api/v1/dashboard/charts")
            assert charts_response.status_code == 200, charts_response.text
            charts = charts_response.json()
            assert charts["workflow_runs"]["labels"] == [
                "Persistent workflow A updated"
            ]
            assert charts["workflow_runs"]["data"] == [1]
            assert charts["project_progress"]["labels"] == [project_a.name]
            assert charts["project_progress"]["data"] == [42]
            assert charts["task_status"]["data"][-1] == 1

            actor_holder["actor"] = _actor(
                user_a.id,
                organization_a.id,
                organization_a.name,
                permissions=["tasks:read", "workflows:read", "reports:read"],
            )
            assert (await client.get("/api/v1/dashboard/activity")).status_code == 403
            assert (
                await client.post(
                    "/api/v1/tasks",
                    json={"title": "Forbidden task"},
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/api/v1/workflows",
                    json={"name": "Forbidden workflow"},
                )
            ).status_code == 403
            actor_holder["actor"] = _actor(
                user_a.id,
                organization_a.id,
                organization_a.name,
                permissions=[],
            )
            assert (await client.get("/api/v1/reports")).status_code == 403
            assert (
                await client.post(
                    "/api/v1/reports",
                    json={"name": "Forbidden report"},
                )
            ).status_code == 403
            actor_holder["actor"] = _actor(
                user_a.id,
                organization_a.id,
                organization_a.name,
            )
            assert (
                await client.put(
                    f"/api/v1/tasks/{task_ids['a']}",
                    json={"title": None},
                )
            ).status_code == 422
            assert (
                await client.put(
                    f"/api/v1/tasks/{task_ids['a']}",
                    json={"title": "  "},
                )
            ).status_code == 422
            assert (
                await client.put(
                    f"/api/v1/workflows/{workflow_ids['a']}",
                    json={"status": "deleted"},
                )
            ).status_code == 422
            assert (
                await client.put(
                    f"/api/v1/workflows/{workflow_ids['a']}",
                    json={"name": "  "},
                )
            ).status_code == 422
            assert (
                await client.delete(f"/api/v1/tasks/{task_ids['a']}")
            ).status_code == 200
            assert (
                await client.get(f"/api/v1/tasks/{task_ids['a']}")
            ).status_code == 404
            assert (
                await client.delete(f"/api/v1/workflows/{workflow_ids['a']}")
            ).status_code == 200
            assert (
                await client.get(f"/api/v1/workflows/{workflow_ids['a']}")
            ).status_code == 404

        async with SessionLocal() as session:
            persisted_task = await session.get(Task, task_ids["a"])
            persisted_workflow = await session.get(Workflow, workflow_ids["a"])
            persisted_report = await session.get(Report, report_ids["a"])
            assert persisted_task is not None and persisted_task.status == "deleted"
            assert (
                persisted_workflow is not None
                and persisted_workflow.status == "deleted"
            )
            assert persisted_report is not None
            assert persisted_report.metrics == {"progress": 42}
            audit_actions = set(
                (
                    await session.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.organization_id == organization_a.id
                        )
                    )
                ).all()
            )
            assert {
                "task.create",
                "task.update",
                "task.delete",
                "workflow.create",
                "workflow.update",
                "workflow.run",
                "workflow.delete",
                "report.create",
            } <= audit_actions
    finally:
        await _delete_tenants(organization_ids)
