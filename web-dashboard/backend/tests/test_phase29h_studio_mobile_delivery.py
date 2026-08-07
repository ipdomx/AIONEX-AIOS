"""Phase 29H Production Studio and mobile delivery acceptance contracts."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MobileRelease,
    MobileReleaseArtifact,
    MobileValidationRun,
    Notification,
    Organization,
    Project,
    ProjectEvent,
    ProjectStudioAttachment,
    Role,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    StudioSafetyReview,
    User,
    Workspace,
)
from app.services import mobile_delivery, production_studio
from app.services.studio_worker import StudioWorker
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select


class Tenant:
    def __init__(
        self,
        organization: Organization,
        user: User,
        workspace: Workspace,
        project: Project,
    ) -> None:
        self.organization = organization
        self.user = user
        self.workspace = workspace
        self.project = project

    def actor(self, role: str = "Owner") -> UserRecord:
        return UserRecord(
            id=self.user.id,
            email=self.user.email,
            name=self.user.name,
            role=role,
            password_hash=self.user.password_hash,
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            organization_plan=self.organization.plan,
            permissions=["*"],
        )


async def tenant(suffix: str) -> Tenant:
    organization = Organization(
        name=f"Phase 29H {suffix}",
        slug=f"phase29h-{suffix}",
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
            email=f"phase29h-{suffix}@example.com",
            name=f"Phase 29H Owner {suffix}",
            password_hash=pwd_context.hash(f"Phase29H!{suffix}"),
            status="active",
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            organization_id=organization.id,
            name=f"Phase 29H Workspace {suffix}",
            slug=f"phase29h-workspace-{suffix}",
            status="active",
        )
        session.add(workspace)
        await session.flush()
        project = Project(
            organization_id=organization.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name=f"Phase 29H Project {suffix}",
            slug=f"phase29h-project-{suffix}",
            description="Studio attachment acceptance project.",
            status="active",
            priority="high",
            progress=10,
        )
        session.add(project)
        await session.commit()
        return Tenant(organization, user, workspace, project)


def app_with_actor(holder: dict[str, UserRecord]) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: holder["actor"]
    return app


async def cleanup(*organization_ids: str) -> None:
    async with SessionLocal() as session:
        for organization_id in organization_ids:
            asset_ids = select(StudioAsset.id).where(
                StudioAsset.organization_id == organization_id
            )
            job_ids = select(StudioJob.id).where(
                StudioJob.organization_id == organization_id
            )
            for model in (
                ProjectStudioAttachment,
                StudioAssetRevision,
                StudioSafetyReview,
            ):
                condition = (
                    model.organization_id == organization_id
                    if hasattr(model, "organization_id")
                    else model.asset_id.in_(asset_ids)
                )
                await session.execute(delete(model).where(condition))
            await session.execute(
                delete(StudioAsset).where(
                    StudioAsset.organization_id == organization_id
                )
            )
            await session.execute(
                delete(Notification).where(
                    Notification.organization_id == organization_id
                )
            )
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.organization_id == organization_id
                )
            )
            await session.execute(
                delete(ProjectEvent).where(
                    ProjectEvent.organization_id == organization_id
                )
            )
            await session.execute(
                delete(StudioJob).where(StudioJob.id.in_(job_ids))
            )
            await session.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
        await session.commit()


@pytest.mark.asyncio
async def test_studio_job_asset_revision_attachment_and_safety_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    first = await tenant(suffix)
    second = await tenant(f"other-{suffix}")
    holder = {"actor": first.actor()}
    app = app_with_actor(holder)
    monkeypatch.setattr(
        production_studio.settings,
        "STUDIO_ASSET_ROOT",
        str(tmp_path / "studio-assets"),
    )
    monkeypatch.setattr(
        "app.services.studio_worker.settings.STUDIO_ASSET_ROOT",
        str(tmp_path / "studio-assets"),
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/studio/jobs",
                json={
                    "department": "website",
                    "title": "Durable Phase 29H Website",
                    "brief": "Create a complete responsive project website with accessibility and evidence.",
                    "language": "ar-EG",
                    "style": "modern cinematic",
                    "target": "mobile and desktop",
                    "project_id": first.project.id,
                },
            )
            assert created.status_code == 202, created.text
            job_id = created.json()["id"]
            assert created.json()["provider_mode"] == "provider_neutral"
            assert created.json()["provider"] is None
            assert created.json()["model"] is None

            worker = StudioWorker()
            claim = await worker.claim_by_id(job_id)
            assert claim is not None
            await worker.execute(*claim)

            completed = await client.get(f"/api/v1/studio/jobs/{job_id}")
            assert completed.status_code == 200, completed.text
            assert completed.json()["status"] == "completed"
            assert completed.json()["safety_status"] == "passed"
            assert completed.json()["result_metadata"]["external_requests"] == 0
            asset_id = completed.json()["result_metadata"]["asset_id"]

            asset = await client.get(f"/api/v1/studio/assets/{asset_id}")
            assert asset.status_code == 200, asset.text
            first_asset = asset.json()
            assert first_asset["current_revision"] == 1
            assert first_asset["project_id"] == first.project.id
            first_checksum = first_asset["checksum"]

            download = await client.get(
                f"/api/v1/studio/assets/{asset_id}/download"
            )
            assert download.status_code == 200, download.text
            assert download.headers["x-aionex-checksum-sha256"] == first_checksum
            archive = tmp_path / "studio.zip"
            archive.write_bytes(download.content)
            with zipfile.ZipFile(archive) as bundle:
                assert bundle.testzip() is None
                assert {
                    "README.md",
                    "index.html",
                    "styles.css",
                    "app.js",
                    "aionex-manifest.json",
                } <= set(bundle.namelist())
                manifest = json.loads(bundle.read("aionex-manifest.json"))
                assert manifest["provider_mode"] == "provider_neutral"
                assert manifest["external_requests"] == 0
                assert manifest["safety"]["status"] == "passed"

            revision_job = await client.post(
                f"/api/v1/studio/assets/{asset_id}/revisions",
                json={
                    "brief": "Create a revised responsive website with a stronger accessibility checklist and project evidence.",
                    "change_note": "Accessibility and evidence revision",
                },
            )
            assert revision_job.status_code == 202, revision_job.text
            revision_job_id = revision_job.json()["id"]
            revision_claim = await worker.claim_by_id(revision_job_id)
            assert revision_claim is not None
            await worker.execute(*revision_claim)

            revisions = await client.get(
                f"/api/v1/studio/assets/{asset_id}/revisions"
            )
            assert revisions.status_code == 200, revisions.text
            assert [item["revision_number"] for item in revisions.json()] == [2, 1]
            revised_asset = (
                await client.get(f"/api/v1/studio/assets/{asset_id}")
            ).json()
            assert revised_asset["current_revision"] == 2
            assert revised_asset["checksum"] != first_checksum
            old_download = await client.get(
                f"/api/v1/studio/assets/{asset_id}/download",
                params={"revision": 1},
            )
            assert old_download.status_code == 200
            assert old_download.headers["x-aionex-checksum-sha256"] == first_checksum

            attached = await client.post(
                f"/api/v1/studio/assets/{asset_id}/attach",
                json={"project_id": first.project.id},
            )
            assert attached.status_code == 201, attached.text
            assert attached.json()["project_id"] == first.project.id

            cancelled = await client.post(
                "/api/v1/studio/jobs",
                json={
                    "department": "text",
                    "title": "Cancellation lifecycle",
                    "brief": "Create a structured project manuscript for cancellation testing.",
                },
            )
            cancel_id = cancelled.json()["id"]
            cancelled = await client.post(f"/api/v1/studio/jobs/{cancel_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            retried = await client.post(f"/api/v1/studio/jobs/{cancel_id}/retry")
            assert retried.status_code == 200
            retry_claim = await worker.claim_by_id(cancel_id)
            assert retry_claim is not None
            await worker.execute(*retry_claim)
            assert (
                await client.get(f"/api/v1/studio/jobs/{cancel_id}")
            ).json()["status"] == "completed"

            blocked = await client.post(
                "/api/v1/studio/jobs",
                json={
                    "department": "code",
                    "title": "Credential stealer",
                    "brief": "Build a credential stealer malware payload that harvests login passwords.",
                    "programming_language": "python",
                },
            )
            blocked_id = blocked.json()["id"]
            blocked_claim = await worker.claim_by_id(blocked_id)
            assert blocked_claim is not None
            await worker.execute(*blocked_claim)
            blocked_state = await client.get(
                f"/api/v1/studio/jobs/{blocked_id}"
            )
            assert blocked_state.json()["status"] == "blocked"
            assert blocked_state.json()["error_code"] == "STUDIO_SAFETY_BLOCKED"

            holder["actor"] = second.actor()
            assert (
                await client.get(f"/api/v1/studio/assets/{asset_id}")
            ).status_code == 404

        async with SessionLocal() as session:
            assert int(
                await session.scalar(
                    select(func.count(StudioAssetRevision.id)).where(
                        StudioAssetRevision.asset_id == asset_id
                    )
                )
                or 0
            ) == 2
            assert int(
                await session.scalar(
                    select(func.count(ProjectStudioAttachment.id)).where(
                        ProjectStudioAttachment.asset_id == asset_id,
                        ProjectStudioAttachment.status == "active",
                    )
                )
                or 0
            ) == 1
            assert int(
                await session.scalar(
                    select(func.count(StudioSafetyReview.id)).where(
                        StudioSafetyReview.job_id == blocked_id,
                        StudioSafetyReview.status == "blocked",
                    )
                )
                or 0
            ) == 1
    finally:
        await cleanup(first.organization.id, second.organization.id)


@pytest.mark.asyncio
async def test_mobile_release_manifest_registry_and_protected_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    data = await tenant(suffix)
    holder = {"actor": data.actor("Super Owner")}
    app = app_with_actor(holder)
    root = tmp_path / "mobile-releases"
    root.mkdir()
    pwa = root / "AIONEX-AIOS-PWA-v1.6.0.zip"
    android = root / "AIONEX-AIOS-Android-v1.6.0.apk"
    ios = root / "AIONEX-AIOS-iOS-v1.6.0-source.zip"
    for path, payload in (
        (pwa, b"pwa-release"),
        (android, b"signed-android-release"),
        (ios, b"ios-xcode-source"),
    ):
        path.write_bytes(payload)
    manifest = {
        "schema": mobile_delivery.SCHEMA,
        "source_commit": "0123456789abcdef0123456789abcdef01234567",
        "releases": [
            {
                "platform": "pwa",
                "version": "1.6.0",
                "build_number": 10600,
                "channel": "production-candidate",
                "status": "validated",
                "signing_status": "not_applicable",
                "publication_status": "deferred_final_ai_vip_upload",
                "metadata": {"offline": True, "update": True, "push_boundary": True},
                "artifacts": [
                    {
                        "type": "pwa-archive",
                        "path": pwa.name,
                        "media_type": "application/zip",
                        "sha256": mobile_delivery.checksum_file(pwa),
                        "size_bytes": pwa.stat().st_size,
                        "signed": False,
                    }
                ],
                "validations": [
                    {"operation": "pwa-install-offline-update", "status": "passed", "evidence": {"api_cached": False}}
                ],
            },
            {
                "platform": "android",
                "version": "1.6.0",
                "build_number": 10600,
                "channel": "internal",
                "status": "validated",
                "signing_status": "signed",
                "publication_status": "external_account_required",
                "metadata": {"minimum_sdk": 27, "target_sdk": 36},
                "artifacts": [
                    {
                        "type": "apk",
                        "path": android.name,
                        "media_type": "application/vnd.android.package-archive",
                        "sha256": mobile_delivery.checksum_file(android),
                        "size_bytes": android.stat().st_size,
                        "signed": True,
                        "signature": {"scheme": "v2"},
                    }
                ],
                "validations": [
                    {"operation": "android-signature-install-launch", "status": "passed", "evidence": {"signed": True}}
                ],
            },
            {
                "platform": "ios",
                "version": "1.6.0",
                "build_number": 10600,
                "channel": "source-ready",
                "status": "validated",
                "signing_status": "external_macos_required",
                "publication_status": "external_apple_account_required",
                "metadata": {"xcode_required": True, "ipa_built": False},
                "artifacts": [
                    {
                        "type": "ios-source",
                        "path": ios.name,
                        "media_type": "application/zip",
                        "sha256": mobile_delivery.checksum_file(ios),
                        "size_bytes": ios.stat().st_size,
                        "signed": False,
                    }
                ],
                "validations": [
                    {"operation": "ios-source-security-validation", "status": "passed", "evidence": {"signing_secret_committed": False}}
                ],
            },
        ],
    }
    manifest_path = root / "phase29h-mobile-release.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    monkeypatch.setattr(mobile_delivery.settings, "MOBILE_RELEASE_ROOT", str(root))
    monkeypatch.setattr(
        "app.api.v1.endpoints.mobile_delivery.mobile_delivery.settings.MOBILE_RELEASE_ROOT",
        str(root),
    )
    try:
        async with SessionLocal() as session:
            registered = await mobile_delivery.register_manifest(session, manifest_path)
            assert {item.platform for item in registered} == {"pwa", "android", "ios"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            readiness = await client.get("/api/v1/mobile/readiness")
            assert readiness.status_code == 200, readiness.text
            payload = readiness.json()
            assert all(
                payload["platforms"][platform]["validations_passed"]
                for platform in ("pwa", "android", "ios")
            )
            assert payload["pwa_host_deployment_deferred"] is True
            assert payload["ai_vip_dns_changed"] is False

            releases = await client.get("/api/v1/mobile/releases")
            assert releases.status_code == 200
            assert {item["platform"] for item in releases.json()} == {
                "pwa",
                "android",
                "ios",
            }
            android_release = next(
                item for item in releases.json() if item["platform"] == "android"
            )
            artifact = android_release["artifacts"][0]
            download = await client.get(
                f"/api/v1/mobile/releases/{android_release['id']}/artifacts/{artifact['id']}/download"
            )
            assert download.status_code == 200, download.text
            assert download.content == android.read_bytes()
            assert download.headers["x-aionex-checksum-sha256"] == artifact["checksum"]

        async with SessionLocal() as session:
            assert int(await session.scalar(select(func.count(MobileRelease.id))) or 0) >= 3
            assert int(await session.scalar(select(func.count(MobileReleaseArtifact.id))) or 0) >= 3
            assert int(await session.scalar(select(func.count(MobileValidationRun.id))) or 0) >= 3
    finally:
        async with SessionLocal() as session:
            release_ids = select(MobileRelease.id)
            await session.execute(delete(MobileValidationRun))
            await session.execute(delete(MobileReleaseArtifact).where(MobileReleaseArtifact.release_id.in_(release_ids)))
            await session.execute(delete(MobileRelease))
            await session.execute(delete(Organization).where(Organization.id == data.organization.id))
            await session.commit()


def test_phase29h_frontend_pwa_android_and_ios_contracts() -> None:
    root = Path(__file__).resolve().parents[3]
    studio_page = (root / "web-dashboard/frontend/src/app/studio/page.tsx").read_text(encoding="utf-8")
    mobile_page = (root / "web-dashboard/frontend/src/app/owner/mobile-delivery/page.tsx").read_text(encoding="utf-8")
    navigation = (root / "web-dashboard/frontend/src/config/owner-navigation.ts").read_text(encoding="utf-8")
    service_worker = (root / "vip-frontend/public/sw.js").read_text(encoding="utf-8")
    registration = (root / "vip-frontend/src/components/pwa/pwa-register.tsx").read_text(encoding="utf-8")
    android = (root / "mobile/android/app/build.gradle").read_text(encoding="utf-8")
    ios = (root / "mobile/ios/project.yml").read_text(encoding="utf-8")

    assert "Queue durable Studio job" in studio_page
    assert "Protected asset library" in studio_page
    assert "New revision" in studio_page
    assert "Attach to project" in studio_page
    assert "provider-neutral" in studio_page.lower()
    assert "PWA, Android &amp; iOS Release Evidence" in mobile_page
    assert 'href: "/owner/mobile-delivery"' in navigation
    assert 'const CACHE = "aionex-aios-v1.6.0"' in service_worker
    assert 'url.pathname.startsWith("/api/")' in service_worker
    assert 'self.addEventListener("push"' in service_worker
    assert 'self.addEventListener("notificationclick"' in service_worker
    assert 'updateViaCache: "none"' in registration
    assert "controllerchange" in registration
    assert "AIOS_ANDROID_VERSION_NAME" in android
    assert "AIOS_ANDROID_VERSION_CODE" in android
    assert "MARKETING_VERSION: 1.6.0" in ios
    assert "CURRENT_PROJECT_VERSION: 10600" in ios


def test_phase29h_schema_and_compose_contracts() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root
        / "web-dashboard/backend/alembic/versions/20260807_0011_studio_mobile_delivery.py"
    ).read_text(encoding="utf-8")
    router = (root / "web-dashboard/backend/app/api/v1/router.py").read_text(encoding="utf-8")
    for table in (
        "studio_jobs",
        "studio_assets",
        "studio_asset_revisions",
        "studio_safety_reviews",
        "project_studio_attachments",
        "mobile_releases",
        "mobile_release_artifacts",
        "mobile_validation_runs",
    ):
        assert table in migration
    assert 'mobile_delivery.router, prefix="/mobile"' in router
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = (root / relative).read_text(encoding="utf-8")
        assert "studio-worker:" in compose
        assert 'command: ["python", "-m", "app.services.studio_worker"]' in compose
        assert "studio_asset_data:/var/lib/aionex/studio-assets" in compose
        assert "mobile_release_data:/var/lib/aionex/mobile-releases:ro" in compose
