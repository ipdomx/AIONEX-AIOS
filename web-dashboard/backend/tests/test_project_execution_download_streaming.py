"""No-production-db test: actual governed 3D ZIP can stream with bounded RAM."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.project_executions import (
    _download_archive_slots,
    download_project_execution,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class DummyReadOnlySession:
    def __init__(self, path: Path | None):
        self._path = path

    async def scalar(self, query):
        compiled = str(query).lower()
        assert "project_executions" in compiled
        assert "organization_id" in compiled
        assert "project_id" in compiled
        assert "completed" in compiled or "status" in compiled
        if self._path is None:
            return None
        return SimpleNamespace(evidence_path=str(self._path))


@pytest.mark.anyio
async def test_completed_governed_3d_delivery_streams_valid_sha_and_chunk_boundaries(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "governance" / "cycle"
    root = evidence / "delivery-package"
    (root / "source").mkdir(parents=True)
    (root / "3d-web" / "dist").mkdir(parents=True)
    (root / "source" / "server.py").write_text("reviewed core API")
    (root / "3d-web" / "dist" / "index.html").write_text("verified 3D scene")
    before = _download_archive_slots._value
    result = await download_project_execution(
        "synthetic-project",
        "synthetic-execution",
        actor=SimpleNamespace(organization_id="synthetic-tenant"),
        session=DummyReadOnlySession(evidence),
    )
    assert result.status_code == 200
    assert result.headers["Content-Type"] == "application/zip"
    assert result.headers["Cache-Control"] == "no-store"
    assert int(result.headers["Content-Length"]) > 0

    chunks = [x async for x in result.body_iterator]
    assert chunks and all(0 < len(c) <= 1024 * 1024 for c in chunks)
    payload = b"".join(chunks)
    assert len(payload) == int(result.headers["Content-Length"])
    assert hashlib.sha256(payload).hexdigest() == result.headers["X-AIONEX-SHA256"]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "source/server.py",
            "3d-web/dist/index.html",
        }
    assert _download_archive_slots._value == before


@pytest.mark.anyio
async def test_unavailable_or_nonexistent_customer_delivery_does_not_allocate_zip(
    tmp_path: Path,
) -> None:
    from fastapi import HTTPException

    before = _download_archive_slots._value
    with pytest.raises(HTTPException) as exc:
        await download_project_execution(
            "synthetic-project", "not-in-tenant",
            actor=SimpleNamespace(organization_id="other-tenant"),
            session=DummyReadOnlySession(None),
        )
    assert exc.value.status_code == 404
    assert _download_archive_slots._value == before


@pytest.mark.anyio
async def test_cancelling_download_closes_temporary_archive_and_releases_slot(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "cycle"
    source = evidence / "delivery-package" / "source"
    source.mkdir(parents=True)
    (source / "server.py").write_text("reviewed")
    initial = _download_archive_slots._value
    result = await download_project_execution(
        "synthetic-project", "cancelled-client",
        actor=SimpleNamespace(organization_id="synthetic-tenant"),
        session=DummyReadOnlySession(evidence),
    )
    first = await anext(result.body_iterator)
    assert first.startswith(b"PK")
    await result.body_iterator.aclose()
    assert _download_archive_slots._value == initial
