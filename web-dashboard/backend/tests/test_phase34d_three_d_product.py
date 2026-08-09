from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.three_d_policy import (
    DEFAULT_THREE_D_POLICY,
    normalize_three_d_policy,
    three_d_access_allowed,
)
from app.services.three_d_product import (
    provider_error_requires_clarification,
    validate_image_payload,
)
from app.services.three_d_storage import ThreeDObjectStore
from app.services.three_d_worker import _env_file

ROOT = Path(__file__).resolve().parents[1]


def test_owner_policy_defaults_to_business_plus_entitlement_and_caps_values():
    policy = normalize_three_d_policy(
        {
            **DEFAULT_THREE_D_POLICY,
            "monthly_jobs_per_user": 9999,
            "max_input_megabytes": 500,
            "max_texture_size": 9999,
            "artifact_retention_days": 9999,
            "signed_url_ttl_seconds": 9999,
            "compression_policy": "invalid",
        }
    )
    assert policy["allowed_plan_codes"] == ["business"]
    assert policy["required_entitlement"] == "3d.generation"
    assert policy["monthly_jobs_per_user"] == 1000
    assert policy["max_input_megabytes"] == 50
    assert policy["max_texture_size"] == 4096
    assert policy["artifact_retention_days"] == 365
    assert policy["signed_url_ttl_seconds"] == 3600
    assert policy["compression_policy"] == "compat"


def test_owner_explicit_allow_and_deny_have_expected_precedence():
    policy = normalize_three_d_policy(
        {
            **DEFAULT_THREE_D_POLICY,
            "allowed_user_ids": ["override"],
            "denied_user_ids": ["denied"],
        }
    )
    assert three_d_access_allowed(
        policy, user_id="override", plan_code="free", entitlements=[]
    )
    assert not three_d_access_allowed(
        policy, user_id="denied", plan_code="business", entitlements=["3d.generation"]
    )
    assert three_d_access_allowed(
        policy,
        user_id="business-user",
        plan_code="business",
        entitlements=["3d.generation"],
    )
    assert not three_d_access_allowed(
        policy,
        user_id="professional-user",
        plan_code="professional",
        entitlements=["3d.generation"],
    )


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("image/png", b"\x89PNG\r\n\x1a\nvalid"),
        ("image/jpeg", b"\xff\xd8\xffvalid"),
        ("image/webp", b"RIFF1234WEBPvalid"),
    ],
)
def test_source_image_magic_validation_accepts_supported_formats(
    content_type: str, body: bytes
):
    validate_image_payload(content_type, body, 1024)


def test_source_image_validation_rejects_mime_spoof_and_owner_size_overflow():
    with pytest.raises(HTTPException) as spoofed:
        validate_image_payload("image/png", b"not-a-png", 1024)
    assert spoofed.value.status_code == 422
    assert spoofed.value.detail["code"] == "THREE_D_IMAGE_UNSUPPORTED"
    with pytest.raises(HTTPException) as large:
        validate_image_payload("image/jpeg", b"\xff\xd8\xff" + b"x" * 20, 10)
    assert large.value.status_code == 413
    assert large.value.detail["code"] == "THREE_D_IMAGE_TOO_LARGE"


def test_provider_input_failures_are_routed_to_clarification_not_fake_success():
    assert provider_error_requires_clarification(
        "UnidentifiedImageError: cannot identify image file"
    )
    assert provider_error_requires_clarification("invalid image decode")
    assert not provider_error_requires_clarification("CUDA out of memory")


def test_private_storage_keys_are_tenant_and_project_scoped():
    assert (
        ThreeDObjectStore.input_key("org", "project", "job", "PNG")
        == "3d/org/project/job/input.png"
    )
    assert (
        ThreeDObjectStore.output_key("org", "project", "job")
        == "3d/org/project/job/final.glb"
    )


