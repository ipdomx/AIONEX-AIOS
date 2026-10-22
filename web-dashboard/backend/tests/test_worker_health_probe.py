"""Regression tests for the dependency-free Docker worker heartbeat probe."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "worker_health_probe.py"
SPEC = importlib.util.spec_from_file_location("worker_health_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

NOW = 1_800_000_000.0


@pytest.mark.parametrize("kind,status", [
    ("three-d", "ok"),
    ("user-telegram", "running"),
])
def test_current_heartbeats_pass(tmp_path: Path, kind: str, status: str) -> None:
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"status": status, "checked_at_epoch": NOW - 60}))
    assert probe.check_heartbeat(path, probe.POLICIES[kind], now_epoch=NOW)


@pytest.mark.parametrize("kind,status", [
    ("three-d", "ok"),
    ("user-telegram", "running"),
])
@pytest.mark.parametrize("offset", [-121, -10000, 10000])
def test_stale_or_far_future_heartbeat_fails(
    tmp_path: Path, kind: str, status: str, offset: int
) -> None:
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"status": status, "checked_at_epoch": NOW + offset}))
    assert not probe.check_heartbeat(path, probe.POLICIES[kind], now_epoch=NOW)


def test_three_d_allows_existing_30_second_clock_skew_only(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"status": "ok", "checked_at_epoch": NOW + 29}))
    assert probe.check_heartbeat(path, probe.POLICIES["three-d"], now_epoch=NOW)
    path.write_text(json.dumps({"status": "running", "checked_at_epoch": NOW + 29}))
    assert not probe.check_heartbeat(path, probe.POLICIES["user-telegram"], now_epoch=NOW)


@pytest.mark.parametrize("kind,expected", [("three-d", "ok"), ("user-telegram", "running")])
@pytest.mark.parametrize("corruption", [
    {"status": "stopped", "checked_at_epoch": NOW},
    {"status": "starting", "checked_at_epoch": NOW},
    {"checked_at_epoch": NOW},
    {"status": "ok"},
    {"status": "ok", "checked_at_epoch": "NaN"},
    {"status": "ok", "checked_at_epoch": float("inf")},
    {"status": "ok", "checked_at_epoch": True},
])
def test_invalid_receipt_never_passes(
    tmp_path: Path, kind: str, expected: str, corruption: dict
) -> None:
    path = tmp_path / "health.json"
    sample = dict(corruption)
    if sample.get("status") == "ok" and expected == "running":
        sample["status"] = "running"
    path.write_text(json.dumps(sample))
    assert not probe.check_heartbeat(path, probe.POLICIES[kind], now_epoch=NOW)


def test_malformed_missing_and_oversized_files_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    policy = probe.POLICIES["three-d"]
    assert not probe.check_heartbeat(path, policy, now_epoch=NOW)
    path.write_text("{this-is-not-json")
    assert not probe.check_heartbeat(path, policy, now_epoch=NOW)
    path.write_bytes(b" " * (probe.MAX_HEALTH_BYTES + 1))
    assert not probe.check_heartbeat(path, policy, now_epoch=NOW)


@pytest.mark.parametrize("kind,status,env_var", [
    ("three-d", "ok", "THREE_D_WORKER_HEALTH_FILE"),
    ("user-telegram", "running", "AIOS_USER_TELEGRAM_HEALTH_FILE"),
])
def test_real_cli_uses_configured_path_and_has_no_app_dependencies(
    tmp_path: Path, kind: str, status: str, env_var: str
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"status": status, "checked_at_epoch": __import__("time").time()}))
    env = dict(os.environ)
    env[env_var] = str(path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--kind", kind],
        capture_output=True, env=env, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b""


def test_compose_keeps_original_verified_healthcheck_contracts() -> None:
    compose = (SCRIPT.parents[2] / "docker-compose.production.yml").read_text()
    three_d = compose.split("\n  three-d-worker:", 1)[1].split("\n  project-worker:", 1)[0]
    telegram = compose.split("\n  user-telegram-worker:", 1)[1].split("\n  security-tool-cache-init:", 1)[0]
    assert 'test: ["CMD", "su-exec", "aionex", "python", "-m", "app.services.three_d_worker", "--healthcheck"]' in three_d
    assert 'test: ["CMD", "python", "-m", "app.services.user_telegram_worker", "--healthcheck"]' in telegram


@pytest.mark.parametrize("kind,module_name,status,env_var", [
    ("three-d", "app.services.three_d_worker", "ok", "THREE_D_WORKER_HEALTH_FILE"),
    ("user-telegram", "app.services.user_telegram_worker", "running", "AIOS_USER_TELEGRAM_HEALTH_FILE"),
])
def test_original_worker_cli_fastpath_needs_no_sqlalchemy_or_provider_dependencies(
    tmp_path: Path, kind: str, module_name: str, status: str, env_var: str,
) -> None:
    path = tmp_path / "worker.json"
    env = dict(os.environ)
    env[env_var] = str(path)
    env["PYTHONPATH"] = str(SCRIPT.parents[1])
    path.write_text(json.dumps({"status": status, "checked_at_epoch": __import__("time").time()}))
    successful = subprocess.run(
        [sys.executable, "-m", module_name, "--healthcheck"],
        cwd=SCRIPT.parents[1], env=env, capture_output=True, timeout=5,
    )
    assert successful.returncode == 0, successful.stderr.decode(errors="replace")
    assert successful.stdout == b""
    path.write_text(json.dumps({"status": status, "checked_at_epoch": 1.0}))
    stale = subprocess.run(
        [sys.executable, "-m", module_name, "--healthcheck"],
        cwd=SCRIPT.parents[1], env=env, capture_output=True, timeout=5,
    )
    assert stale.returncode == 1, stale.stderr.decode(errors="replace")
    assert stale.stdout == b""


def test_3d_healthcheck_fastpath_precedes_expensive_service_imports() -> None:
    source = (SCRIPT.parents[1] / "app/services/three_d_worker.py").read_text()
    assert source.index('if _health_sys.argv[1:] == ["--healthcheck"]:') < source.index(
        "from app.services.host_maintenance_media_claims import"
    )
    assert source.index('raise SystemExit(_healthcheck("three-d"))') < source.index(
        "from fastapi import HTTPException"
    )


def test_user_telegram_healthcheck_fastpath_precedes_sqlalchemy() -> None:
    source = (SCRIPT.parents[1] / "app/services/user_telegram_worker.py").read_text()
    assert source.index('if _health_sys.argv[1:] == ["--healthcheck"]:') < source.index(
        "from sqlalchemy import select"
    )
    assert 'raise SystemExit(_healthcheck("user-telegram"))' in source
