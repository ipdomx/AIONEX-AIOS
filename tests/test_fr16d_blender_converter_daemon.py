"""Roadmap 2.4: the Blender converter sidecar sandbox, with Blender mocked.

The subprocess runner is replaced by a fake for every Blender invocation; one
test runs a real, harmless child process to prove the timeout kills it and the
resource limits are applied.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "infra/blender-converter"


def _load():
    spec = importlib.util.spec_from_file_location("aionex_converter_daemon", CONVERTER / "converter_daemon.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def daemon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = _load()
    monkeypatch.setattr(module, "SPOOL", tmp_path / "spool")
    module.prepare_spool()
    return module


def _request(daemon, name: str = "a" * 32, body: bytes = b"glTF" + b"\x00" * 16, request: dict | None = None) -> Path:
    job = daemon.SPOOL / "requests" / name
    job.mkdir(parents=True)
    (job / "input.glb").write_bytes(body)
    (job / "request.json").write_text(json.dumps(request or {"input_format": "glb", "formats": ["fbx", "obj"], "thumbnail": True, "thumbnail_size": 128}))
    return job


class FakeBlender:
    def __init__(self, *, returncode: int = 0, stdout: str = "", results: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.returncode, self.stdout, self.results = returncode, stdout, results

    def __call__(self, command, *, cwd, env, timeout):
        self.calls.append({"command": command, "cwd": cwd, "env": env, "timeout": timeout})
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "Blender 5.2.3 LTS\nbuild hash: e13b728c6880\n", "")
        spec = json.loads(Path(command[-1]).read_text())
        if self.returncode == 0:
            results = self.results or {item["format"]: {"ok": True} for item in spec["outputs"]}
            if spec["thumbnail"]:
                results.setdefault("thumbnail", {"ok": True})
            Path(spec["result"]).write_text(json.dumps({"blender": "5.2.3 LTS", "results": results}))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


def test_blender_runs_headless_without_autoexec_addons_or_network(daemon) -> None:
    fake = FakeBlender()
    job = _request(daemon)
    result = daemon.process_request(job, fake)
    assert result["ok"] and result["results"]["fbx"] == {"ok": True}
    command = fake.calls[0]["command"]
    assert command[:6] == [daemon.BLENDER, "--background", "--factory-startup", "--disable-autoexec", "--offline-mode", "--python-exit-code"]
    assert command[command.index("--python") + 1] == str(daemon.SCRIPT)
    assert fake.calls[0]["timeout"] == daemon.TIMEOUT_SECONDS and fake.calls[0]["cwd"] == job
    env = fake.calls[0]["env"]
    assert not {"PYTHONPATH", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy"} & set(env)
    assert env["BLENDER_USER_SCRIPTS"].startswith(str(job)) and env["HOME"].startswith(str(job))
    spec = json.loads((job / "blender-spec.json").read_text())
    assert spec["thumbnail"]["size"] == 128
    assert all(Path(item["path"]).is_relative_to(job) for item in spec["outputs"])
    assert not (job / "home").exists(), "private Blender home is removed after the run"


@pytest.mark.parametrize(
    ("body", "payload", "reason"),
    [
        (b"PK\x03\x04 not a glb at all", None, "input_not_glb"),
        (b"glTF" + b"\x00" * 16, {"input_format": "fbx"}, "request_invalid"),
        (b"glTF" + b"\x00" * 16, {"input_format": "glb", "thumbnail_size": "huge"}, "request_invalid"),
    ],
)
def test_untrusted_requests_are_rejected_before_blender(daemon, body: bytes, payload, reason: str) -> None:
    fake = FakeBlender()
    result = daemon.process_request(_request(daemon, body=body, request=payload), fake)
    assert result == {"ok": False, "reason": reason, "results": {}}
    assert fake.calls == []


def test_oversized_input_is_rejected(daemon, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "MAX_INPUT_BYTES", 8)
    assert daemon.process_request(_request(daemon), FakeBlender())["reason"] == "input_too_large"


def test_unknown_formats_are_never_passed_to_blender(daemon) -> None:
    fake = FakeBlender()
    job = _request(daemon, request={"input_format": "glb", "formats": ["fbx", "blend", "../../etc"], "thumbnail": False})
    daemon.process_request(job, fake)
    spec = json.loads((job / "blender-spec.json").read_text())
    assert [item["format"] for item in spec["outputs"]] == ["fbx"] and spec["thumbnail"] is None


def test_timeout_and_crash_are_reported_without_outputs(daemon) -> None:
    timed_out = daemon.process_request(_request(daemon, "b" * 32), FakeBlender(returncode=-9, stdout="timeout"))
    crashed = daemon.process_request(_request(daemon, "c" * 32), FakeBlender(returncode=1))
    assert timed_out["reason"] == "timeout" and crashed["reason"] == "blender_exit_nonzero"
    assert timed_out["results"] == {} == crashed["results"]


def test_run_once_claims_atomically_and_publishes_to_done(daemon) -> None:
    _request(daemon, "d" * 32)
    (daemon.SPOOL / "requests" / "not-a-valid-id").mkdir()
    assert daemon.run_once(FakeBlender()) is True
    done = daemon.SPOOL / "done" / ("d" * 32)
    assert json.loads((done / "result.json").read_text())["ok"] is True
    assert not (done / "input.glb").exists()
    assert daemon.run_once(FakeBlender()) is False
    assert not (daemon.SPOOL / "requests" / "not-a-valid-id").exists()


def test_restart_fails_orphaned_work_and_gc_removes_stale_entries(daemon) -> None:
    orphan = daemon.SPOOL / "work" / ("e" * 32)
    orphan.mkdir()
    daemon.prepare_spool()
    assert json.loads((daemon.SPOOL / "done" / ("e" * 32) / "result.json").read_text())["reason"] == "converter_restarted"
    assert daemon.collect_stale(now=time.time() + daemon.STALE_SECONDS + 5) == 1


def test_probe_and_healthcheck_require_the_pinned_series(daemon, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    status = daemon.probe(FakeBlender(), scratch=tmp_path / "probe")
    assert status["available"] and status["blender_version"] == "5.2.3" and status["formats"] == ["obj", "fbx", "usdz"]
    daemon.write_status(status)
    assert daemon.healthcheck() == 0
    monkeypatch.setattr(daemon, "REQUIRED_SERIES", "5.3")
    unpinned = daemon.probe(FakeBlender(), scratch=tmp_path / "probe")
    assert not unpinned["available"] and unpinned["reason"] == "blender_version_not_pinned"
    daemon.write_status({**status, "updated_at": time.time() - 3600})
    assert daemon.healthcheck() == 1


def test_real_child_process_gets_rlimits_and_is_killed_on_timeout(daemon, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(daemon, "CPU_SECONDS", 30)
    probe = "import resource; print(resource.getrlimit(resource.RLIMIT_CPU)[0], resource.getrlimit(resource.RLIMIT_CORE)[0], resource.getrlimit(resource.RLIMIT_NOFILE)[0])"
    result = daemon.run_sandboxed([sys.executable, "-I", "-c", probe], cwd=tmp_path, env=daemon.sandbox_env(tmp_path / "h"), timeout=30)
    assert result.returncode == 0 and result.stdout.split() == ["30", "0", "512"]
    started = time.monotonic()
    slow = daemon.run_sandboxed([sys.executable, "-I", "-c", "import time; time.sleep(30)"], cwd=tmp_path, env=daemon.sandbox_env(tmp_path / "h2"), timeout=1)
    assert slow.stdout == "timeout" and slow.returncode < 0 and time.monotonic() - started < 10


def test_bpy_script_blocks_network_before_importing_bpy() -> None:
    script = (CONVERTER / "three_d_convert.py").read_text()
    assert script.index("socket.socket = _deny_network") < script.index("import bpy")
    assert "read_factory_settings(use_empty=True)" in script
    assert "_inside(root, " in script


def test_converter_image_is_pinned_network_less_and_non_root() -> None:
    dockerfile = (CONVERTER / "Dockerfile").read_text()
    assert dockerfile.count("FROM ubuntu:24.04@sha256:") == 2
    assert "ARG BLENDER_VERSION=5.2.3" in dockerfile
    assert "ARG BLENDER_SHA256=78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec" in dockerfile
    assert "sha256sum -c -" in dockerfile and "USER aionex" in dockerfile
    assert "Blender converter contract: PASS" in dockerfile
    for compose in ("deploy/production/docker-compose.production.yml", "web-dashboard/docker-compose.production.yml"):
        text = (ROOT / compose).read_text()
        block = text[text.index("  three-d-converter:"):]
        block = block[: block.index("\n\n")]
        assert "network_mode: none" in block and "read_only: true" in block and 'cap_drop: ["ALL"]' in block
        assert "no-new-privileges:true" in block
