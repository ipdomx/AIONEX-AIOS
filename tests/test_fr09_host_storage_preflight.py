"""Offline regression for independent NEW-host encrypted runtime space preflight."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/capacity/fr09_host_storage_preflight.py"
SPEC = importlib.util.spec_from_file_location("fr09_host_storage_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def snapshot(*, host: str = "nc-ph-4354", root_free_gib: int = 3000,
             vault_free_gib: int = 23, vault_mounted: bool = True,
             vault_device: int = 2, containerd_device: int = 2) -> dict:
    def row(free_gib: int, device: int, mounted: bool = True) -> dict:
        return {
            "total_bytes": max(64, free_gib + 1) * gate.GIB,
            "free_bytes": free_gib * gate.GIB,
            "device_id": device,
            "mountpoint": mounted,
        }

    return {
        "hostname": host,
        "filesystems": {
            "root": row(root_free_gib, 1),
            "docker": row(vault_free_gib, vault_device, vault_mounted),
            "containerd": row(vault_free_gib, containerd_device, vault_mounted),
        },
    }


def test_3tb_root_space_never_conceals_23g_runtime_vault() -> None:
    result = gate.evaluate_storage(snapshot())
    assert result["status"] == "HOLD_STORAGE"
    assert "encrypted Docker/containerd vault free space is below the capacity gate" in result["blockers"]
    assert result["load_test_authorized"] is False


def test_only_storage_is_certified_even_when_free_space_passes() -> None:
    result = gate.evaluate_storage(snapshot(vault_free_gib=45))
    assert result["status"] == "STORAGE_PRECHECK_PASS"
    assert result["fr08_runtime_accepted"] is False
    assert result["isolated_lab_verified"] is False
    assert result["load_test_authorized"] is False
    assert result["load_test_started"] is False


def test_unmounted_runtime_vault_is_a_hard_hold() -> None:
    result = gate.evaluate_storage(snapshot(vault_free_gib=60, vault_mounted=False))
    assert result["status"] == "HOLD_STORAGE"
    assert "encrypted runtime mountpoint is not mounted" in result["blockers"]


def test_shared_root_storage_and_unreviewed_split_runtime_are_rejected() -> None:
    assert gate.evaluate_storage(snapshot(vault_free_gib=50, vault_device=1))["status"] == "HOLD_STORAGE"
    assert gate.evaluate_storage(snapshot(vault_free_gib=50, containerd_device=3))["status"] == "HOLD_STORAGE"


def test_old_host_and_invalid_data_never_open_gate() -> None:
    assert gate.evaluate_storage(snapshot(host="nc-ph-4862", vault_free_gib=50))["status"] == "HOLD_STORAGE"
    bad = snapshot(vault_free_gib=50)
    bad["filesystems"]["docker"]["free_bytes"] = True
    assert gate.evaluate_storage(bad)["status"] == "HOLD_STORAGE"


def test_cli_offline_does_not_accept_weakened_space_limit() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--minimum-free-gib", "23"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "between 40 and 1024" in result.stderr


def test_kernel_observation_paths_remain_fixed_and_no_test_starts() -> None:
    assert gate.FILESYSTEMS == {
        "root": "/", "docker": "/var/lib/docker", "containerd": "/var/lib/containerd",
    }
    source = SCRIPT.read_text(encoding="utf-8")
    assert "shutil.disk_usage(path)" in source
    assert "os.path.ismount(path)" in source
    assert "docker compose up" not in source
    assert "subprocess.run" not in source
