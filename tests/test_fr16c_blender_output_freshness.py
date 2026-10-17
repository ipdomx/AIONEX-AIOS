"""Boundary-only regressions: Blender subprocesses are mocked, never executed.

The byte payloads are deliberately synthetic and are not valid GLB/PNG assets.
These tests establish output freshness and file identity, not renderer, scene,
format, provider, network-namespace, GPU, CPU or memory acceptance.
"""

from __future__ import annotations

from collections.abc import Callable
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from aios.three_d_web import blender_candidate as candidate


PAYLOADS = {
    "scene.glb": b"SYNTHETIC BOUNDARY FIXTURE: NOT A VALID GLB\n" * 4,
    "preview.png": b"SYNTHETIC BOUNDARY FIXTURE: NOT A VALID PNG\n" * 4,
}


def _write_outputs(destination: Path) -> None:
    for name, payload in PAYLOADS.items():
        (destination / name).write_bytes(payload)


@pytest.fixture
def mocked_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[Path], None]], list[Path]]:
    monkeypatch.setattr(
        candidate.Blender52CandidateRunner,
        "preflight",
        lambda self: {"version": "5.2.0"},
    )

    def install(action: Callable[[Path], None]) -> list[Path]:
        calls: list[Path] = []

        def run(command: list[str], *, cwd: Path, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            # No command is executed; this callback only creates test fixtures.
            destination = Path(cwd)
            calls.append(destination)
            action(destination)
            return subprocess.CompletedProcess(command, 0, "synthetic boundary fixture\n", "")

        monkeypatch.setattr(candidate.subprocess, "run", run)
        return calls

    return install


def _runner(tmp_path: Path) -> candidate.Blender52CandidateRunner:
    return candidate.Blender52CandidateRunner(
        executable=tmp_path / "NEVER_EXECUTED_blender",
        workspace_root=tmp_path / "workspace",
    )


def test_existing_artifacts_are_never_accepted_for_a_new_run(
    tmp_path: Path, mocked_renderer: Callable[[Callable[[Path], None]], list[Path]]
) -> None:
    runner = _runner(tmp_path)
    destination = runner.workspace_root / "previous-run"
    destination.mkdir(parents=True)
    _write_outputs(destination)
    original = {name: (destination / name).read_bytes() for name in PAYLOADS}
    calls = mocked_renderer(lambda destination: None)

    with pytest.raises(candidate.BlenderCandidateError, match="new private directory"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert calls == []
    assert {name: (destination / name).read_bytes() for name in PAYLOADS} == original
    assert not (destination / "build_scene.py").exists()
    assert not (destination / "renderer-manifest.json").exists()


@pytest.mark.parametrize("kind", ["empty", "symlink", "dangling-symlink"])
def test_existing_directory_or_destination_link_is_rejected(
    tmp_path: Path,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
    kind: str,
) -> None:
    runner = _runner(tmp_path)
    runner.workspace_root.mkdir()
    destination = runner.workspace_root / "collision"
    target = runner.workspace_root / "link-target"
    if kind == "empty":
        destination.mkdir()
    else:
        if kind == "symlink":
            target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    calls = mocked_renderer(_write_outputs)

    with pytest.raises(candidate.BlenderCandidateError, match="new private directory"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert calls == []
    if kind != "empty":
        assert destination.is_symlink()
        if target.exists():
            assert list(target.iterdir()) == []
        else:
            assert kind == "dangling-symlink"


def test_destination_reservation_rejects_a_concurrent_creator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
) -> None:
    runner = _runner(tmp_path)
    destination = runner.workspace_root / "competing-run"
    calls = mocked_renderer(_write_outputs)
    original_mkdir = Path.mkdir
    raced = False

    def create_competing_directory(self: Path, *args: object, **kwargs: object) -> None:
        nonlocal raced
        if self == destination and not raced:
            raced = True
            original_mkdir(self, mode=0o700)
            (self / "other-run.txt").write_text("preserve this run", encoding="utf-8")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", create_competing_directory)

    with pytest.raises(candidate.BlenderCandidateError, match="new private directory"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert raced and calls == []
    assert sorted(path.name for path in destination.iterdir()) == ["other-run.txt"]
    assert (destination / "other-run.txt").read_text(encoding="utf-8") == "preserve this run"


@pytest.mark.parametrize("name", list(PAYLOADS))
def test_symlink_outputs_cannot_be_accepted_as_fresh_artifacts(
    tmp_path: Path,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
    name: str,
) -> None:
    runner = _runner(tmp_path)
    outside = tmp_path / "prior-output.bin"
    outside.write_bytes(PAYLOADS[name])

    def create_link(destination: Path) -> None:
        _write_outputs(destination)
        (destination / name).unlink()
        (destination / name).symlink_to(outside)

    mocked_renderer(create_link)
    destination = runner.workspace_root / "linked-output"
    with pytest.raises(candidate.BlenderCandidateError, match="fresh regular artifacts"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert outside.read_bytes() == PAYLOADS[name]
    assert not (destination / "renderer-manifest.json").exists()


def test_hardlinked_prior_output_is_not_a_fresh_owned_file(
    tmp_path: Path, mocked_renderer: Callable[[Callable[[Path], None]], list[Path]]
) -> None:
    runner = _runner(tmp_path)
    outside = tmp_path / "prior-output.bin"
    outside.write_bytes(PAYLOADS["scene.glb"])

    def create_link(destination: Path) -> None:
        (destination / "preview.png").write_bytes(PAYLOADS["preview.png"])
        os.link(outside, destination / "scene.glb")

    mocked_renderer(create_link)
    destination = runner.workspace_root / "hardlinked-output"
    with pytest.raises(candidate.BlenderCandidateError, match="fresh regular artifacts"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert outside.read_bytes() == PAYLOADS["scene.glb"]
    assert not (destination / "renderer-manifest.json").exists()


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_non_regular_outputs_are_rejected_without_waiting_for_a_writer(
    tmp_path: Path,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
    kind: str,
) -> None:
    runner = _runner(tmp_path)

    def create_non_regular(destination: Path) -> None:
        if kind == "directory":
            (destination / "scene.glb").mkdir()
        else:
            os.mkfifo(destination / "scene.glb")
        (destination / "preview.png").write_bytes(PAYLOADS["preview.png"])

    mocked_renderer(create_non_regular)
    destination = runner.workspace_root / "non-regular-output"
    with pytest.raises(candidate.BlenderCandidateError):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert not (destination / "renderer-manifest.json").exists()


def test_rejected_output_file_descriptor_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
) -> None:
    runner = _runner(tmp_path)
    destination = runner.workspace_root / "closed-descriptor"
    descriptors: list[int] = []
    original_open = os.open

    def create_directory(current: Path) -> None:
        (current / "scene.glb").mkdir()
        (current / "preview.png").write_bytes(PAYLOADS["preview.png"])

    def record_open(path: Path, *args: object, **kwargs: object) -> int:
        descriptor = original_open(path, *args, **kwargs)
        if Path(path) == destination / "scene.glb":
            descriptors.append(descriptor)
        return descriptor

    mocked_renderer(create_directory)
    monkeypatch.setattr(candidate.os, "open", record_open)
    with pytest.raises(candidate.BlenderCandidateError):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert len(descriptors) == 1
    with pytest.raises(OSError) as caught:
        os.fstat(descriptors[0])
    assert caught.value.errno == errno.EBADF


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_manifest_collision_never_overwrites_existing_data(
    tmp_path: Path,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
    kind: str,
) -> None:
    runner = _runner(tmp_path)
    outside = tmp_path / "must-remain-unchanged.txt"
    outside.write_text("preserve original data", encoding="utf-8")

    def create_collision(destination: Path) -> None:
        _write_outputs(destination)
        manifest = destination / "renderer-manifest.json"
        if kind == "symlink":
            manifest.symlink_to(outside)
        else:
            manifest.write_text("preserve renderer-created file", encoding="utf-8")

    mocked_renderer(create_collision)
    destination = runner.workspace_root / "manifest-collision"
    with pytest.raises(candidate.BlenderCandidateError, match="reserved file"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert outside.read_text(encoding="utf-8") == "preserve original data"
    manifest = destination / "renderer-manifest.json"
    if kind == "symlink":
        assert manifest.is_symlink()
    else:
        assert manifest.read_text(encoding="utf-8") == "preserve renderer-created file"


def test_fresh_regular_outputs_return_matching_hashes_and_private_manifest(
    tmp_path: Path, mocked_renderer: Callable[[Callable[[Path], None]], list[Path]]
) -> None:
    runner = _runner(tmp_path)
    calls = mocked_renderer(_write_outputs)
    destination = runner.workspace_root / "parent" / "fresh-run"
    artifact = runner.render(candidate.BlenderScenePlan("freshness-test"), "parent/fresh-run")

    assert calls == [destination]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / ".home").stat().st_mode) == 0o700
    for name in ("build_scene.py", "renderer-manifest.json"):
        assert stat.S_IMODE((destination / name).stat().st_mode) == 0o600
    assert artifact.glb_path == "scene.glb" and artifact.preview_path == "preview.png"
    assert artifact.glb_sha256 == hashlib.sha256(PAYLOADS["scene.glb"]).hexdigest()
    assert artifact.preview_sha256 == hashlib.sha256(PAYLOADS["preview.png"]).hexdigest()
    assert artifact.glb_bytes == len(PAYLOADS["scene.glb"])
    assert artifact.preview_bytes == len(PAYLOADS["preview.png"])
    assert json.loads((destination / "renderer-manifest.json").read_text()) == artifact.snapshot()


def test_successive_runs_use_distinct_destinations(
    tmp_path: Path, mocked_renderer: Callable[[Callable[[Path], None]], list[Path]]
) -> None:
    runner = _runner(tmp_path)
    calls = mocked_renderer(_write_outputs)
    first = runner.render(candidate.BlenderScenePlan("freshness-test"), "first")
    first_manifest = (runner.workspace_root / "first" / "renderer-manifest.json").read_bytes()
    with pytest.raises(candidate.BlenderCandidateError, match="new private directory"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), "first")
    second = runner.render(candidate.BlenderScenePlan("freshness-test"), "second")

    assert len(calls) == 2 and calls[0] != calls[1]
    assert first.glb_sha256 == second.glb_sha256
    assert (runner.workspace_root / "first" / "renderer-manifest.json").read_bytes() == first_manifest


def test_output_replaced_during_hashing_cannot_receive_a_success_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_renderer: Callable[[Callable[[Path], None]], list[Path]],
) -> None:
    runner = _runner(tmp_path)
    mocked_renderer(_write_outputs)
    destination = runner.workspace_root / "replaced-output"
    original_sha256 = hashlib.sha256
    replaced = False

    class ReplaceDuringHash:
        def __init__(self) -> None:
            self.digest = original_sha256()

        def update(self, chunk: bytes) -> None:
            nonlocal replaced
            self.digest.update(chunk)
            if not replaced:
                replacement = destination / "replacement.bin"
                replacement.write_bytes(PAYLOADS["scene.glb"])
                replacement.replace(destination / "scene.glb")
                replaced = True

        def hexdigest(self) -> str:
            return self.digest.hexdigest()

    monkeypatch.setattr(candidate.hashlib, "sha256", ReplaceDuringHash)
    with pytest.raises(candidate.BlenderCandidateError, match="changed during inspection"):
        runner.render(candidate.BlenderScenePlan("freshness-test"), destination)

    assert replaced
    assert not (destination / "renderer-manifest.json").exists()
