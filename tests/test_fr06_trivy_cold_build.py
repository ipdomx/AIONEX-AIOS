"""Cold-build orchestration regressions; no scanner/network/production actions."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("trivy_cold_build_target", SCRIPTS / "build_trivy.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


def read_receipt(log: Path):
    return json.loads(log.with_name(log.name + ".execution.json").read_text())


def test_cold_compilation_budget_is_bounded_and_recorded(tmp_path, monkeypatch, capsys):
    calls = []
    def fake_run(args, cwd, env, output, timeout):
        calls.append((args, cwd, env, output, timeout))
        output.write_text("build complete\n")
    monkeypatch.setattr(m, "run", fake_run)
    args = ["go", "test", "-timeout=120s", "./pkg/db"]
    log = tmp_path / "tests.jsonl"
    env = {"SYNTHETIC_NOT_FOR_LOGGING": "not-a-real-secret"}
    m.run_cold_build_step(args, tmp_path, env, log)
    assert calls == [(args, tmp_path, env, log, 1800)]
    record = read_receipt(log)
    assert record["status"] == "PASSED" and record["outer_timeout_seconds"] == 1800
    assert record["elapsed_seconds"] >= 0
    assert record["command"] == args and "failure_log_tail" not in record
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "PASSED"
    assert "SYNTHETIC_NOT_FOR_LOGGING" not in output and "not-a-real-secret" not in output


@pytest.mark.parametrize("failure", [RuntimeError("synthetic nonzero"), OSError("synthetic executable missing")])
def test_failure_is_never_converted_to_acceptance(tmp_path, monkeypatch, failure):
    def fail(args, cwd, env, output, timeout):
        output.write_text("retained diagnostic\n")
        raise failure
    monkeypatch.setattr(m, "run", fail)
    log = tmp_path / "build.log"
    with pytest.raises(type(failure)) as exc:
        m.run_cold_build_step(["go", "build"], tmp_path, {}, log)
    assert exc.value is failure
    assert read_receipt(log)["status"] == "FAILED"
    assert read_receipt(log)["failure_log_tail"] == "retained diagnostic\n"


def test_outer_timeout_is_retained_and_raised(tmp_path, monkeypatch):
    failure = subprocess.TimeoutExpired(["go", "test"], 1800)
    def fail(args, cwd, env, output, timeout):
        output.write_text("compiler still active\n")
        raise failure
    monkeypatch.setattr(m, "run", fail)
    log = tmp_path / "tests.jsonl"
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        m.run_cold_build_step(["go", "test"], tmp_path, {}, log)
    assert exc.value is failure
    assert read_receipt(log)["status"] == "TIMED_OUT"
    assert read_receipt(log)["outer_timeout_seconds"] == 1800


def test_no_log_when_process_cannot_start_is_not_false_success(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("synthetic")
    monkeypatch.setattr(m, "run", fail)
    log = tmp_path / "absent.log"
    with pytest.raises(FileNotFoundError):
        m.run_cold_build_step(["missing"], tmp_path, {}, log)
    record = read_receipt(log)
    assert record["status"] == "FAILED" and "failure_log_tail" not in record


def test_failure_tail_is_bounded_and_terminal_controls_are_escaped(tmp_path, monkeypatch, capsys):
    payload = "x" * 50000 + "\x1b[31mBAD\x1b[0m\x00\n"
    def fail(args, cwd, env, output, timeout):
        output.write_text(payload)
        raise RuntimeError("synthetic")
    monkeypatch.setattr(m, "run", fail)
    log = tmp_path / "huge.log"
    with pytest.raises(RuntimeError):
        m.run_cold_build_step(["go", "test"], tmp_path, {}, log)
    stdout = capsys.readouterr().out
    assert "\x1b" not in stdout and "\x00" not in stdout
    record = json.loads(stdout)
    assert len(record["failure_log_tail"].encode()) == m.FAILURE_LOG_TAIL_BYTES == 16384
    assert record["failure_log_tail"].endswith("BAD\x1b[0m\x00\n")
    assert log.read_text() == payload


def test_symlink_log_is_never_followed_for_diagnostic_output(tmp_path, monkeypatch, capsys):
    outside = tmp_path / "not-log"
    outside.write_text("not permitted in diagnostic")
    log = tmp_path / "build.log"
    log.symlink_to(outside)
    def fail(*args, **kwargs):
        raise FileExistsError("log already exists")
    monkeypatch.setattr(m, "run", fail)
    with pytest.raises(FileExistsError):
        m.run_cold_build_step(["go", "build"], tmp_path, {}, log)
    assert "failure_log_tail" not in read_receipt(log)
    assert "not permitted" not in capsys.readouterr().out


def test_real_nonzero_process_fails_and_retains_its_output(tmp_path):
    log = tmp_path / "native-process.log"
    args = [sys.executable, "-c", "print('SYNTHETIC_BUILD_ERROR'); raise SystemExit(7)"]
    with pytest.raises(RuntimeError):
        m.run_cold_build_step(args, tmp_path, {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, log)
    record = read_receipt(log)
    assert record["status"] == "FAILED" and "SYNTHETIC_BUILD_ERROR" in record["failure_log_tail"]


def test_existing_receipt_is_not_overwritten(tmp_path, monkeypatch):
    log = tmp_path / "build.log"
    receipt = log.with_name(log.name + ".execution.json")
    receipt.write_text("prior evidence")
    def fake_run(args, cwd, env, output, timeout):
        output.write_text("success\n")
    monkeypatch.setattr(m, "run", fake_run)
    with pytest.raises(FileExistsError):
        m.run_cold_build_step(["go", "build"], tmp_path, {}, log)
    assert receipt.read_text() == "prior evidence"


def test_selected_tests_and_package_timeout_are_not_relaxed():
    source = (SCRIPTS / "build_trivy.py").read_text()
    assert len(m.TEST_PACKAGES) == 7
    assert '"-count=1", "-timeout=120s", "-json", *TEST_PACKAGES' in source
    assert 'run_cold_build_step([go, "test"' in source
    assert 'run_cold_build_step(build_command(go, binary, lock)' in source
    assert 'run([go, "mod", "download", "all"]' in source
    assert 'run([go, "mod", "verify"]' in source
    assert 'if not counts["pass"] or counts["fail"] or counts["skip"]' in source
    assert 'if sha(binary) != lock["expected_binary_sha256"]' in source
    assert '"GOEXPERIMENT": "jsonv2"' in source


def test_trivy_waits_for_grype_without_using_a_prebuilt_trivy_binary():
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    stage = dockerfile.split(" AS trivy-builder\n", 1)[1].split(" AS runtime\n", 1)[0]
    dependency = "COPY --from=grype-builder /build/grype-output/grype-build-provenance.json /build/prerequisites/grype-build-provenance.json"
    assert dependency in stage
    assert stage.index(dependency) < stage.index("RUN python build_trivy.py")
    assert "COPY --from=grype-builder /build/grype-output/trivy" not in stage
    assert "RUN python build_trivy.py --lock-dir /build/trivy-lock --output /build/trivy-output" in stage
