"""Real temporary-filesystem coverage for the D6 preparation lifetime.

These tests call the actual bundle helper. Faults only replace filesystem seams;
they do not replace the outcome, cleanup, publication, or backup implementation.
Root owns execution in the isolated verification environment.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import tarfile
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services import security_remediation_files as files
from app.services.three_d_asset_backup import ThreeDAssetSnapshotExecutor


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _private_file(path: Path, content: bytes) -> Path:
    _private_directory(path.parent)
    path.write_bytes(content)
    path.chmod(0o600)
    return path


@pytest.fixture
def build(tmp_path: Path) -> files.RemediationBuildInput:
    allowed = _private_directory(tmp_path / "source-root")
    source = _private_directory(allowed / "snapshot")
    _private_file(source / "payload.txt", b"abcdefgh")
    work = _private_directory(tmp_path / "work")
    return files.RemediationBuildInput(
        remediation_id=str(uuid4()),
        activity_id=str(uuid4()),
        source=source,
        allowed_roots=(allowed,),
        work_root=work,
        plan_json=b'{"schema_version":1,"instructions":["bounded copy"]}\n',
    )


def _prepare(build: files.RemediationBuildInput, **limits):
    return files.prepare_remediation_bundle(build, threading.Event(), **limits)


def _final(build: files.RemediationBuildInput) -> Path:
    return build.work_root / build.remediation_id


def _stage(build: files.RemediationBuildInput) -> Path:
    return build.work_root / ".tmp" / build.activity_id


def _assert_no_stage(build: files.RemediationBuildInput) -> None:
    assert not _stage(build).exists()
    temporary = build.work_root / ".tmp"
    if temporary.exists():
        assert list(temporary.iterdir()) == []


def _assert_unresolved(outcome: files.RemediationIOOutcome) -> None:
    assert outcome.evidence is None
    assert outcome.unresolved_reason
    assert outcome.error_type


def _fd_path(descriptor: int) -> str:
    # This is the test process's own temporary-file descriptor, never a service PID.
    return os.readlink(f"/proc/self/fd/{descriptor}")


def test_atomic_bundle_publishes_source_and_plan_together(build, monkeypatch):
    _private_file(build.source / "nested" / "second.bin", b"second")
    original = files._publish_noreplace
    observed = []

    def publish(source_fd, source_name, destination_fd, destination_name):
        assert source_name == build.activity_id
        assert destination_name == build.remediation_id
        assert not _final(build).exists()
        assert (_stage(build) / "source" / "payload.txt").read_bytes() == b"abcdefgh"
        assert (_stage(build) / "remediation-plan.json").read_bytes() == build.plan_json
        original(source_fd, source_name, destination_fd, destination_name)
        observed.append(
            (
                (_final(build) / "source" / "nested" / "second.bin").read_bytes(),
                (_final(build) / "remediation-plan.json").read_bytes(),
            )
        )

    monkeypatch.setattr(files, "_publish_noreplace", publish)
    result = _prepare(build)

    assert observed == [(b"second", build.plan_json)]
    assert result.error_type is None
    assert result.unresolved_reason is None
    assert result.evidence["files"] == 2
    assert result.evidence["bytes"] == 14
    assert len(result.evidence["manifest_digest"]) == 64
    assert result.evidence["plan_digest"] == hashlib.sha256(build.plan_json).hexdigest()
    _assert_no_stage(build)
    for path in [_final(build), *_final(build).rglob("*")]:
        metadata = path.lstat()
        assert not stat.S_ISLNK(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == (0o700 if path.is_dir() else 0o600)
        if path.is_file():
            assert metadata.st_nlink == 1


def test_prepared_bundle_round_trips_through_actual_asset_backup(build, tmp_path):
    assert _prepare(build).evidence is not None
    backup_dir = _private_directory(tmp_path / "backups")
    database = _private_file(
        backup_dir / f"backup-{'a' * 24}-{'b' * 32}.dump",
        b"PGDMPsynthetic-database",
    )
    config = Settings(
        SECRET_KEY="d6-filesystem-test-key-with-at-least-32-characters",
        DATABASE_URL="postgresql+asyncpg://test:test@database:5432/test",
        BACKUP_DIR=str(backup_dir),
        BACKUP_SECURITY_REMEDIATIONS_ENABLED=True,
        SECURITY_REMEDIATION_ROOT=str(build.work_root),
    )
    executor = ThreeDAssetSnapshotExecutor(config)

    snapshot = executor.create_snapshot(str(database))
    assert snapshot is not None
    checked = executor.validate_snapshot(
        str(database),
        expected_checksum=snapshot.checksum,
        expected_size_bytes=snapshot.size_bytes,
        expected_file_count=snapshot.file_count,
        expected_payload_bytes=snapshot.payload_bytes,
    )

    assert checked.roots == snapshot.roots
    assert snapshot.roots["security_remediation_data"]["file_count"] == 2
    with tarfile.open(snapshot.location, mode="r:") as archive:
        member = archive.extractfile("manifest.json")
        assert member is not None
        manifest = json.loads(member.read())
        paths = {item["path"] for item in manifest["files"]}
        prefix = f"security_remediation_data/{build.remediation_id}"
        assert paths == {
            f"{prefix}/source/payload.txt",
            f"{prefix}/remediation-plan.json",
        }
    _assert_no_stage(build)


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_existing_final_bundle_is_never_adopted_or_overwritten(build, tmp_path, kind):
    foreign = _private_directory(tmp_path / "foreign")
    sentinel = _private_file(foreign / "sentinel", b"foreign-preserved")
    if kind == "directory":
        foreign.rename(_final(build))
        sentinel = _final(build) / "sentinel"
    else:
        _final(build).symlink_to(foreign, target_is_directory=True)
    before = sentinel.stat()

    result = _prepare(build)

    _assert_unresolved(result)
    assert sentinel.read_bytes() == b"foreign-preserved"
    assert sentinel.stat().st_ino == before.st_ino
    assert not (sentinel.parent / "source").exists()
    assert not (build.work_root / ".tmp").exists()


@pytest.mark.parametrize("kind", ["missing", "public", "symlink_ancestor"])
def test_work_root_validation_does_not_create_repair_or_follow(tmp_path, kind):
    root = tmp_path / "work"
    if kind == "missing":
        with pytest.raises(OSError):
            files.validate_work_root(root)
        assert not root.exists()
    elif kind == "public":
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        with pytest.raises(files.RemediationFilesystemUncertain):
            files.validate_work_root(root)
        assert stat.S_IMODE(root.stat().st_mode) == 0o755
    else:
        real = _private_directory(tmp_path / "real" / "work")
        link = tmp_path / "alias"
        link.symlink_to(real.parent, target_is_directory=True)
        with pytest.raises(OSError):
            files.validate_work_root(link / "work")
        assert list(real.iterdir()) == []


def test_work_root_validation_only_observes_existing_private_directory(build):
    before = build.work_root.stat()
    files.validate_work_root(build.work_root)
    after = build.work_root.stat()
    assert (before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns
    )
    assert list(build.work_root.iterdir()) == []


def test_outside_source_is_rejected_before_payload_creation(build, tmp_path):
    outside = _private_directory(tmp_path / "outside")
    _private_file(outside / "private", b"outside")
    result = _prepare(replace(build, source=outside))
    assert result.evidence is None
    assert result.error_type == "ValueError"
    assert not _final(build).exists()
    assert list(build.work_root.iterdir()) == []
    assert (outside / "private").read_bytes() == b"outside"


def test_symlink_source_ancestor_is_not_followed(build, tmp_path):
    real = _private_directory(tmp_path / "outside" / "snapshot")
    _private_file(real / "private", b"outside")
    alias = build.allowed_roots[0] / "alias"
    alias.symlink_to(real.parent, target_is_directory=True)

    result = _prepare(replace(build, source=alias / "snapshot"))

    _assert_unresolved(result)
    assert not _final(build).exists()
    assert (real / "private").read_bytes() == b"outside"


def test_symlink_source_entries_do_not_escape_or_appear_in_bundle(build, tmp_path):
    outside = _private_directory(tmp_path / "outside")
    _private_file(outside / "private", b"do-not-copy")
    (build.source / "linked-file").symlink_to(outside / "private")
    (build.source / "linked-dir").symlink_to(outside, target_is_directory=True)

    result = _prepare(build)

    assert result.evidence is not None
    assert result.evidence["files"] == 1
    assert set(p.name for p in (_final(build) / "source").iterdir()) == {"payload.txt"}
    assert (outside / "private").read_bytes() == b"do-not-copy"


def test_hardlinked_source_cannot_leak_outside_content(build, tmp_path):
    outside = _private_file(tmp_path / "outside-private", b"outside-hardlink-secret")
    os.link(outside, build.source / "hardlink")
    assert outside.stat().st_nlink == 2

    result = _prepare(build)

    _assert_unresolved(result)
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert outside.read_bytes() == b"outside-hardlink-secret"
    assert outside.stat().st_nlink == 2


@pytest.mark.parametrize("relationship", ["same", "work_inside_source", "source_inside_work"])
def test_source_and_work_root_overlap_is_rejected(build, relationship):
    if relationship == "same":
        candidate = replace(build, work_root=build.source)
    elif relationship == "work_inside_source":
        candidate = replace(
            build, work_root=_private_directory(build.source / "destination")
        )
    else:
        source = _private_directory(build.work_root / "input")
        _private_file(source / "data", b"original")
        candidate = replace(build, source=source, allowed_roots=(build.work_root,))

    result = _prepare(candidate, max_entries=20, max_bytes=100)

    assert result.evidence is None
    assert not _final(candidate).exists()
    assert not (candidate.work_root / ".tmp").exists()


@pytest.mark.parametrize("target", ["source", "source_ancestor", "work_root", "temporary", "stage"])
def test_pinned_directory_substitution_preserves_foreign_tree(
    build, tmp_path, monkeypatch, target
):
    original = files._copy_regular_file
    replaced = False
    sentinels = []

    def copy_and_substitute(*args, **kwargs):
        nonlocal replaced
        original(*args, **kwargs)
        if replaced:
            return
        replaced = True
        path = {
            "source": build.source,
            "source_ancestor": build.allowed_roots[0],
            "work_root": build.work_root,
            "temporary": build.work_root / ".tmp",
            "stage": _stage(build),
        }[target]
        path.rename(tmp_path / f"held-original-{target}")
        _private_directory(path)
        sentinels.append(_private_file(path / "foreign-sentinel", b"untouched"))

    monkeypatch.setattr(files, "_copy_regular_file", copy_and_substitute)
    result = _prepare(build)

    assert replaced
    _assert_unresolved(result)
    assert not _final(build).exists()
    assert [p.read_bytes() for p in sentinels] == [b"untouched"]
    assert (sentinels[0].parent / "foreign-sentinel").is_file()


@pytest.mark.parametrize("target", ["source_file", "destination_file", "destination_directory"])
def test_nested_entry_substitution_after_copy_is_detected(build, tmp_path, monkeypatch, target):
    _private_file(build.source / "nested" / "second", b"nested")
    original = files._copy_regular_file
    replaced = False
    foreign = None

    def copy_and_substitute(source_fd, destination_fd, name, relative, state, stop):
        nonlocal replaced, foreign
        original(source_fd, destination_fd, name, relative, state, stop)
        if replaced or name != "second":
            return
        replaced = True
        if target == "source_file":
            path = build.source / "nested" / name
        elif target == "destination_file":
            path = _stage(build) / "source" / "nested" / name
        else:
            path = _stage(build) / "source" / "nested"
        path.rename(tmp_path / "held-original")
        if target == "destination_directory":
            _private_directory(path)
            foreign = _private_file(path / "sentinel", b"foreign")
        else:
            foreign = _private_file(path, b"foreign")

    monkeypatch.setattr(files, "_copy_regular_file", copy_and_substitute)
    result = _prepare(build)

    assert replaced
    _assert_unresolved(result)
    assert not _final(build).exists()
    assert foreign is not None
    assert foreign.read_bytes() == b"foreign"


@pytest.mark.parametrize("target", ["source", "destination"])
def test_same_inode_same_size_content_mutation_before_publication_is_detected(
    build, monkeypatch, target
):
    original = files._copy_regular_file
    changed = False

    def copy_and_mutate(*args, **kwargs):
        nonlocal changed
        original(*args, **kwargs)
        if changed:
            return
        changed = True
        path = (
            build.source / "payload.txt"
            if target == "source"
            else _stage(build) / "source" / "payload.txt"
        )
        before = path.stat()
        path.write_bytes(b"XXXXXXXX")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        assert path.stat().st_ino == before.st_ino
        assert path.stat().st_size == before.st_size

    monkeypatch.setattr(files, "_copy_regular_file", copy_and_mutate)
    result = _prepare(build)

    assert changed
    _assert_unresolved(result)
    assert not _final(build).exists()


def test_publication_collision_created_after_preflight_preserves_foreign(build, monkeypatch):
    original = files._publish_noreplace

    def collide(source_fd, source_name, destination_fd, destination_name):
        _private_file(_final(build) / "sentinel", b"foreign")
        original(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(files, "_publish_noreplace", collide)
    result = _prepare(build)

    _assert_unresolved(result)
    assert (_final(build) / "sentinel").read_bytes() == b"foreign"
    assert not (_final(build) / "source").exists()
    _assert_no_stage(build)


def test_publication_effect_then_error_retains_complete_bundle_and_uncertainty(build, monkeypatch):
    original = files._publish_noreplace

    def publish_then_error(*args):
        original(*args)
        raise OSError(errno.EIO, "synthetic post-publication failure")

    monkeypatch.setattr(files, "_publish_noreplace", publish_then_error)
    result = _prepare(build)

    _assert_unresolved(result)
    assert (_final(build) / "source" / "payload.txt").read_bytes() == b"abcdefgh"
    assert (_final(build) / "remediation-plan.json").read_bytes() == build.plan_json


def test_stage_root_replacement_at_publication_is_not_accepted(build, tmp_path, monkeypatch):
    original = files._publish_noreplace

    def replace_then_publish(*args):
        _stage(build).rename(tmp_path / "held-owned-stage")
        _private_file(_stage(build) / "sentinel", b"foreign")
        original(*args)

    monkeypatch.setattr(files, "_publish_noreplace", replace_then_publish)
    result = _prepare(build)

    _assert_unresolved(result)
    assert (_final(build) / "sentinel").read_bytes() == b"foreign"
    assert (tmp_path / "held-owned-stage" / "source" / "payload.txt").read_bytes() == b"abcdefgh"


def test_leaf_mutation_at_publication_does_not_return_stale_success_manifest(build, monkeypatch):
    original = files._publish_noreplace

    def mutate_then_publish(*args):
        path = _stage(build) / "source" / "payload.txt"
        before = path.stat()
        path.write_bytes(b"XXXXXXXX")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        original(*args)

    monkeypatch.setattr(files, "_publish_noreplace", mutate_then_publish)
    result = _prepare(build)

    _assert_unresolved(result)
    assert (_final(build) / "source" / "payload.txt").read_bytes() == b"XXXXXXXX"


@pytest.mark.parametrize("limit", ["files", "bytes", "entries"])
def test_ordinary_copy_limit_cleans_all_owned_stage_before_clean_failure(build, limit):
    limits = {"max_files": 1, "max_bytes": 8, "max_entries": 1}
    if limit == "files":
        _private_file(build.source / "second", b"x")
        limits = {"max_files": 1}
    elif limit == "bytes":
        limits = {"max_bytes": 7}
    else:
        _private_directory(build.source / ".git")
        limits = {"max_entries": 1}

    result = _prepare(build, **limits)

    assert result.evidence is None
    assert result.error_type == "RemediationSourceLimit"
    assert result.unresolved_reason is None
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert (build.source / "payload.txt").read_bytes() == b"abcdefgh"


def test_actual_byte_budget_bounds_source_growth_after_open(build, monkeypatch):
    original = os.read
    source = build.source / "payload.txt"
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    grown = False
    bytes_read = 0

    def grow_after_read(descriptor, amount):
        nonlocal grown, bytes_read
        metadata = os.fstat(descriptor)
        is_source = (metadata.st_dev, metadata.st_ino) == source_identity
        chunk = original(descriptor, amount)
        if is_source:
            bytes_read += len(chunk)
            if chunk and not grown:
                grown = True
                with source.open("ab") as output:
                    output.write(b"extra-content")
        return chunk

    monkeypatch.setattr(files, "_CHUNK_BYTES", 4)
    monkeypatch.setattr(os, "read", grow_after_read)
    result = _prepare(build, max_bytes=10)

    assert grown
    assert bytes_read <= 11
    assert result.error_type == "RemediationSourceLimit"
    assert result.evidence is None
    assert not _final(build).exists()
    _assert_no_stage(build)


@pytest.mark.parametrize("phase", ["payload", "plan"])
def test_partial_write_failure_is_uncertain_and_cleanup_is_complete(build, monkeypatch, phase):
    original = files._write_all
    failed = False

    def write_then_fail(descriptor, value):
        nonlocal failed
        match = value == build.plan_json if phase == "plan" else value != build.plan_json
        if match and not failed:
            failed = True
            original(descriptor, value[:3])
            raise OSError(errno.EIO, "synthetic partial write")
        original(descriptor, value)

    monkeypatch.setattr(files, "_write_all", write_then_fail)
    result = _prepare(build)

    assert failed
    _assert_unresolved(result)
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert (build.source / "payload.txt").read_bytes() == b"abcdefgh"


@pytest.mark.parametrize("phase", ["payload", "plan", "stage", "published_root"])
def test_fsync_failure_never_looks_like_prepared_or_removes_published_bundle(
    build, monkeypatch, phase
):
    original = os.fsync
    failed = False

    def sync_or_fail(descriptor):
        nonlocal failed
        path = _fd_path(descriptor)
        match = {
            "payload": path.endswith("/source/payload.txt"),
            "plan": path.endswith("/remediation-plan.json"),
            "stage": path == str(_stage(build)),
            "published_root": path == str(build.work_root) and _final(build).exists(),
        }[phase]
        if match and not failed:
            failed = True
            raise OSError(errno.EIO, "synthetic fsync failure")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", sync_or_fail)
    result = _prepare(build)

    assert failed
    _assert_unresolved(result)
    if phase == "published_root":
        assert (_final(build) / "source" / "payload.txt").read_bytes() == b"abcdefgh"
        assert (_final(build) / "remediation-plan.json").read_bytes() == build.plan_json
    else:
        assert not _final(build).exists()
        _assert_no_stage(build)


@pytest.mark.parametrize("kind", ["stage_root", "nested_file", "nested_directory"])
def test_cleanup_refuses_foreign_substitution_and_retains_uncertainty(
    build, tmp_path, monkeypatch, kind
):
    original_copy = files._copy_regular_file
    original_cleanup = files._cleanup_owned_stage
    _private_file(build.source / "nested" / "child", b"child")
    replaced = False
    foreign = None

    def copy_then_fail(*args, **kwargs):
        original_copy(*args, **kwargs)
        raise files.RemediationSourceLimit("synthetic ordinary overlimit")

    def replace_then_cleanup(parent_fd, stage_name, stage_fd, identities):
        nonlocal replaced, foreign
        replaced = True
        if kind == "stage_root":
            path = _stage(build)
        elif kind == "nested_directory":
            path = _stage(build) / "source" / "nested"
        else:
            path = _stage(build) / "source" / "nested" / "child"
        path.rename(tmp_path / "held-owned-entry")
        if kind == "nested_file":
            foreign = _private_file(path, b"foreign")
        else:
            _private_directory(path)
            foreign = _private_file(path / "sentinel", b"foreign")
        original_cleanup(parent_fd, stage_name, stage_fd, identities)

    monkeypatch.setattr(files, "_copy_regular_file", copy_then_fail)
    monkeypatch.setattr(files, "_cleanup_owned_stage", replace_then_cleanup)
    result = _prepare(build)

    assert replaced
    _assert_unresolved(result)
    assert foreign is not None
    assert foreign.read_bytes() == b"foreign"
    assert not _final(build).exists()


def test_cleanup_io_failure_does_not_upgrade_ordinary_limit_to_clean_failure(build, monkeypatch):
    original = os.unlink
    failed = False

    def refuse_owned_unlink(name, *args, **kwargs):
        nonlocal failed
        if name == "payload.txt" and kwargs.get("dir_fd") is not None and not failed:
            failed = True
            raise OSError(errno.EIO, "synthetic cleanup failure")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refuse_owned_unlink)
    result = _prepare(build, max_bytes=7)

    assert failed
    _assert_unresolved(result)
    assert _stage(build).exists()
    assert not _final(build).exists()


@pytest.mark.parametrize("phase", ["before", "during", "after_publication"])
def test_cooperative_stop_remains_unresolved_until_owner_reconciliation(build, monkeypatch, phase):
    stop = threading.Event()
    original_copy = files._copy_regular_file
    original_publish = files._publish_noreplace

    def copy_then_stop(*args, **kwargs):
        original_copy(*args, **kwargs)
        stop.set()

    def publish_then_stop(*args):
        original_publish(*args)
        stop.set()

    if phase == "before":
        stop.set()
    elif phase == "during":
        monkeypatch.setattr(files, "_copy_regular_file", copy_then_stop)
    else:
        monkeypatch.setattr(files, "_publish_noreplace", publish_then_stop)

    result = files.prepare_remediation_bundle(build, stop)

    _assert_unresolved(result)
    if phase == "after_publication":
        assert (_final(build) / "source" / "payload.txt").read_bytes() == b"abcdefgh"
    else:
        assert not _final(build).exists()
        _assert_no_stage(build)


def test_close_effect_then_error_attempts_other_fds_without_closing_reused_fd(
    build, tmp_path, monkeypatch
):
    original_open = os.open
    original_close = os.close
    live = set()
    failed = False
    reused = None
    sentinel = _private_file(tmp_path / "fd-sentinel", b"still-open")

    def track_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        live.add(descriptor)
        return descriptor

    def close_and_fail_once(descriptor):
        nonlocal failed, reused
        match = (
            not failed
            and stat.S_ISREG(os.fstat(descriptor).st_mode)
            and _fd_path(descriptor).endswith("/source/payload.txt")
            and "/.tmp/" in _fd_path(descriptor)
        )
        original_close(descriptor)
        live.discard(descriptor)
        if match:
            failed = True
            reused = original_open(sentinel, os.O_RDONLY | os.O_CLOEXEC)
            assert reused == descriptor
            raise OSError(errno.EIO, "synthetic completed close with uncertain result")

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", close_and_fail_once)
    try:
        result = _prepare(build)
        assert failed
        _assert_unresolved(result)
        assert live == set()
        assert reused is not None
        assert os.read(reused, 10) == b"still-open"
        assert not _final(build).exists()
        _assert_no_stage(build)
    finally:
        if reused is not None:
            original_close(reused)
        for descriptor in list(live):
            original_close(descriptor)
            live.discard(descriptor)


@pytest.mark.parametrize("phase", ["after_copy", "at_publication"])
def test_published_directories_must_keep_private_permissions(build, monkeypatch, phase):
    _private_file(build.source / "nested" / "child", b"nested")
    original_copy = files._copy_regular_file
    original_publish = files._publish_noreplace
    changed = False

    def copy_and_chmod(*args, **kwargs):
        nonlocal changed
        original_copy(*args, **kwargs)
        if not changed:
            changed = True
            (_stage(build) / "source").chmod(0o755)

    def chmod_and_publish(*args):
        nonlocal changed
        changed = True
        (_stage(build) / "source" / "nested").chmod(0o755)
        original_publish(*args)

    if phase == "after_copy":
        monkeypatch.setattr(files, "_copy_regular_file", copy_and_chmod)
    else:
        monkeypatch.setattr(files, "_publish_noreplace", chmod_and_publish)

    result = _prepare(build)

    assert changed
    _assert_unresolved(result)
    if phase == "at_publication":
        assert (_final(build) / "source" / "payload.txt").read_bytes() == b"abcdefgh"
    else:
        assert not _final(build).exists()


def test_source_file_replaced_between_stat_and_open_is_not_followed(
    build, tmp_path, monkeypatch
):
    original = os.open
    outside = _private_file(tmp_path / "outside-content", b"do-not-read")
    replaced = False

    def substitute_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if (
            not replaced
            and path == "payload.txt"
            and flags & os.O_NONBLOCK
            and kwargs.get("dir_fd") is not None
        ):
            replaced = True
            (build.source / "payload.txt").rename(tmp_path / "held-source-file")
            (build.source / "payload.txt").symlink_to(outside)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", substitute_before_open)
    result = _prepare(build)

    assert replaced
    _assert_unresolved(result)
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert outside.read_bytes() == b"do-not-read"


def test_source_gaining_hardlink_after_copy_is_not_accepted(build, tmp_path, monkeypatch):
    original = files._copy_regular_file
    added = False

    def copy_and_link(*args, **kwargs):
        nonlocal added
        original(*args, **kwargs)
        if not added:
            added = True
            os.link(build.source / "payload.txt", tmp_path / "external-alias")

    monkeypatch.setattr(files, "_copy_regular_file", copy_and_link)
    result = _prepare(build)

    assert added
    _assert_unresolved(result)
    assert not _final(build).exists()
    assert (tmp_path / "external-alias").read_bytes() == b"abcdefgh"


def test_directory_depth_budget_cleans_owned_copy_without_publishing(build):
    cursor = build.source
    for _ in range(130):
        cursor = _private_directory(cursor / "d")
    _private_file(cursor / "deep", b"bounded")

    result = _prepare(build)

    assert result.error_type == "RemediationSourceLimit"
    assert result.evidence is None
    assert result.unresolved_reason is None
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert (cursor / "deep").read_bytes() == b"bounded"


def test_publication_unavailable_is_fail_closed_with_complete_owned_cleanup(build, monkeypatch):
    def unavailable(*args):
        raise OSError(errno.ENOSYS, "synthetic unsupported publication ABI")

    monkeypatch.setattr(files, "_publish_noreplace", unavailable)
    result = _prepare(build)

    _assert_unresolved(result)
    assert not _final(build).exists()
    _assert_no_stage(build)


class _GuardedHugeDirectoryIterator:
    """Represent a huge directory without allocating its entries in this test."""

    def __init__(self, *, first_name=None, guard_after=8):
        self.first_name = first_name
        self.guard_after = guard_after
        self.consumed = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def __iter__(self):
        return self

    def __next__(self):
        self.consumed += 1
        if self.consumed > self.guard_after:
            raise AssertionError("enumeration continued beyond the bounded witness")
        name = (
            self.first_name
            if self.consumed == 1 and self.first_name is not None
            else f"phantom-{self.consumed}"
        )
        return SimpleNamespace(name=name)

    def close(self):
        self.closed = True


def test_huge_source_enumeration_stops_at_budget_plus_one_before_stat_or_copy(
    build, monkeypatch
):
    original_scandir = os.scandir
    original_listdir = os.listdir
    source_metadata = build.source.stat()
    source_identity = (source_metadata.st_dev, source_metadata.st_ino)
    enumeration = _GuardedHugeDirectoryIterator(guard_after=8)
    eager_calls = []

    def bounded_source_scandir(path):
        if isinstance(path, int):
            metadata = os.fstat(path)
            if (metadata.st_dev, metadata.st_ino) == source_identity:
                return enumeration
        return original_scandir(path)

    def reject_eager_descriptor_listdir(path):
        if isinstance(path, int):
            eager_calls.append(path)
            raise AssertionError("descriptor enumeration must enforce its budget incrementally")
        return original_listdir(path)

    monkeypatch.setattr(os, "scandir", bounded_source_scandir)
    monkeypatch.setattr(os, "listdir", reject_eager_descriptor_listdir)
    result = _prepare(build, max_entries=3)

    assert enumeration.consumed == 4
    assert enumeration.closed
    assert eager_calls == []
    assert result.error_type == "RemediationSourceLimit"
    assert result.unresolved_reason is None
    assert result.evidence is None
    assert not _final(build).exists()
    _assert_no_stage(build)
    assert (build.source / "payload.txt").read_bytes() == b"abcdefgh"


@pytest.mark.parametrize("phase", ["inventory", "cleanup"])
def test_known_tree_enumeration_stops_at_first_unknown_and_preserves_it(
    build, monkeypatch, phase
):
    original_scandir = os.scandir
    original_copy = files._copy_regular_file
    original_cleanup = files._cleanup_owned_stage
    injected = False
    stage_identity = None
    enumerations = []

    def inject_foreign():
        nonlocal injected, stage_identity
        if not injected:
            injected = True
            _private_file(_stage(build) / "foreign-sentinel", b"must-survive")
            metadata = _stage(build).stat()
            stage_identity = (metadata.st_dev, metadata.st_ino)

    def copy_then_inject(*args, **kwargs):
        original_copy(*args, **kwargs)
        inject_foreign()

    def inject_then_cleanup(*args, **kwargs):
        inject_foreign()
        return original_cleanup(*args, **kwargs)

    def unknown_first_scandir(path):
        if stage_identity is not None and isinstance(path, int):
            metadata = os.fstat(path)
            if (metadata.st_dev, metadata.st_ino) == stage_identity:
                iterator = _GuardedHugeDirectoryIterator(
                    first_name="foreign-sentinel", guard_after=2
                )
                enumerations.append(iterator)
                return iterator
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", unknown_first_scandir)
    if phase == "inventory":
        monkeypatch.setattr(files, "_copy_regular_file", copy_then_inject)
        result = _prepare(build)
    else:
        monkeypatch.setattr(files, "_cleanup_owned_stage", inject_then_cleanup)
        result = _prepare(build, max_bytes=7)

    assert injected
    assert enumerations
    assert all(item.consumed == 1 and item.closed for item in enumerations)
    _assert_unresolved(result)
    assert (_stage(build) / "foreign-sentinel").read_bytes() == b"must-survive"
    assert not _final(build).exists()
