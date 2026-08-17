"""Phase 36D Studio API contracts for tenant-safe media graph orchestration."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import Organization, Project, Role, StudioAsset, StudioJob, User, Workspace


class Tenant:
    def __init__(
        self,
        organization: Organization,
        user: User,
        workspace: Workspace,
        project: Project,
        asset_id: str,
    ) -> None:
        self.organization = organization
        self.user = user
        self.workspace = workspace
        self.project = project
        self.asset_id = asset_id

    def actor(self) -> UserRecord:
        return UserRecord(
            id=self.user.id,
            email=self.user.email,
            name=self.user.name,
            role="Owner",
            password_hash=self.user.password_hash,
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            organization_plan=self.organization.plan,
            permissions=["*"],
        )


async def seed_tenant(tag: str) -> Tenant:
    suffix = f"{tag}-{uuid4().hex[:8]}"
    async with SessionLocal() as session:
        organization = Organization(
            name=f"P36D {suffix}",
            slug=f"p36d-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(organization)
        await session.flush()
        role = Role(organization_id=organization.id, name="Owner", status="active")
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"{suffix}@example.com",
            name="P36D Owner",
            password_hash=pwd_context.hash("Phase36D!StrongPassword"),
            status="active",
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            organization_id=organization.id,
            name="P36D Workspace",
            slug=f"ws-{suffix}",
            status="active",
        )
        session.add(workspace)
        await session.flush()
        project = Project(
            organization_id=organization.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="P36D Project",
            slug=f"project-{suffix}",
            description="Media API acceptance",
            status="active",
            priority="high",
            progress=10,
        )
        session.add(project)
        await session.flush()
        job = StudioJob(
            organization_id=organization.id,
            workspace_id=workspace.id,
            project_id=project.id,
            requested_by_id=user.id,
            department="video",
            output_kind="video",
            title="P36D Studio Asset",
            brief="Render a governed media graph for API acceptance.",
            language="en-US",
            style="modern",
            provider_mode="provider_neutral",
            status="completed",
            progress=100,
            safety_status="passed",
            request_metadata={},
            result_metadata={},
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            organization_id=organization.id,
            job_id=job.id,
            project_id=project.id,
            created_by_id=user.id,
            department="video",
            asset_type="video",
            title="P36D Studio Asset",
            filename="source.zip",
            media_type="application/zip",
            storage_path="/tmp/source.zip",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={},
        )
        session.add(asset)
        await session.commit()
        return Tenant(organization, user, workspace, project, asset.id)


def app_with_actor(holder: dict[str, UserRecord]) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    return app


async def cleanup(*organization_ids: str) -> None:
    async with SessionLocal() as session:
        for organization_id in organization_ids:
            await session.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
        await session.commit()


@pytest.mark.asyncio
async def test_studio_media_graph_api_is_tenant_scoped_prompt_free_and_revision_safe() -> None:
    first = await seed_tenant("first")
    second = await seed_tenant("second")
    holder = {"actor": first.actor()}
    app = app_with_actor(holder)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                f"/api/v1/studio/assets/{first.asset_id}/media-graphs",
                json={
                    "title": "Two-scene API graph",
                    "asset_kind": "video",
                    "output_profile": "video-mp4-h264",
                    "idempotency_key": f"api-{uuid4()}",
                    "rights_metadata": {"owner_consent": True},
                    "provenance": [{"type": "api-test"}],
                    "nodes": [
                        {
                            "key": "scene-a",
                            "node_type": "scene",
                            "media_type": "video/mp4",
                            "parameters": {
                                "operation": "render_scene",
                                "output_profile": "video-mp4-h264",
                                "duration_seconds": 1.0,
                                "color": "#2563eb",
                            },
                            "prompt_metadata": {
                                "private_prompt": "must-not-leak"
                            },
                        },
                        {
                            "key": "scene-b",
                            "node_type": "scene",
                            "media_type": "video/mp4",
                            "parameters": {
                                "operation": "render_scene",
                                "output_profile": "video-mp4-h264",
                                "duration_seconds": 1.0,
                                "color": "#dc2626",
                            },
                        },
                        {
                            "key": "final",
                            "node_type": "assembly",
                            "media_type": "video/mp4",
                            "parameters": {
                                "operation": "assemble",
                                "output_profile": "video-mp4-h264",
                            },
                        },
                    ],
                    "edges": [
                        {"parent": "scene-a", "child": "final", "ordinal": 0},
                        {"parent": "scene-b", "child": "final", "ordinal": 1},
                    ],
                },
            )
            assert created.status_code == 202, created.text
            payload = created.json()
            graph_id = payload["id"]
            assert payload["status"] == "planned"
            assert "private_prompt" not in created.text
            assert "must-not-leak" not in created.text
            assert "storage_key" not in created.text

            listed = await client.get(
                f"/api/v1/studio/assets/{first.asset_id}/media-graphs"
            )
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == graph_id

            fetched = await client.get(f"/api/v1/studio/media-graphs/{graph_id}")
            assert fetched.status_code == 200
            assert len(fetched.json()["render_steps"]) == 3

            premature = await client.post(
                f"/api/v1/studio/media-graphs/{graph_id}/revisions",
                json={
                    "idempotency_key": f"rev-{uuid4()}",
                    "node_parameter_updates": {"scene-b": {"color": "#16a34a"}},
                },
            )
            assert premature.status_code == 409

            output = await client.get(f"/api/v1/studio/media-graphs/{graph_id}/output")
            assert output.status_code == 409

            holder["actor"] = second.actor()
            assert (
                await client.get(f"/api/v1/studio/media-graphs/{graph_id}")
            ).status_code == 404
    finally:
        await cleanup(first.organization.id, second.organization.id)
