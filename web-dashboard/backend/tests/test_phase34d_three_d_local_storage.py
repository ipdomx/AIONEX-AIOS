from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import three_d_jobs
from app.core.config import settings
from app.services.three_d_storage import (
    GLB_MEDIA_TYPE,
    ThreeDObjectStore,
    ThreeDStorageError,
    issue_local_artifact_token,
    local_artifact_url,
    verify_local_artifact_token,
)


def _ids() -> tuple[str, str, str]:
    return (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )


def test_local_three_d_store_is_private_atomic_and_integrity_checked(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "three-d-assets"
    monkeypatch.setattr(settings, "THREE_D_STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "THREE_D_STORAGE_ROOT", str(root))
    store = ThreeDObjectStore()
    assert store.is_local is True
    assert root.stat().st_mode & 0o077 == 0
    store.preflight()

    project_id, job_id, _ = _ids()
    key = store.output_key("org", project_id, job_id)
    body = b"glTF-local-three-d-evidence"
    stored = store.put_bytes(key, body, GLB_MEDIA_TYPE)
    assert stored.size_bytes == len(body)
    assert store.get_bytes(key, max_bytes=1024) == body
    verified = store.verified_local_path(
        key, checksum=stored.sha256, size_bytes=stored.size_bytes
    )
    assert verified.read_bytes() == body
    assert verified.stat().st_mode & 0o077 == 0
    current = root
    for part in Path(key).parent.parts:
        current = current / part
        assert current.stat().st_mode & 0o077 == 0

    with pytest.raises(ThreeDStorageError):
        store.get_bytes("../escape.glb", max_bytes=1024)
    unsafe = root / "unsafe"
    unsafe.symlink_to(tmp_path)
    with pytest.raises(ThreeDStorageError):
        store.get_bytes("unsafe/escape.glb", max_bytes=1024)
    with pytest.raises(ThreeDStorageError):
        store.verified_local_path(
            key, checksum="0" * 64, size_bytes=stored.size_bytes
        )
    store.delete(key)
    with pytest.raises(ThreeDStorageError):
        store.get_bytes(key, max_bytes=1024)


def test_local_artifact_token_is_scoped_short_lived_and_tamper_evident() -> None:
    project_id, job_id, artifact_id = _ids()
    secret = "three-d-test-signing-secret-0123456789abcdef"
    token = issue_local_artifact_token(
        project_id=project_id,
        job_id=job_id,
        artifact_id=artifact_id,
        inline=True,
        secret=secret,
        ttl_seconds=900,
        now_epoch=1_000_000,
    )
    grant = verify_local_artifact_token(
        token, secret=secret, now_epoch=1_000_100
    )
    assert grant.project_id == project_id
    assert grant.job_id == job_id
    assert grant.artifact_id == artifact_id
    assert grant.inline is True
    assert grant.expires_at_epoch == 1_000_900
    assert local_artifact_url("https://api.vip-e.net", token).startswith(
        "https://api.vip-e.net/api/v1/projects/3d/artifacts/local?token="
    )
    with pytest.raises(ThreeDStorageError):
        verify_local_artifact_token(token + "0", secret=secret, now_epoch=1_000_100)
    with pytest.raises(ThreeDStorageError):
        verify_local_artifact_token(token, secret=secret, now_epoch=1_000_901)
    with pytest.raises(ThreeDStorageError):
        local_artifact_url("http://api.vip-e.net", token)


@pytest.mark.asyncio
async def test_local_artifact_download_requires_valid_grant_and_verifies_file(
    monkeypatch, tmp_path: Path
) -> None:
    project_id, job_id, artifact_id = _ids()
    artifact_path = tmp_path / "final.glb"
    body = b"glTF-verified-local-artifact"
    artifact_path.write_bytes(body)
    checksum = __import__("hashlib").sha256(body).hexdigest()
    job = SimpleNamespace(
        id=job_id,
        project_id=project_id,
        provider="triposr",
        status="completed",
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        job_id=job_id,
        project_id=project_id,
        status="ready",
        media_type=GLB_MEDIA_TYPE,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        object_key="3d/org/project/job/final.glb",
        checksum=checksum,
        size_bytes=len(body),
        filename="final.glb",
    )

    class FakeSession:
        def __init__(self) -> None:
            self.rows = [job, artifact]

        async def scalar(self, _statement):
            return self.rows.pop(0)

    class FakeStore:
        is_local = True

        def verified_local_path(self, key: str, *, checksum: str, size_bytes: int) -> Path:
            assert key == artifact.object_key
            assert checksum == artifact.checksum
            assert size_bytes == artifact.size_bytes
            return artifact_path

    monkeypatch.setattr(three_d_jobs, "ThreeDObjectStore", FakeStore)
    token = issue_local_artifact_token(
        project_id=project_id,
        job_id=job_id,
        artifact_id=artifact_id,
        inline=False,
        secret=settings.SECRET_KEY,
        ttl_seconds=900,
    )
    response = await three_d_jobs.download_local_three_d_artifact(
        token=token, session=FakeSession()  # type: ignore[arg-type]
    )
    assert Path(response.path) == artifact_path
    assert response.media_type == GLB_MEDIA_TYPE
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-aionex-checksum-sha256"] == checksum
    assert response.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize(
    "relative_path",
    [
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ],
)
def test_production_compose_wires_private_three_d_volume(relative_path: str) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / relative_path).read_text(encoding="utf-8")
    assert "  three_d_asset_data:\n" in source
    assert "THREE_D_STORAGE_TYPE: local" in source
    assert "three_d_asset_data:/var/lib/aionex/three-d-assets:rw" in source
    assert "three_d_asset_data:/var/lib/aionex/three-d-assets:ro" in source
    assert "${AIOS_ENV_FILE:-.env}" not in source
