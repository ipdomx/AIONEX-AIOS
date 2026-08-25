from __future__ import annotations
from datetime import UTC, datetime
from types import SimpleNamespace
import pytest
from app.services import academy_course_runtime as runtime


def test_package_path_is_traversal_safe(tmp_path):
    root = tmp_path / "packages"
    root.mkdir()
    file = root / "course.zip"
    file.write_bytes(b"zip")
    assert runtime.resolve_package_path(root, "course.zip") == file
    with pytest.raises(FileNotFoundError):
        runtime.resolve_package_path(root, "../escape.zip")


def test_snapshots_never_return_physical_storage_paths():
    item = SimpleNamespace(
        id="p",
        course_id="c",
        status="approved",
        version=2,
        lesson_count=4,
        request_payload={},
        curriculum={},
        citations=[],
        review={},
        archive_sha256="a" * 64,
        manifest_sha256="b" * 64,
        archive_bytes=100,
        archive_relpath="private/x.zip",
        site_relpath="private/site",
        error_code=None,
        completed_at=datetime.now(UTC),
        reviewed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    snap = runtime.package_snapshot(item)
    assert "archive_relpath" not in snap and "site_relpath" not in snap
    assert snap["download_ready"] is True and snap["site_ready"] is True


def test_progress_status_contracts_are_bounded():
    assert runtime.PACKAGE_STATUSES == frozenset(
        {"queued", "building", "review_pending", "approved", "rejected", "failed"}
    )
    assert runtime.PROGRESS_STATUSES == frozenset(
        {"not_started", "in_progress", "completed"}
    )
    assert runtime.SUPPORTED_LOCALES == ("ar", "en", "fr", "de", "es", "tr")
