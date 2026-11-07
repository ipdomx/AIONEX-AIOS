"""P6 gate 6.4: isolated restore drill production guards and safe asset extraction."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/restore-drill/docker-compose.restore-drill.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


drill = _load("p6_isolated_restore_drill", ROOT / "scripts/recovery/p6_isolated_restore_drill.py")
fetch = _load("restore_drill_fetch", ROOT / "web-dashboard/backend/app/services/restore_drill_fetch.py")

PROJECT = "aionex-restore-drill-20261120t090000z"
ENV = {
    "DRILL_ENV_FILE": "/var/lib/aionex-migration/p6-restore-drill/x/drill.env",
    "DRILL_R2_SECRET_FILE": "/root/.config/aionex/r2-backup/credentials.env",
    "DRILL_KEYRING_FILE": "/root/.config/aionex/backup-encryption/keyring.json",
    "DRILL_CANARY_EMAIL": "p6-20261120t0900z-00000@synthetic.loadtest.invalid",
    "DRILL_CANARY_PASSWORD_FILE": "/root/p6/canary-password",
}
ALLOWED = {
    "fetch": {ENV["DRILL_R2_SECRET_FILE"], ENV["DRILL_KEYRING_FILE"]},
    "smoke": {str(ROOT / "deploy/restore-drill/smoke.py"), ENV["DRILL_CANARY_PASSWORD_FILE"]},
}


def _subst(value: str) -> str:
    return re.sub(r"\$\{([A-Z0-9_]+)(?::[-?][^}]*)?\}", lambda m: ENV.get(m.group(1), ""), value)


def _docker_compose_config() -> dict | None:
    if shutil.which("docker") is None:
        return None
    argv = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE)]
    for profile in ("fetch", "restore", "app", "smoke"):
        argv += ["--profile", profile]
    env = {**os.environ, **ENV, "DRILL_ENV_FILE": os.devnull}
    try:
        result = subprocess.run(argv + ["config", "--format", "json"], env=env, capture_output=True,
                                text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return json.loads(result.stdout) if result.returncode == 0 else None


_CACHED: dict = {}


def rendered() -> dict:
    """The drill compose file as `docker compose config` renders it (YAML fallback)."""
    if "config" not in _CACHED:
        _CACHED["config"] = _docker_compose_config() or _yaml_config()
    return copy.deepcopy(_CACHED["config"])


def _yaml_config() -> dict:
    yaml = pytest.importorskip("yaml")
    raw = yaml.safe_load(COMPOSE.read_text())
    config = {"name": PROJECT, "services": {}, "networks": {}, "volumes": {}}
    for key, value in raw["networks"].items():
        config["networks"][key] = {"name": f"{PROJECT}_{key}", **(value or {})}
    for key, value in raw["volumes"].items():
        config["volumes"][key] = {"name": f"{PROJECT}_{key}", **(value or {})}
    for name, service in raw["services"].items():
        out = {k: v for k, v in service.items() if k not in ("volumes", "networks")}
        out["networks"] = {n: None for n in service.get("networks", [])}
        mounts = []
        for spec in service.get("volumes", []):
            parts = _subst(spec).split(":")
            source, target = parts[0], parts[1]
            read_only = len(parts) > 2 and parts[2] == "ro"
            if source.startswith("./"):
                source = str((COMPOSE.parent / source).resolve())
            kind = "bind" if source.startswith("/") else "volume"
            mounts.append({"type": kind, "source": source, "target": target, "read_only": read_only})
        out["volumes"] = mounts
        config["services"][name] = out
    return config


def test_project_name_guard():
    drill.validate_project_name(PROJECT)
    for bad in ("web-dashboard", "aionex-restore-drill-web-dashboard", "aionex-restore-drill-2026", "drill"):
        with pytest.raises(drill.DrillRefused):
            drill.validate_project_name(bad)


def test_real_drill_compose_passes_every_guard():
    assert drill.validate_compose_config(rendered(), PROJECT, ALLOWED) == []


def test_restored_app_has_no_egress_and_only_fetch_reaches_r2():
    config = rendered()
    assert config["networks"]["drill_isolated"]["internal"] is True
    for name, service in config["services"].items():
        if "drill_egress" in (service.get("networks") or {}):
            assert name == "fetch"
        assert "ports" not in service


@pytest.mark.parametrize("mutation, expected", [
    (lambda c: c["services"]["backend"].__setitem__("ports", ["8000:8000"]), "backend publishes ports"),
    (lambda c: c["services"]["backend"].setdefault("networks", {}).__setitem__("drill_egress", None), "backend must not reach the internet"),
    (lambda c: c["networks"]["drill_isolated"].__setitem__("internal", False), "drill_isolated must be internal"),
    (lambda c: c["volumes"]["drill_pgdata"].__setitem__("name", "web-dashboard_postgres_data"), "volume drill_pgdata is not project-scoped"),
    (lambda c: c["volumes"]["drill_pgdata"].__setitem__("external", True), "volume drill_pgdata is external"),
    (lambda c: c["networks"].__setitem__("web-dashboard_aionex-network", {"external": True}), "unexpected network"),
    (lambda c: c["services"]["backend"].__setitem__("network_mode", "host"), "backend uses network_mode host"),
    (lambda c: c["services"]["backend"]["volumes"].append(
        {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock", "read_only": True}),
     "backend mounts the Docker socket"),
    (lambda c: c["services"]["backend"]["volumes"].append(
        {"type": "volume", "source": "web-dashboard_media_asset_data", "target": "/x"}), "backend mounts foreign volume"),
    (lambda c: c["services"]["fetch"]["volumes"].__setitem__(1, {**c["services"]["fetch"]["volumes"][1], "read_only": False}),
     "is not read-only"),
    (lambda c: c["services"]["fetch"].setdefault("networks", {}).__setitem__("drill_isolated", None), "must not bridge egress"),
    (lambda c: c.__setitem__("name", "web-dashboard"), "rendered project name differs"),
])
def test_guard_violations_are_refused(mutation, expected):
    config = copy.deepcopy(rendered())
    mutation(config)
    problems = drill.validate_compose_config(config, PROJECT, ALLOWED)
    assert any(expected in problem for problem in problems), problems


def test_plan_is_dry(capsys):
    assert drill.main(["plan", "--project", PROJECT]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["docker_commands_run"] == 0 and len(out["steps"]) == 8
    assert drill.main(["run", "--project", "web-dashboard", "--execute"]) == 2


def _archive(members: dict[str, bytes], symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            bundle.addfile(info)
    return buffer.getvalue()


def test_asset_extraction_restores_per_root_layout(tmp_path):
    archive = tmp_path / "a.tar"
    archive.write_bytes(_archive({"manifest.json": b"{}", "files/media_asset_data/org/a.png": b"png",
                                  "files/portal_asset_data/b.webp": b"webp!"}))
    dest = tmp_path / "restore"
    dest.mkdir()
    result = fetch.extract(archive, dest)
    assert result["files"] == 2
    assert (dest / "media_asset_data/org/a.png").read_bytes() == b"png"
    assert result["roots"]["portal_asset_data"] == {"files": 1, "bytes": 5}


@pytest.mark.parametrize("members, link", [
    ({"files/../../etc/x": b"x"}, None),
    ({"files/unknown_root/x": b"x"}, None),
    ({"other/x": b"x"}, None),
    ({}, "files/media_asset_data/link"),
])
def test_asset_extraction_refuses_unsafe_members(tmp_path, members, link):
    archive = tmp_path / "a.tar"
    archive.write_bytes(_archive(members, link))
    dest = tmp_path / "restore"
    dest.mkdir()
    with pytest.raises(fetch.DrillFetchError):
        fetch.extract(archive, dest)


def test_fetch_module_refuses_outside_the_drill(monkeypatch, capsys):
    monkeypatch.delenv("AIOS_RESTORE_DRILL", raising=False)
    assert fetch.main(["extract", "--archive", "/nonexistent", "--destination", "/tmp/x"]) == 2
