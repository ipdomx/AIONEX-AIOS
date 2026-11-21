"""Real retained project archive format/size, security and stream integrity."""
from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest

from app.services import project_delivery_archive as arch


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    evidence = tmp_path / "governance" / "cycle"
    package = evidence / "delivery-package"
    (package / "source").mkdir(parents=True)
    (package / "3d-web" / "dist").mkdir(parents=True)
    (package / "3d-web" / "qa").mkdir(parents=True)
    return evidence, package


def test_real_3d_source_archive_over_old_50mib_limit_uses_disk_and_chunks(
    tmp_path: Path,
) -> None:
    evidence, package = _roots(tmp_path)
    (package / "source" / "server.py").write_text("print('reviewed')")
    (package / "3d-web" / "dist" / "index.html").write_text("<title>3D</title>")
    (package / "3d-web" / "qa" / "low-power-360.png").write_bytes(b"real-qa-sample")
    with (package / "3d-web" / "assets.bin").open("wb") as output:
        # Sparse synthetic asset; the source is genuinely 51 MiB without
        # consuming the same amount of physical test disk.
        output.truncate(51 * 1024 * 1024)
    (evidence / "owner-approval.json").write_text('{"approved":true}')

    archive = arch.build_project_delivery_archive(package, evidence)
    try:
        assert archive.length > 0
        assert archive.sha256 and len(archive.sha256) == 64
        assert not isinstance(archive.stream, io.BytesIO)
        digest = hashlib.sha256()
        chunks = []
        while block := archive.stream.read(arch.ARCHIVE_CHUNK_BYTES):
            assert len(block) <= 1024 * 1024
            digest.update(block)
            chunks.append(block)
        assert digest.hexdigest() == archive.sha256
        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as bundle:
            assert set(bundle.namelist()) == {
                "source/server.py",
                "3d-web/dist/index.html",
                "3d-web/qa/low-power-360.png",
                "3d-web/assets.bin",
                "owner-approval.json",
            }
            assert bundle.getinfo("3d-web/assets.bin").file_size == 51 * 1024 * 1024
            assert bundle.read("owner-approval.json") == b'{"approved":true}'
    finally:
        archive.stream.close()
    assert archive.stream.closed


def test_symlinks_and_escaped_paths_never_enter_archive(tmp_path: Path) -> None:
    evidence, package = _roots(tmp_path)
    (package / "source" / "server.py").write_text("ok")
    secret = tmp_path / "secret.txt"
    secret.write_text("not a customer deliverable")
    (package / "source" / "leak.txt").symlink_to(secret)
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="unsafe link"):
        arch.build_project_delivery_archive(package, evidence)
    (package / "source" / "leak.txt").unlink()
    (package / "outside").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="unsafe link"):
        arch.build_project_delivery_archive(package, evidence)


def test_oversized_sparse_package_rejected_before_temp_zip(tmp_path: Path) -> None:
    evidence, package = _roots(tmp_path)
    with (package / "source" / "huge.bin").open("wb") as output:
        output.truncate(arch.MAX_DELIVERY_SOURCE_BYTES + 1)
    with pytest.raises(arch.ProjectDeliveryArchiveError) as exc:
        arch.build_project_delivery_archive(package, evidence)
    assert exc.value.status_code == 413


def test_excessive_file_count_rejected_before_packaging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, package = _roots(tmp_path)
    monkeypatch.setattr(arch, "MAX_DELIVERY_FILES", 2)
    for i in range(3):
        (package / "source" / f"file-{i}.txt").write_text("ok")
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="too many"):
        arch.build_project_delivery_archive(package, evidence)


def test_approval_receipt_is_bounded_and_symlinks_denied(tmp_path: Path) -> None:
    evidence, package = _roots(tmp_path)
    (package / "source" / "server.py").write_text("ok")
    approval = evidence / "owner-approval.json"
    approval.write_bytes(b"X" * (arch.MAX_APPROVAL_RECEIPT_BYTES + 1))
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="approval receipt"):
        arch.build_project_delivery_archive(package, evidence)
    approval.unlink()
    approval.symlink_to(tmp_path / "does-not-exist")
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="unsafe link"):
        arch.build_project_delivery_archive(package, evidence)


def test_nonexistent_or_empty_package_is_not_downloadable(tmp_path: Path) -> None:
    evidence, package = _roots(tmp_path)
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="empty"):
        arch.build_project_delivery_archive(package, evidence)
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="unavailable"):
        arch.build_project_delivery_archive(tmp_path / "missing", evidence)


def test_hardlinked_external_file_cannot_be_exfiltrated(tmp_path: Path) -> None:
    evidence, package = _roots(tmp_path)
    (package / "source" / "server.py").write_text("reviewed")
    external_secret = tmp_path / "outside-secret.txt"
    external_secret.write_text("must not be sent")
    os.link(external_secret, package / "source" / "hardlink.txt")
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="hardlink"):
        arch.build_project_delivery_archive(package, evidence)


def test_generated_files_cannot_spoof_protected_owner_approval_receipt(
    tmp_path: Path,
) -> None:
    evidence, package = _roots(tmp_path)
    (package / "source" / "server.py").write_text("reviewed")
    (package / "owner-approval.json").write_text('{"approved":true}')
    with pytest.raises(arch.ProjectDeliveryArchiveError, match="reserved receipt"):
        arch.build_project_delivery_archive(package, evidence)