def test_runpod_env_loader_rejects_symlink_and_never_requires_shell_eval(
    tmp_path: Path,
):
    secret = tmp_path / "runpod.env"
    secret.write_text(
        "RUNPOD_API_KEY=secret\nRUNPOD_ENDPOINT_ID=endpoint\n", encoding="utf-8"
    )
    assert _env_file(str(secret)) == {
        "RUNPOD_API_KEY": "secret",
        "RUNPOD_ENDPOINT_ID": "endpoint",
    }
    link = tmp_path / "link.env"
    link.symlink_to(secret)
    with pytest.raises(RuntimeError):
        _env_file(str(link))


def test_immediate_queued_cancel_removes_private_input_object():
    source = (ROOT / "app/api/v1/endpoints/three_d_jobs.py").read_text()
    assert (
        'immediate_cancel = job.status == "queued" and not job.provider_job_id'
        in source
    )
    assert "ThreeDObjectStore().delete(input_key)" in source


def test_processing_notification_reaches_user_and_owner():
    source = (ROOT / "app/services/three_d_worker.py").read_text()
    marker = 'event_key="3d.job.processing"'
    block = source[source.index(marker) : source.index(marker) + 500]
    assert "include_owner=True" in block


@pytest.mark.asyncio
async def test_project_3d_api_lifecycle_is_tenant_scoped_and_issues_only_signed_artifact_links(
    monkeypatch,
):
    from datetime import UTC, datetime, timedelta
    from io import BytesIO

    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from sqlalchemy import select

    from app.api.v1.endpoints import three_d_jobs
    from app.core.auth import UserRecord
    from app.db.base import SessionLocal
    from app.db.models import (
        Organization,
        Project,
        ThreeDArtifact,
        User,
        Workspace,
        uuid_str,
    )
    from app.services.three_d_storage import StoredObject

    class FakeStore:
        deleted: list[str] = []
        uploaded: dict[str, bytes] = {}

        @staticmethod
        def input_key(
            organization_id: str, project_id: str, job_id: str, suffix: str
        ) -> str:
            return ThreeDObjectStore.input_key(
                organization_id, project_id, job_id, suffix
            )

        def put_bytes(self, key: str, body: bytes, content_type: str, *, metadata=None):
            from hashlib import sha256

            self.uploaded[key] = body
            return StoredObject(key, len(body), sha256(body).hexdigest(), content_type)

        def delete(self, key: str) -> None:
            self.deleted.append(key)
            self.uploaded.pop(key, None)

        def presigned_get(
            self,
            key: str,
            *,
            filename: str,
            content_type: str,
            expires_seconds: int,
            inline: bool,
        ) -> str:
            mode = "view" if inline else "download"
            return f"https://private-storage.invalid/{mode}/{key}?ttl={expires_seconds}"

    async def fake_access(_session, _actor, *, lock_policy=False):
        del lock_policy
        return {
            "eligible": True,
            "plan_code": "business",
            "required_entitlement": "3d.generation",
            "monthly_quota": 20,
            "monthly_used": 0,
            "monthly_remaining": 20,
            "active_jobs": 0,
            "max_concurrent_jobs": 1,
            "max_input_megabytes": 12,
            "max_texture_size": 2048,
            "compression_policy": "compat",
            "signed_url_ttl_seconds": 900,
            "owner_managed": True,
            "service_enabled": True,
        }

    async def fake_admission(_session, _actor):
        return (
            {
                "max_texture_size": 2048,
                "compression_policy": "compat",
                "max_retries": 1,
            },
            {"reserved_estimated_cost_usd": 0.36},
        )

    async def no_notifications(*_args, **_kwargs):
        return []

    monkeypatch.setattr(three_d_jobs, "ThreeDObjectStore", FakeStore)
    monkeypatch.setattr(three_d_jobs, "access_snapshot", fake_access)
    monkeypatch.setattr(three_d_jobs, "enforce_admission", fake_admission)
    monkeypatch.setattr(three_d_jobs, "notify_job", no_notifications)

    suffix = uuid_str()
    async with SessionLocal() as session:
        organization = Organization(
            id=uuid_str(),
            name=f"Phase34D API {suffix[:8]}",
            slug=f"phase34d-api-{suffix}",
            plan="business",
            status="active",
        )
        session.add(organization)
        await session.flush()
        workspace = Workspace(
            id=uuid_str(),
            organization_id=organization.id,
            name="3D Workspace",
            slug="3d-workspace",
            status="active",
        )
        session.add(workspace)
        await session.flush()
        user = User(
            id=uuid_str(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            email=f"phase34d-api-{suffix}@example.invalid",
            name="Phase34D API User",
            password_hash="not-used",
            status="active",
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid_str(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="3D API Project",
            slug="3d-api-project",
            status="planning",
            priority="medium",
            progress=0,
            tags=[],
            risk="normal",
            review_status="not_requested",
            version=1,
        )
        session.add(project)
        await session.commit()

        actor = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role="Owner",
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            organization_plan="business",
            permissions=["projects:read", "projects:write"],
        )
        source = b"\x89PNG\r\n\x1a\nphase34d-api"
        upload = UploadFile(
            file=BytesIO(source),
            filename="source.png",
            headers=Headers({"content-type": "image/png"}),
        )
        created = await three_d_jobs.create_three_d_job(
            project.id, upload, 12345, 1024, actor, session
        )
        assert created["status"] == "queued"
        assert created["organization_id"] == organization.id
        assert created["project_id"] == project.id
        assert created["has_artifact"] is False

        rows = await three_d_jobs.list_three_d_jobs(project.id, 20, actor, session)
        assert [item["id"] for item in rows] == [created["id"]]
        loaded = await three_d_jobs.get_three_d_job(
            project.id, created["id"], actor, session
        )
        assert loaded["id"] == created["id"]

        outsider = UserRecord(
            id=uuid_str(),
            email="outside@example.invalid",
            name="Outside",
            role="Owner",
            password_hash="not-used",
            organization_id=uuid_str(),
            organization_name="Other org",
            organization_plan="business",
            permissions=["projects:read", "projects:write"],
        )
        with pytest.raises(HTTPException) as isolated:
            await three_d_jobs.get_three_d_job(
                project.id, created["id"], outsider, session
            )
        assert isolated.value.status_code == 404

        cancelled = await three_d_jobs.cancel_three_d_job(
            project.id, created["id"], actor, session
        )
        assert cancelled["status"] == "cancelled"
        assert FakeStore.deleted

        job = await session.scalar(
            select(three_d_jobs.ThreeDGenerationJob).where(
                three_d_jobs.ThreeDGenerationJob.id == created["id"]
            )
        )
        assert job is not None
        job.status = "completed"
        job.stage = "completed"
        job.progress = 100
        job.completed_at = datetime.now(UTC)
        artifact = ThreeDArtifact(
            id=uuid_str(),
            organization_id=organization.id,
            project_id=project.id,
            job_id=job.id,
            created_by_id=user.id,
            filename="final.glb",
            media_type="model/gltf-binary",
            object_key=f"3d/{organization.id}/{project.id}/{job.id}/final.glb",
            checksum="a" * 64,
            size_bytes=2734648,
            status="ready",
            artifact_metadata={"fallback_used": False, "pbr_material_count": 1},
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add(artifact)
        await session.commit()

        links = await three_d_jobs.get_three_d_artifact_links(
            project.id, job.id, actor, session
        )
        assert links["view_url"].startswith("https://private-storage.invalid/view/")
        assert links["download_url"].startswith(
            "https://private-storage.invalid/download/"
        )
        assert links["expires_in"] == 900
        assert links["sha256"] == "a" * 64


def test_billing_sync_backfills_business_3d_entitlement_for_older_published_catalogues():
    from app.services.billing import THREE_D_BUSINESS_ENTITLEMENT

    source = (ROOT / "app/services/billing.py").read_text()
    assert THREE_D_BUSINESS_ENTITLEMENT == "3d.generation"
    assert 'if code == "business":' in source
    assert (
        "entitlements = sorted(set(entitlements) | {THREE_D_BUSINESS_ENTITLEMENT})"
        in source
    )
