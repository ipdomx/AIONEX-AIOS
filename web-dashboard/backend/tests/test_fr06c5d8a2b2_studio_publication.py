"""Real isolated filesystem tests; no production mounts, database or providers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import os
from pathlib import Path
import stat
import threading

import pytest

from app.services import studio_artifact_publication as publication


def arguments(tmp_path: Path, **changes):
    content = b"synthetic complete archive bytes" * 257
    result = dict(
        root=tmp_path / "store", organization_id="org-test", asset_id="asset-test",
        revision_number=1, filename="archive.zip", content=content,
        checksum=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
        maximum_bytes=1024 * 1024,
    )
    result.update(changes)
    return result


def destination(values):
    return Path(values["root"]) / values["organization_id"] / values["asset_id"] / f"revision-{values['revision_number']}" / values["filename"]


def prepared(tmp_path):
    values = arguments(tmp_path)
    path = destination(values)
    path.parent.mkdir(parents=True, mode=0o700)
    return values, path


def staging_names(path):
    return list(path.parent.glob(".studio-publish-*.partial"))


def test_publishes_verified_complete_single_link_private_file(tmp_path):
    values = arguments(tmp_path)
    path = publication.publish_studio_archive(**values)
    assert path == destination(values)
    assert path.read_bytes() == values["content"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_nlink == 1
    assert not staging_names(path)
    for directory in [path.parent, path.parent.parent, path.parent.parent.parent, Path(values["root"])]:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling", "fifo", "hardlink"])
def test_existing_destination_is_never_replaced_or_removed(tmp_path, kind):
    values, path = prepared(tmp_path)
    original = tmp_path / "original"
    original.write_bytes(b"original must survive")
    if kind == "file":
        path.write_bytes(b"existing archive")
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(original)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "missing")
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        os.link(original, path)
    before = os.lstat(path)
    with pytest.raises(FileExistsError):
        publication.publish_studio_archive(**values)
    after = os.lstat(path)
    assert (before.st_dev, before.st_ino, before.st_mode, before.st_nlink) == (after.st_dev, after.st_ino, after.st_mode, after.st_nlink)
    assert original.read_bytes() == b"original must survive"
    if kind == "file":
        assert path.read_bytes() == b"existing archive"
    assert not staging_names(path)


def test_identical_payload_is_still_a_collision_not_replay_success(tmp_path):
    values = arguments(tmp_path)
    path = publication.publish_studio_archive(**values)
    before = path.stat()
    with pytest.raises(FileExistsError):
        publication.publish_studio_archive(**values)
    assert path.stat().st_ino == before.st_ino
    assert path.read_bytes() == values["content"]
    assert not staging_names(path)


@pytest.mark.parametrize("field", ["organization_id", "asset_id", "filename"])
@pytest.mark.parametrize("value", ["", ".", "..", "../outside", "/absolute", "a/b", "a\\b", "bad\x00name", "bad\nname", "x" * 221])
def test_invalid_component_precedes_filesystem_mutation(tmp_path, field, value):
    values = arguments(tmp_path, **{field: value})
    with pytest.raises(ValueError):
        publication.publish_studio_archive(**values)
    assert not Path(values["root"]).exists()


@pytest.mark.parametrize("value", [0, -1, True, False, 1.0, "1", None, 2_147_483_648])
def test_invalid_revision_precedes_filesystem_mutation(tmp_path, value):
    values = arguments(tmp_path, revision_number=value)
    with pytest.raises(ValueError):
        publication.publish_studio_archive(**values)
    assert not Path(values["root"]).exists()


@pytest.mark.parametrize("changes", [
    {"checksum": "0" * 64}, {"size_bytes": 1}, {"size_bytes": True},
    {"maximum_bytes": 1}, {"maximum_bytes": True}, {"maximum_bytes": 0},
    {"content": b"", "size_bytes": 0}, {"content": bytearray(b"bad")},
])
def test_invalid_payload_precedes_filesystem_mutation(tmp_path, changes):
    values = arguments(tmp_path, **changes)
    with pytest.raises(ValueError):
        publication.publish_studio_archive(**values)
    assert not Path(values["root"]).exists()


def test_competing_writers_publish_exactly_one_whole_archive(tmp_path):
    barrier = threading.Barrier(16)
    def produce(index):
        content = bytes([index]) * 65537
        values = arguments(tmp_path, content=content, checksum=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
        barrier.wait(timeout=10)
        try:
            return index, publication.publish_studio_archive(**values)
        except FileExistsError:
            return index, None
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(produce, range(16)))
    winners = [(index, path) for index, path in results if path is not None]
    assert len(winners) == 1
    index, path = winners[0]
    assert path.read_bytes() == bytes([index]) * 65537
    assert path.stat().st_nlink == 1
    assert not staging_names(path)


def test_link_publishes_only_fsynced_complete_staging_bytes(tmp_path, monkeypatch):
    values, path = prepared(tmp_path)
    real_link, real_sync = os.link, os.fsync
    flushed = set()
    observations = []
    def sync(descriptor):
        real_sync(descriptor)
        flushed.add((os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino))
    def link(source, target, **kwargs):
        assert target == values["filename"] and not path.exists()
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        assert kwargs["follow_symlinks"] is False
        staged = path.parent / source
        assert staged.read_bytes() == values["content"]
        assert (staged.stat().st_dev, staged.stat().st_ino) in flushed
        observations.append(source)
        return real_link(source, target, **kwargs)
    monkeypatch.setattr(publication.os, "fsync", sync)
    monkeypatch.setattr(publication.os, "link", link)
    assert publication.publish_studio_archive(**values) == path
    assert len(observations) == 1


def test_short_writes_are_completed_before_publication(tmp_path, monkeypatch):
    real_write = os.write
    monkeypatch.setattr(publication.os, "write", lambda fd, data: real_write(fd, data[:13]))
    values = arguments(tmp_path)
    path = publication.publish_studio_archive(**values)
    assert path.read_bytes() == values["content"]


@pytest.mark.parametrize("failure", ["no_progress", "write", "checksum", "file_sync", "unsupported_link"])
def test_prepublication_failure_never_publishes_partial_file(tmp_path, monkeypatch, failure):
    values, path = prepared(tmp_path)
    real_write, real_sync = os.write, os.fsync
    if failure == "no_progress":
        monkeypatch.setattr(publication.os, "write", lambda _fd, _data: 0)
    elif failure == "write":
        def broken_write(fd, content):
            real_write(fd, content[:11])
            raise OSError(errno.ENOSPC, "synthetic storage exhaustion")
        monkeypatch.setattr(publication, "_write_bytes", broken_write)
    elif failure == "checksum":
        monkeypatch.setattr(publication, "_write_bytes", lambda fd, content: real_write(fd, b"X" * len(content)))
    elif failure == "file_sync":
        def file_sync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, "synthetic file sync failure")
            return real_sync(fd)
        monkeypatch.setattr(publication.os, "fsync", file_sync)
    else:
        def unsupported(*_args, **_kwargs):
            raise OSError(errno.EOPNOTSUPP, "synthetic unsupported hardlinks")
        monkeypatch.setattr(publication.os, "link", unsupported)
    with pytest.raises((OSError, publication.StudioPublicationUncertain)):
        publication.publish_studio_archive(**values)
    assert not path.exists()
    assert not staging_names(path)


@pytest.mark.parametrize("phase", ["after_link", "cleanup_sync"])
def test_postpublication_sync_failure_retains_archive_and_does_not_report_success(tmp_path, monkeypatch, phase):
    values, path = prepared(tmp_path)
    real_sync = os.fsync
    count = 0
    def sync(fd):
        nonlocal count
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            count += 1
            if count == (1 if phase == "after_link" else 2):
                raise OSError(errno.EIO, "synthetic directory sync failure")
        return real_sync(fd)
    monkeypatch.setattr(publication.os, "fsync", sync)
    with pytest.raises(OSError):
        publication.publish_studio_archive(**values)
    assert path.read_bytes() == values["content"]
    assert not staging_names(path)


@pytest.mark.parametrize("level", ["ancestor", "root", "organization", "asset", "revision"])
def test_symlink_directories_are_not_followed(tmp_path, level):
    values = arguments(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"untouched")
    root = Path(values["root"])
    if level == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        values["root"] = alias / "store"
    elif level == "root":
        root.symlink_to(outside, target_is_directory=True)
    else:
        parts = [values["organization_id"], values["asset_id"], "revision-1"]
        index = ["organization", "asset", "revision"].index(level)
        parent = root.joinpath(*parts[:index])
        parent.mkdir(parents=True)
        (parent / parts[index]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        publication.publish_studio_archive(**values)
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"untouched"


def test_world_writable_target_directory_is_rejected_without_chmod(tmp_path):
    values, path = prepared(tmp_path)
    path.parent.chmod(0o777)
    with pytest.raises(publication.StudioPublicationUncertain):
        publication.publish_studio_archive(**values)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o777
    assert not path.exists() and not staging_names(path)


@pytest.mark.parametrize("moment", ["before_link", "during_link"])
def test_directory_replacement_never_redirects_write_or_cleanup(tmp_path, monkeypatch, moment):
    values, path = prepared(tmp_path)
    moved = path.parent.with_name("original-revision")
    real_write, real_link = publication._write_bytes, os.link
    def swap():
        path.parent.rename(moved)
        path.parent.mkdir(mode=0o700)
        (path.parent / "sentinel").write_bytes(b"replacement directory")
    if moment == "before_link":
        def write(fd, content):
            real_write(fd, content)
            swap()
        monkeypatch.setattr(publication, "_write_bytes", write)
    else:
        def link(*args, **kwargs):
            swap()
            return real_link(*args, **kwargs)
        monkeypatch.setattr(publication.os, "link", link)
    with pytest.raises(publication.StudioPublicationUncertain):
        publication.publish_studio_archive(**values)
    assert not path.exists()
    assert (path.parent / "sentinel").read_bytes() == b"replacement directory"
    assert not list(moved.glob("*.partial"))
    assert (moved / path.name).exists() is (moment == "during_link")
    if moment == "during_link":
        assert (moved / path.name).read_bytes() == values["content"]


def test_replaced_staging_name_is_not_deleted(tmp_path, monkeypatch):
    values, path = prepared(tmp_path)
    real_write = publication._write_bytes
    def write(fd, content):
        real_write(fd, content)
        staged = staging_names(path)[0]
        staged.unlink()
        staged.write_bytes(b"replacement staging must survive")
    monkeypatch.setattr(publication, "_write_bytes", write)
    with pytest.raises(publication.StudioPublicationUncertain):
        publication.publish_studio_archive(**values)
    assert not path.exists()
    assert [entry.read_bytes() for entry in staging_names(path)] == [b"replacement staging must survive"]


def test_staging_cleanup_failure_is_not_success_or_final_deletion(tmp_path, monkeypatch):
    values, path = prepared(tmp_path)
    def deny_unlink(*_args, **_kwargs):
        raise OSError(errno.EIO, "synthetic cleanup failure")
    monkeypatch.setattr(publication.os, "unlink", deny_unlink)
    with pytest.raises(OSError):
        publication.publish_studio_archive(**values)
    assert path.read_bytes() == values["content"]
    assert len(staging_names(path)) == 1
    assert path.stat().st_nlink == 2


def test_old_fixed_partial_name_is_not_used_or_deleted(tmp_path):
    values, path = prepared(tmp_path)
    old_partial = path.with_suffix(path.suffix + ".partial")
    outside = tmp_path / "old-content"
    outside.write_bytes(b"historical file")
    old_partial.symlink_to(outside)
    assert publication.publish_studio_archive(**values) == path
    assert outside.read_bytes() == b"historical file"
    assert old_partial.is_symlink()


def test_all_descriptors_close_after_success_and_collision(tmp_path):
    before = len(list(Path("/proc/self/fd").iterdir()))
    for index in range(8):
        values = arguments(tmp_path, asset_id=f"asset-{index}")
        publication.publish_studio_archive(**values)
        with pytest.raises(FileExistsError):
            publication.publish_studio_archive(**values)
    assert len(list(Path("/proc/self/fd").iterdir())) == before


def test_established_store_api_uses_no_replace_and_keeps_path_return(tmp_path, monkeypatch):
    from app.services import production_studio
    monkeypatch.setattr(production_studio.settings, "STUDIO_ASSET_ROOT", str(tmp_path / "store"))
    spec = production_studio.StudioSpec(department="text", title="Isolated publication", brief="Build an editable synthetic demonstration.")
    archive = production_studio.build_archive(spec, job_id="synthetic-job", revision_number=1)
    values = dict(organization_id="org-test", asset_id="asset-test", revision_number=1, artifact=archive)
    path = production_studio.store_artifact(**values)
    assert isinstance(path, Path)
    assert production_studio.verify_artifact(str(path), archive.checksum, archive.size_bytes) == path
    with pytest.raises(FileExistsError):
        production_studio.store_artifact(**values)
    assert not staging_names(path)
