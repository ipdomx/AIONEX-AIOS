"""FR-09 isolated lab storage identity and fail-closed release gates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "capacity" / "fr09_profile.py"
SPEC = importlib.util.spec_from_file_location("fr09_isolated_lab_gate", SOURCE)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def profile():
    return mod.CapacityProfile.from_plan(json.loads((ROOT / "docs/project/PLAN.json").read_text()))


@pytest.fixture()
def isolated(monkeypatch, tmp_path: Path):
    lab = tmp_path / "lab"
    docker = lab / "docker-data"
    containerd = lab / "containerd-data"
    docker.mkdir(parents=True)
    containerd.mkdir()
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    dockerd_cfg = cfg_dir / "dockerd.json"
    containerd_cfg = cfg_dir / "containerd.toml"
    unit = cfg_dir / "containerd.service"
    docker_socket = tmp_path / "docker.sock"
    containerd_socket = tmp_path / "containerd.sock"
    expected = {
        "data-root": str(docker),
        "hosts": ["unix://" + str(docker_socket)],
        "exec-root": "/run/aionex-fr09-lab/docker-exec",
        "bridge": "none",
        "iptables": False,
        "ip6tables": False,
        "ip-forward": False,
        "ip-masq": False,
        "userland-proxy": False,
    }
    dockerd_cfg.write_text(json.dumps(expected))
    containerd_cfg.write_text(
        "root = " + json.dumps(str(containerd)) + "\n"
        'state = "/run/aionex-fr09-lab/containerd-state"\n'
    )
    unit.write_text("ExecStart=/usr/bin/containerd --address " + str(containerd_socket))
    monkeypatch.setattr(mod, "FR09_LAB_ROOT", lab)
    monkeypatch.setattr(mod, "FR09_LAB_DOCKER_CONFIG", dockerd_cfg)
    monkeypatch.setattr(mod, "FR09_LAB_CONTAINERD_CONFIG", containerd_cfg)
    monkeypatch.setattr(mod, "FR09_LAB_DOCKER_SOCKET", docker_socket)
    monkeypatch.setattr(mod, "FR09_LAB_CONTAINERD_SOCKET", containerd_socket)
    monkeypatch.setattr(mod, "FR09_LAB_CONTAINERD_UNIT", unit)
    monkeypatch.setattr(mod, "_verified_luks_lab_mount", lambda path: None)

    def device(path: Path) -> int:
        name = str(path)
        if name.startswith(str(lab)):
            return 7
        return 2 if name.startswith("/var/lib/") else 1

    monkeypatch.setattr(mod, "_fs_device", device)
    sock_orig = Path.is_socket
    monkeypatch.setattr(
        Path, "is_socket",
        lambda p: True if p in (docker_socket, containerd_socket) else sock_orig(p),
    )
    monkeypatch.setattr(
        mod.shutil, "disk_usage",
        lambda p: SimpleNamespace(
            free=96 * mod.GIB if str(p).startswith(str(lab)) else 23 * mod.GIB
        ),
    )
    return SimpleNamespace(
        lab=lab,
        docker=docker,
        containerd=containerd,
        dockerd_cfg=dockerd_cfg,
        containerd_cfg=containerd_cfg,
        docker_socket=docker_socket,
        unit=unit,
    )


def test_isolated_lab_measures_own_vault_not_undersized_production(isolated) -> None:
    result = mod.measure_isolated_lab_free_space()
    assert result["runtime_role"] == "fr09-isolated-lab"
    assert result["lab_identity_verified"] is True
    assert result["runtime_fs_separate_from_production"] is True
    assert result["runtime_min_free_bytes"] == 96 * mod.GIB
    assert result["production_runtime_min_free_bytes"] == 23 * mod.GIB
    assert result["measurement_paths"] == [str(isolated.docker), str(isolated.containerd)]


def test_unaccepted_fr08_keeps_real_workload_held_despite_valid_lab(isolated) -> None:
    measured = mod.measure_isolated_lab_free_space()
    preflight = mod.build_preflight(
        profile(), fr08_accepted=False, free_bytes=96 * mod.GIB,
        heavy_min_free_bytes=40 * mod.GIB, measured_storage=measured,
    )
    ex = preflight["execution"]
    assert ex["blockers"] == ["FR-08 dependency is not accepted"]
    assert ex["heavy_work_permitted"] is False
    assert ex["load_test_started"] is False
    assert ex["load_test_authorized"] is False
    assert ex["production_targeted"] is False


def test_even_clean_lab_and_fr08_does_not_authorize_load_test(isolated) -> None:
    measured = mod.measure_isolated_lab_free_space()
    preflight = mod.build_preflight(
        profile(), fr08_accepted=True, free_bytes=96 * mod.GIB,
        heavy_min_free_bytes=40 * mod.GIB, measured_storage=measured,
    )
    assert preflight["execution"]["blockers"] == []
    assert preflight["execution"]["heavy_work_permitted"] is True
    assert preflight["execution"]["load_test_authorized"] is False
    assert preflight["execution"]["load_test_started"] is False


@pytest.mark.parametrize("weakened", [
    {"runtime_fs_separate_from_production": False},
    {"lab_identity_verified": False},
    {"docker_containerd_share_filesystem": False},
])
def test_isolated_lab_malformed_attestation_is_rejected(isolated, weakened) -> None:
    measured = mod.measure_isolated_lab_free_space()
    measured.update(weakened)
    preflight = mod.build_preflight(
        profile(), fr08_accepted=True, free_bytes=96 * mod.GIB,
        heavy_min_free_bytes=40 * mod.GIB, measured_storage=measured,
    )
    assert not preflight["execution"]["heavy_work_permitted"]
    assert "FR09 isolated lab identity is not verified" in preflight["execution"]["blockers"]


def test_root_or_production_mount_alias_is_rejected(monkeypatch, isolated) -> None:
    monkeypatch.setattr(mod, "_fs_device", lambda path: 2)
    with pytest.raises(mod.CapacityProfileError, match="separate from root and production"):
        mod.measure_isolated_lab_free_space()


def test_invalid_docker_network_config_is_rejected(isolated) -> None:
    cfg = json.loads(isolated.dockerd_cfg.read_text())
    cfg["bridge"] = "docker0"
    isolated.dockerd_cfg.write_text(json.dumps(cfg))
    with pytest.raises(mod.CapacityProfileError, match="configuration is not pinned"):
        mod.measure_isolated_lab_free_space()


def test_mismatched_containerd_address_unit_is_rejected(isolated) -> None:
    isolated.unit.write_text("ExecStart=/usr/bin/containerd --address /run/elsewhere.sock")
    with pytest.raises(mod.CapacityProfileError, match="configuration is not pinned"):
        mod.measure_isolated_lab_free_space()


def test_symlink_escape_from_luks_mount_is_rejected(isolated, tmp_path: Path) -> None:
    isolated.docker.rmdir()
    isolated.docker.symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(mod.CapacityProfileError, match="missing or redirected"):
        mod.measure_isolated_lab_free_space()


def test_low_isolated_runtime_space_still_blocks_40_gib_floor(monkeypatch, isolated) -> None:
    monkeypatch.setattr(
        mod.shutil, "disk_usage",
        lambda p: SimpleNamespace(
            free=39 * mod.GIB if str(p).startswith(str(isolated.lab)) else 96 * mod.GIB
        ),
    )
    measured = mod.measure_isolated_lab_free_space()
    preflight = mod.build_preflight(
        profile(), fr08_accepted=True, free_bytes=96 * mod.GIB,
        heavy_min_free_bytes=40 * mod.GIB, measured_storage=measured,
    )
    assert preflight["execution"]["load_test_authorized"] is False
    assert not preflight["execution"]["heavy_work_permitted"]
    assert "Docker/containerd runtime free space is below the heavy-work gate" in preflight["execution"]["blockers"]


def test_missing_encrypted_mount_never_implicitly_passes(monkeypatch, isolated) -> None:
    def missing(path: Path) -> None:
        raise mod.CapacityProfileError("FR09 isolated lab mount is missing or redirected")
    monkeypatch.setattr(mod, "_verified_luks_lab_mount", missing)
    with pytest.raises(mod.CapacityProfileError, match="mount is missing"):
        mod.measure_isolated_lab_free_space()


def test_default_cli_stays_on_production_runtime(monkeypatch, isolated, tmp_path: Path, capsys) -> None:
    def must_not_use_lab():
        raise AssertionError("isolated lab must be opt-in")
    monkeypatch.setattr(mod, "measure_isolated_lab_free_space", must_not_use_lab)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(json.loads((ROOT/"docs/project/PLAN.json").read_text())))
    monkeypatch.setattr(
        sys, "argv",
        [str(SOURCE), "--plan", str(plan), "--free-bytes", str(96 * mod.GIB)],
    )
    assert mod.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["execution"]["measured_runtime_storage"]["runtime_min_free_bytes"] == 23 * mod.GIB
    assert receipt["execution"]["load_test_started"] is False


def test_explicit_isolated_cli_measures_96_gib_but_holds_fr08(monkeypatch, isolated, tmp_path: Path, capsys) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(json.loads((ROOT/"docs/project/PLAN.json").read_text())))
    monkeypatch.setattr(
        sys, "argv",
        [str(SOURCE), "--plan", str(plan), "--free-bytes", str(96 * mod.GIB),
         "--runtime-layout", "isolated-lab"],
    )
    assert mod.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    measured = receipt["execution"]["measured_runtime_storage"]
    assert measured["runtime_role"] == "fr09-isolated-lab"
    assert measured["runtime_min_free_bytes"] == 96 * mod.GIB
    assert receipt["execution"]["blockers"] == ["FR-08 dependency is not accepted"]
    assert receipt["execution"]["load_test_authorized"] is False


def test_40_gib_floor_cannot_be_weakened_on_isolated_layout(isolated) -> None:
    preflight = mod.build_preflight(
        profile(), fr08_accepted=True, free_bytes=96 * mod.GIB,
        heavy_min_free_bytes=39 * mod.GIB,
        measured_storage=mod.measure_isolated_lab_free_space(),
    )
    assert "heavy-work minimum free space cannot be weakened below 40 GiB" in preflight["execution"]["blockers"]
    assert not preflight["execution"]["load_test_authorized"]
