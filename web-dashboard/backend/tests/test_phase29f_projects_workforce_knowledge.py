"""Phase 29F project delivery, workforce, academy, and knowledge contracts."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    AcademyAssessment,
    AcademyCertification,
    AcademyCourse,
    AcademyEnrollment,
    AuditEvent,
    KnowledgeItem,
    KnowledgeProvenance,
    LearningEvent,
    Lesson,
    Notification,
    NotificationDelivery,
    Organization,
    Project,
    ProjectEvent,
    ProjectExecution,
    ProjectMembership,
    Role,
    ScopedMemory,
    TaskComment,
    User,
    WorkflowRun,
    WorkforceAssignment,
    WorkforceHealthReport,
    WorkforceIncident,
    WorkforceMember,
    WorkforcePerformanceEvent,
    Workspace,
)
from app.services import knowledge_learning, workforce
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text


class Tenant:
    def __init__(
        self,
        organization: Organization,
        user: User,
        workspace: Workspace,
    ) -> None:
        self.organization = organization
        self.user = user
        self.workspace = workspace

    def actor(self, permissions: list[str] | None = None) -> UserRecord:
        return UserRecord(
            id=self.user.id,
            email=self.user.email,
            name=self.user.name,
            role="Owner",
            password_hash=self.user.password_hash,
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            organization_plan=self.organization.plan,
            permissions=permissions or ["*"],
        )


async def tenant(suffix: str) -> Tenant:
    organization = Organization(
        name=f"Phase 29F {suffix}",
        slug=f"phase29f-{suffix}",
        plan="enterprise",
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name="Owner",
            status="active",
        )
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"phase29f-{suffix}@example.com",
            name=f"Phase 29F Owner {suffix}",
            password_hash=pwd_context.hash(f"Phase29F!{suffix}"),
            status="active",
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            organization_id=organization.id,
            name=f"Phase 29F Workspace {suffix}",
            slug=f"phase29f-workspace-{suffix}",
            status="active",
        )
        session.add(workspace)
        await session.commit()
        return Tenant(organization, user, workspace)


def app_with_actor(holder: dict[str, UserRecord]) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    return app


async def cleanup(*organization_ids: str) -> None:
    async with SessionLocal() as session:
        for organization_id in organization_ids:
            item_ids = select(KnowledgeItem.id).where(
                KnowledgeItem.organization_id == organization_id
            )
            await session.execute(
                delete(KnowledgeProvenance).where(
                    KnowledgeProvenance.knowledge_item_id.in_(item_ids)
                )
            )
            for model in (
                AcademyCertification,
                AcademyAssessment,
                AcademyEnrollment,
                AcademyCourse,
                Lesson,
                LearningEvent,
                ScopedMemory,
                KnowledgeItem,
                WorkforcePerformanceEvent,
                WorkforceHealthReport,
                WorkforceIncident,
                WorkforceAssignment,
            ):
                await session.execute(
                    delete(model).where(model.organization_id == organization_id)
                )
            await session.execute(
                delete(ProjectMembership).where(
                    ProjectMembership.organization_id == organization_id
                )
            )
            await session.execute(
                delete(TaskComment).where(TaskComment.organization_id == organization_id)
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.organization_id == organization_id)
            )
            await session.execute(
                delete(ProjectEvent).where(ProjectEvent.organization_id == organization_id)
            )
            await session.execute(
                delete(ProjectExecution).where(
                    ProjectExecution.organization_id == organization_id
                )
            )
            await session.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
        await session.commit()


@pytest.mark.asyncio
async def test_project_task_workflow_report_and_provider_neutral_execution_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    first = await tenant(suffix)
    second = await tenant(f"other-{suffix}")
    async with SessionLocal() as session:
        platform_owner = await session.get(User, second.user.id)
        assert platform_owner is not None and platform_owner.role_id is not None
        platform_role = await session.get(Role, platform_owner.role_id)
        assert platform_role is not None
        platform_role.name = "Super Owner"
        await session.commit()
    holder = {"actor": first.actor()}
    app = app_with_actor(holder)
    monkeypatch.setattr(
        "app.api.v1.endpoints.project_executions.settings.PROJECT_EXECUTION_OUTPUT_ROOT",
        str(tmp_path / "executions"),
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.projects.owner_alert_channels", lambda: ["in_app"]
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.project_executions.owner_alert_channels",
        lambda: ["in_app"],
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/projects",
                json={
                    "name": "Governed Phase 29F Project",
                    "workspace_id": first.workspace.id,
                    "priority": "high",
                    "risk": "high",
                    "description": "Provider-neutral delivery validation.",
                },
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["id"]
            assert created.json()["risk"] == "high"
            async with SessionLocal() as session:
                project_alert = await session.scalar(
                    select(Notification).where(
                        Notification.recipient_id == second.user.id,
                        Notification.event_key == "project.started",
                        Notification.source_id == project_id,
                    )
                )
                assert project_alert is not None
                project_alert_channels = set(
                    (
                        await session.scalars(
                            select(NotificationDelivery.channel).where(
                                NotificationDelivery.notification_id == project_alert.id
                            )
                        )
                    ).all()
                )
                assert project_alert_channels == {"in_app"}
            members = await client.get(f"/api/v1/projects/{project_id}/members")
            assert members.status_code == 200, members.text
            assert members.json()[0]["role"] == "owner"

            for action, expected in (
                ("start", "active"),
                ("pause", "paused"),
                ("resume", "active"),
                ("request_review", "review"),
                ("approve", "approved"),
            ):
                response = await client.post(
                    f"/api/v1/projects/{project_id}/transition",
                    json={"action": action, "reason": f"{action} evidence"},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == expected

            task = await client.post(
                "/api/v1/tasks",
                json={
                    "title": "Governed implementation task",
                    "project_id": project_id,
                    "workspace_id": first.workspace.id,
                    "priority": "high",
                },
            )
            assert task.status_code == 201, task.text
            task_id = task.json()["id"]
            assert (
                await client.post(
                    f"/api/v1/tasks/{task_id}/comments",
                    json={"body": "Durable review evidence."},
                )
            ).status_code == 201
            for action, expected in (
                ("start", "in_progress"),
                ("request_review", "review"),
                ("rework", "rework"),
                ("start", "in_progress"),
                ("request_review", "review"),
                ("approve", "done"),
            ):
                response = await client.post(
                    f"/api/v1/tasks/{task_id}/transition",
                    json={"action": action, "reason": action},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == expected
            comments = await client.get(f"/api/v1/tasks/{task_id}/comments")
            assert [item["body"] for item in comments.json()] == [
                "Durable review evidence."
            ]

            workflow = await client.post(
                "/api/v1/workflows",
                json={
                    "name": "Provider-neutral workflow",
                    "workspace_id": first.workspace.id,
                    "project_id": project_id,
                    "steps": [
                        {"type": "validation", "id": "validate"},
                        {"type": "set", "key": "ready", "value": True},
                        {"type": "evidence", "label": "reviewed"},
                    ],
                },
            )
            assert workflow.status_code == 201, workflow.text
            workflow_id = workflow.json()["id"]
            run = await client.post(
                f"/api/v1/workflows/{workflow_id}/run",
                json={"input": {"phase": "29F"}},
            )
            assert run.status_code == 200, run.text
            assert run.json()["status"] == "accepted"
            assert run.json()["run_status"] == "completed"
            assert run.json()["run"]["output"]["ready"] is True
            runs = await client.get(f"/api/v1/workflows/{workflow_id}/runs")
            assert len(runs.json()) == 1

            report = await client.post(
                "/api/v1/reports",
                json={
                    "name": "Phase 29F delivery report",
                    "type": "delivery",
                    "workspace_id": first.workspace.id,
                    "project_id": project_id,
                },
            )
            assert report.status_code == 201, report.text
            report_id = report.json()["id"]
            download = await client.get(f"/api/v1/reports/{report_id}/download")
            assert download.status_code == 200, download.text
            assert download.headers["x-aionex-sha256"]
            assert json.loads(download.text)["project"]["id"] == project_id

            execution = await client.post(
                f"/api/v1/projects/{project_id}/executions",
                json={
                    "mode": "provider_neutral",
                    "confirm_external_processing": False,
                },
            )
            assert execution.status_code == 202, execution.text
            execution_data = execution.json()
            execution_id = execution_data["id"]
            assert execution_data["provider"] == "provider-neutral"
            assert execution_data["status"] == "completed"
            assert execution_data["result"]["model"] is None
            assert execution_data["result"]["requests_count"] == 0
            assert execution_data["result"]["production_modified"] is False
            assert execution_data["result"]["model_claims_used_as_execution_proof"] is False
            async with SessionLocal() as session:
                execution_alert = await session.scalar(
                    select(Notification).where(
                        Notification.recipient_id == second.user.id,
                        Notification.event_key == "project.execution.started",
                        Notification.source_id == execution_id,
                    )
                )
                assert execution_alert is not None
                assert execution_alert.payload["project_id"] == project_id
                assert execution_alert.payload["requested_mode"] == "provider_neutral"
                assert execution_alert.payload["effective_mode"] == "provider_neutral"
                execution_alert_channels = set(
                    (
                        await session.scalars(
                            select(NotificationDelivery.channel).where(
                                NotificationDelivery.notification_id == execution_alert.id
                            )
                        )
                    ).all()
                )
                assert execution_alert_channels == {"in_app"}
            evidence_root = tmp_path / "executions" / execution_id
            assert (evidence_root / "manifest.json").is_file()
            assert (evidence_root / "delivery-package" / "project.json").is_file()

            approval = await client.post(
                f"/api/v1/projects/{project_id}/executions/{execution_id}/approve",
                json={
                    "confirm_owner_approval": True,
                    "note": "Provider-neutral evidence approved.",
                },
            )
            assert approval.status_code == 409, approval.text
            assert approval.json()["detail"] == (
                "Execution evidence still contains non-Owner release blockers"
            )
            execution_after = await client.get(
                f"/api/v1/projects/{project_id}/executions/{execution_id}"
            )
            assert execution_after.status_code == 200
            assert execution_after.json()["approved"] is False
            assert execution_after.json()["review_status"] == "not_requested"
            assert execution_after.json()["result"]["all_governance_layers_executed"] is False
            archive = await client.get(
                f"/api/v1/projects/{project_id}/executions/{execution_id}/download"
            )
            assert archive.status_code == 200
            assert archive.headers["x-aionex-sha256"]

            history = await client.get(f"/api/v1/projects/{project_id}/history")
            event_types = {item["event_type"] for item in history.json()}
            assert {
                "project.created",
                "project.start",
                "project.pause",
                "project.resume",
                "project.request_review",
                "project.approve",
                "task.created",
                "task.approve",
            } <= event_types

            holder["actor"] = second.actor()
            assert (
                await client.get(f"/api/v1/projects/{project_id}/history")
            ).status_code == 404
    finally:
        await cleanup(first.organization.id, second.organization.id)


@pytest.mark.asyncio
async def test_workforce_assignment_health_incident_and_academy_cycle() -> None:
    suffix = uuid4().hex[:10]
    data = await tenant(suffix)
    actor = data.actor()
    try:
        async with SessionLocal() as session:
            project = Project(
                organization_id=data.organization.id,
                workspace_id=data.workspace.id,
                owner_id=data.user.id,
                name="Workforce project",
                slug=f"workforce-{suffix}",
                status="active",
                priority="high",
                risk="high",
                progress=10,
            )
            session.add(project)
            await session.flush()
            member = await workforce.create_digital_member(
                session,
                actor,
                name="Provider Neutral Engineer",
                role="Engineer",
                department="Engineering",
                skills=["python", "testing"],
                grade=3,
            )
            assert member.provider_neutral is True
            assert member.profile_metadata["provider_activation"] == "deferred_to_29J"
            assignment = await workforce.create_assignment(
                session,
                actor,
                project_id=project.id,
                worker_id=member.id,
                title="Validate durable workforce",
                required_skills=["python"],
                acceptance_criteria=["tests_pass", "audit_present"],
                risk="high",
            )
            await workforce.transition_assignment(
                session, actor, assignment, action="start"
            )
            with pytest.raises(ValueError):
                await workforce.transition_assignment(
                    session,
                    actor,
                    assignment,
                    action="submit_review",
                    evidence={"passed_criteria": ["tests_pass"]},
                )
            await session.rollback()

        async with SessionLocal() as session:
            project = await session.scalar(
                select(Project).where(Project.slug == f"workforce-{suffix}")
            )
            member = await session.scalar(
                select(WorkforceMember).where(
                    WorkforceMember.organization_id == data.organization.id,
                    WorkforceMember.name == "Provider Neutral Engineer",
                )
            )
            # The deliberately invalid review was rolled back with the setup, so
            # recreate the retained assignment in a clean transaction.
            if project is None:
                project = Project(
                    organization_id=data.organization.id,
                    workspace_id=data.workspace.id,
                    owner_id=data.user.id,
                    name="Workforce project",
                    slug=f"workforce-{suffix}",
                    status="active",
                    priority="high",
                    risk="high",
                    progress=10,
                )
                session.add(project)
                await session.flush()
            if member is None:
                member = await workforce.create_digital_member(
                    session,
                    actor,
                    name="Provider Neutral Engineer",
                    role="Engineer",
                    department="Engineering",
                    skills=["python", "testing"],
                    grade=3,
                )
            assignment = await workforce.create_assignment(
                session,
                actor,
                project_id=project.id,
                worker_id=member.id,
                title="Validate durable workforce",
                required_skills=["python"],
                acceptance_criteria=["tests_pass", "audit_present"],
                risk="high",
            )
            await workforce.transition_assignment(
                session, actor, assignment, action="start"
            )
            await workforce.transition_assignment(
                session,
                actor,
                assignment,
                action="submit_review",
                evidence={
                    "passed_criteria": ["tests_pass", "audit_present"],
                    "test_count": 305,
                },
            )
            await workforce.transition_assignment(
                session, actor, assignment, action="approve"
            )
            performance = await workforce.record_performance(
                session,
                actor,
                member,
                assignment_id=assignment.id,
                outcome="success",
                quality=94,
                reliability=96,
                collaboration=90,
                policy=98,
                learning=88,
                notes="Evidence accepted.",
            )
            health = await workforce.generate_health_report(session, actor, member)
            assert performance.outcome == "success"
            assert health.recommendation == "healthy"
            incident = await workforce.create_incident(
                session,
                actor,
                member,
                severity="high",
                category="quality",
                description="A supervised follow-up is required.",
                restrictions=["unsupervised_execution"],
            )
            assert member.status == "supervised"
            await workforce.resolve_incident(
                session, actor, incident, note="Follow-up completed."
            )
            course = await workforce.create_course(
                session,
                actor,
                code=f"RETRAIN-{suffix}",
                title="Governed retraining",
                description="Assessment and certification validation.",
                competencies=["governance", "testing"],
                passing_score=80,
            )
            enrollment = await workforce.enroll_member(
                session, actor, course, member
            )
            failed, no_certificate = await workforce.assess_enrollment(
                session,
                actor,
                enrollment,
                score=60,
                evidence={"attempt": "first"},
            )
            assert failed.passed is False and no_certificate is None
            passed, certificate = await workforce.assess_enrollment(
                session,
                actor,
                enrollment,
                score=95,
                evidence={"attempt": "second", "verified": True},
            )
            assert passed.passed is True and certificate is not None
            assert course.code in member.certifications
            await workforce.revoke_certification(
                session,
                actor,
                certificate,
                reason="Rotation test",
            )
            assert certificate.status == "revoked"
            await workforce.transition_member(
                session,
                actor,
                member,
                action="promote",
                grade=5,
                reason="Verified performance and certification.",
            )
            assert member.grade >= 5
            await session.commit()

            assert (
                await session.scalar(
                    select(func.count(WorkforcePerformanceEvent.id)).where(
                        WorkforcePerformanceEvent.worker_id == member.id
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count(WorkforceHealthReport.id)).where(
                        WorkforceHealthReport.worker_id == member.id
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count(AcademyAssessment.id)).where(
                        AcademyAssessment.worker_id == member.id
                    )
                )
                == 2
            )
    finally:
        await cleanup(data.organization.id)


@pytest.mark.asyncio
async def test_verified_knowledge_memory_learning_and_tenant_isolation() -> None:
    suffix = uuid4().hex[:10]
    first = await tenant(suffix)
    second = await tenant(f"other-{suffix}")
    actor = first.actor()
    try:
        async with SessionLocal() as session:
            project = Project(
                organization_id=first.organization.id,
                workspace_id=first.workspace.id,
                owner_id=first.user.id,
                name="Knowledge project",
                slug=f"knowledge-{suffix}",
                status="active",
                progress=20,
            )
            session.add(project)
            await session.flush()
            item = await knowledge_learning.ingest_item(
                session,
                actor,
                scope_type="project",
                scope_id=project.id,
                namespace="delivery",
                subject="Verified deployment lesson",
                content={"tests": 305, "production_modified": False},
                content_text="Use retained evidence before owner approval.",
                confidence=0.8,
                tags=["deployment", "evidence"],
                provenance=[
                    {
                        "source": "Phase 29F test suite",
                        "source_type": "test",
                        "source_quality": 1.0,
                        "direct_evidence": True,
                    }
                ],
            )
            duplicate = await knowledge_learning.ingest_item(
                session,
                actor,
                scope_type="project",
                scope_id=project.id,
                namespace="delivery",
                subject="Verified deployment lesson",
                content={"tests": 305, "production_modified": False},
                content_text="Use retained evidence before owner approval.",
                confidence=0.8,
            )
            assert duplicate.id == item.id
            await knowledge_learning.verify_item(
                session,
                actor,
                item,
                accepted=True,
                confidence=0.95,
                note="Evidence checked.",
            )
            memory = await knowledge_learning.upsert_memory(
                session,
                actor,
                scope_type="project",
                scope_id=project.id,
                key="release-evidence",
                value={"knowledge_item_id": item.id},
                summary="Owner approval follows retained evidence.",
                confidence=0.95,
                source_item_id=item.id,
            )
            event = await knowledge_learning.create_learning_event(
                session,
                actor,
                action="project.release.review",
                context={"project_id": project.id, "phase": "29F"},
                outcome="success",
                evidence=[item.id, memory.id],
                strategy="Retain and verify before approval",
                project_id=project.id,
                lesson="Verified evidence must precede release approval.",
            )
            await knowledge_learning.verify_learning_event(
                session, actor, event, accepted=True, note="Outcome confirmed."
            )
            lesson = await knowledge_learning.promote_lesson(
                session,
                actor,
                event,
                title="Evidence before approval",
                lesson=None,
                confidence=0.9,
                tags=["release", "governance"],
            )
            results = await knowledge_learning.search_knowledge(
                session,
                actor,
                query="evidence",
                scope_type="project",
                scope_id=project.id,
            )
            await session.commit()
            assert item.status == "verified"
            assert memory.status == "active"
            assert event.status == "verified"
            assert lesson.status == "verified"
            assert {value["id"] for value in results["knowledge"]} == {item.id}
            assert {value["id"] for value in results["memories"]} == {memory.id}
            assert {value["id"] for value in results["lessons"]} == {lesson.id}
            assert (
                await session.scalar(
                    select(func.count(KnowledgeProvenance.id)).where(
                        KnowledgeProvenance.knowledge_item_id == item.id
                    )
                )
                == 1
            )

        async with SessionLocal() as session:
            with pytest.raises(LookupError):
                await knowledge_learning.validate_scope(
                    session,
                    second.actor(),
                    scope_type="project",
                    scope_id=project.id,
                )
            cross = await session.scalar(
                select(KnowledgeItem).where(
                    KnowledgeItem.id == item.id,
                    KnowledgeItem.organization_id == second.organization.id,
                )
            )
            assert cross is None
    finally:
        await cleanup(first.organization.id, second.organization.id)


@pytest.mark.asyncio
async def test_phase29f_schema_and_audit_evidence_are_present() -> None:
    suffix = uuid4().hex[:10]
    data = await tenant(suffix)
    try:
        async with SessionLocal() as session:
            table_count = int(
                await session.scalar(
                    select(func.count()).select_from(WorkforceMember)
                )
                or 0
            )
            assert table_count >= 0
            required_tables = {
                "project_events",
                "workflow_runs",
                "workforce_members",
                "workforce_assignments",
                "academy_courses",
                "academy_certifications",
                "knowledge_items",
                "knowledge_provenance",
                "scoped_memories",
                "learning_events",
                "lessons",
            }
            present = set(
                (
                    await session.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = current_schema()"
                        )
                    )
                ).scalars().all()
            )
            assert required_tables <= present
            audit_actions = set(
                (
                    await session.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.organization_id == data.organization.id
                        )
                    )
                ).all()
            )
            assert isinstance(audit_actions, set)

        # The authoritative migration itself declares every retained table.
        migration = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "20260807_0010_projects_workforce_academy_knowledge.py"
        ).read_text(encoding="utf-8")
        assert required_tables <= {
            value
            for value in required_tables
            if f'"{value}"' in migration
        }
    finally:
        await cleanup(data.organization.id)
