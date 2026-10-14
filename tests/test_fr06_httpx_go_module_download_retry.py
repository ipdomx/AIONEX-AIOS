"""Bounded retry / immutable Go module lock regression tests (no network)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location(
        "httpx_retry_candidate", SCRIPTS / "build_httpx.py"
    )
    assert spec and spec.loader
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
finally:
    sys.path.pop(0)


def fixture_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "go.mod").write_text("module fixture.invalid/retry\n")
    (source / "go.sum").write_text("fixture.invalid/retry v1 h1:fixture\n")
    output = tmp_path / "output"
    output.mkdir()
    return source, output


def scripted(responses, commands):
    calls = iter(responses)

    def runner(argv, **kwargs):
        assert argv == ["/fixture/pinned-go", "mod", "download", "all"]
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 240
        assert kwargs["env"]["GOTOOLCHAIN"] == "local"
        commands.append(tuple(argv))
        outcome = next(calls)
        kwargs["stdout"].write(outcome[1])
        if outcome[0] == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, outcome[0])
    return runner


def test_transient_go_proxy_failure_recovers_with_exact_same_inputs(tmp_path, capsys):
    source, output = fixture_paths(tmp_path)
    environment = {"GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly"}
    before = tuple((source / name).read_bytes() for name in ("go.mod", "go.sum"))
    commands = []
    sleep = []
    fake = scripted([(1, b"proxy.golang.org: connection reset by peer"),
                     (0, b"all pinned modules verified")], commands)
    attempts = candidate.download_pinned_modules(
        "/fixture/pinned-go", source, environment, output,
        runner=fake, sleeper=sleep.append,
    )
    assert len(attempts) == 2
    assert len(commands) == 2 and commands[0] == commands[1]
    assert sleep == [2]
    assert (output / "go-module-download-attempts.json").is_file()
    receipt = json.loads((output / "go-module-download-attempts.json").read_text())
    assert receipt["status"] == "PASS" and len(receipt["attempts"]) == 2
    assert receipt["source_or_module_locks_changed"] is False
    assert before == tuple((source / name).read_bytes() for name in ("go.mod", "go.sum"))
    assert "AIONEX_PINNED_GO_DOWNLOAD_RECOVERED" in capsys.readouterr().out


def test_source_integrity_checksum_failure_never_retried(tmp_path, capsys):
    source, output = fixture_paths(tmp_path)
    commands = []
    fake = scripted([(1, b"go: security error: checksum mismatch")], commands)
    with pytest.raises(RuntimeError, match="Pinned Go module download failed"):
        candidate.download_pinned_modules(
            "/fixture/pinned-go", source, {"GOTOOLCHAIN": "local"}, output,
            runner=fake, sleeper=lambda _: pytest.fail("integrity failure must not be retried"),
        )
    proof = json.loads((output / "go-module-download-attempts.json").read_text())
    assert proof["status"] == "FAIL_CLOSED" and len(proof["attempts"]) == 1
    assert proof["attempts"][0]["integrity_or_lock_failure"] is True
    assert len(commands) == 1
    assert "AIONEX_BUILD_FAILURE" in capsys.readouterr().err


def test_persistent_remote_failure_stays_red_with_three_bounded_attempts(tmp_path, capsys):
    source, output = fixture_paths(tmp_path)
    commands = []
    sleep = []
    fake = scripted([(1, b"proxy.golang.org: stream closed")]*3, commands)
    with pytest.raises(RuntimeError, match="Pinned Go module download failed"):
        candidate.download_pinned_modules(
            "/fixture/pinned-go", source, {"GOTOOLCHAIN": "local"}, output,
            runner=fake, sleeper=sleep.append,
        )
    proof = json.loads((output / "go-module-download-attempts.json").read_text())
    assert len(commands) == 3
    assert sleep == [2, 5]
    assert proof["status"] == "FAIL_CLOSED"
    assert len(proof["attempts"]) == 3
    assert "AIONEX_BUILD_FAILURE" in capsys.readouterr().err


def test_timeout_then_clean_verified_retry(tmp_path):
    source, output = fixture_paths(tmp_path)
    commands = []
    fake = scripted([("timeout", b"temporary deadline"), (0, b"success")], commands)
    attempts = candidate.download_pinned_modules(
        "/fixture/pinned-go", source, {"GOTOOLCHAIN": "local"}, output,
        runner=fake, sleeper=lambda _: None,
    )
    assert len(commands) == 2
    assert attempts[0]["timed_out"] is True and attempts[0]["return_code"] is None
    assert attempts[1]["return_code"] == 0
    assert json.loads((output / "go-module-download-attempts.json").read_text())["status"] == "PASS"


def test_invalid_module_path_and_required_go_version_are_not_retried(tmp_path):
    for i, error in enumerate((b"go: invalid version: unknown revision",
                               b"go: module requires go >= 1.28")):
        source, output = fixture_paths(tmp_path / ("case"+str(i)))
        calls = []
        with pytest.raises(RuntimeError):
            candidate.download_pinned_modules(
                "/fixture/pinned-go", source, {"GOTOOLCHAIN": "local"}, output,
                runner=scripted([(1, error)], calls),
                sleeper=lambda _: pytest.fail("deterministic module resolution must fail immediately"),
            )
        assert len(calls) == 1
