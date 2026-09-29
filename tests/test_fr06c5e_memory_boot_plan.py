"""Enabled boot graph tests using systemd-analyze on an owned offline root.

The verifier constructs a transaction only. No unit is installed, started,
stopped, mounted or enabled on the real host. Fixture executables are not run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_boot_plan", ROOT / "scripts/security/fr06c5_memory_boot_plan.py"
)
assert SPEC and SPEC.loader
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)
SWAP_NAME = "aionex-fr06c5-encrypted-swap.service"


def _tree(
    root: Path, *, corrected: bool, split_mounts: bool, tmpfs_backing: bool = False
) -> Path:
    unitdir = root / "etc/systemd/system"
    unitdir.mkdir(parents=True)
    fixtures = ROOT / "tests/fixtures/fr06c5e"
    units = {
        "default.target": "[Unit]\nDescription=Owned test transaction\nDefaultDependencies=no\nRequires=local-fs.target swap.target\n",
        "local-fs.target": "[Unit]\nDescription=Local filesystems\nDefaultDependencies=no\n",
        "swap.target": "[Unit]\nDescription=Swap\nDefaultDependencies=no\n",
        "local-fs-pre.target": "[Unit]\nDefaultDependencies=no\n",
        "shutdown.target": "[Unit]\nDefaultDependencies=no\n",
        "umount.target": "[Unit]\nDefaultDependencies=no\n",
        "sysinit.target": "[Unit]\nDefaultDependencies=no\n",
        "basic.target": "[Unit]\nDefaultDependencies=no\n",
        "-.slice": "[Slice]\n",
        "system.slice": "[Unit]\nDefaultDependencies=no\n[Slice]\n",
        "systemd-remount-fs.service": "[Unit]\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/bin/true\n",
        "-.mount": "[Unit]\nDefaultDependencies=no\n[Mount]\nWhat=/dev/root\nWhere=/\nType=ext4\n",
        SWAP_NAME: boot.SWAP_UNIT
        if corrected
        else (fixtures / "prepared-swap.service").read_text(),
        "tmp.mount": boot.TMP_UNIT
        if corrected
        else (fixtures / "tmp.mount").read_text(),
    }
    for directory in [
        "bin",
        "usr/bin",
        "opt/AIOS/scripts/security",
        "var/lib/aionex/fr06-vaults",
        "var/lib/aionex/fr06c5-memory-controls",
        "tmp",
    ]:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for executable in ["bin/true", "usr/bin/python3"]:
        path = root / executable
        path.write_text(
            "#!/bin/sh\n# Only an executable metadata fixture; never run.\nexit 0\n"
        )
        path.chmod(0o755)
    if split_mounts or tmpfs_backing:
        for path in ["/usr", "/var", "/opt"] if split_mounts else ["/var"]:
            name = path[1:] + ".mount"
            filesystem = "tmpfs" if tmpfs_backing and path == "/var" else "ext4"
            what = "tmpfs" if filesystem == "tmpfs" else "/dev/fixture-" + path[1:]
            units[name] = (
                f"[Unit]\nDescription=Owned fixture mount\n[Mount]\nWhat={what}\nWhere={path}\nType={filesystem}\n"
            )
    for name, content in units.items():
        (unitdir / name).write_text(content)
    for link, target in boot.proposal()["enabled_links"].items():
        destination = unitdir / link
        destination.parent.mkdir(exist_ok=True)
        destination.symlink_to(target)
    if split_mounts or tmpfs_backing:
        for name in units:
            if name in {"usr.mount", "var.mount", "opt.mount"}:
                (unitdir / "local-fs.target.wants" / name).symlink_to("../" + name)
    return unitdir


def _verify(root: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("systemd-analyze")
    if executable is None:
        pytest.fail("systemd-analyze required for actual enabled-graph acceptance")
    return subprocess.run(
        [
            executable,
            "--root=" + str(root),
            "--man=no",
            "--generators=no",
            "verify",
            "default.target",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "SYSTEMD_LOG_LEVEL": "warning", "LC_ALL": "C"},
    )


def test_prepared_enabled_units_reproduce_ordering_cycle(tmp_path):
    _tree(tmp_path, corrected=False, split_mounts=False)
    result = _verify(tmp_path)
    with pytest.raises(boot.BootGraphRejected):
        boot.accept_offline_verification(
            result.returncode, result.stdout, result.stderr
        )
    assert "cycle" in (result.stdout + result.stderr).lower(), (
        result.stdout + result.stderr
    )


@pytest.mark.parametrize("split_mounts", [False, True])
def test_corrected_enabled_graph_is_accepted_by_actual_systemd(tmp_path, split_mounts):
    _tree(tmp_path, corrected=True, split_mounts=split_mounts)
    result = _verify(tmp_path)
    assert (
        boot.accept_offline_verification(
            result.returncode, result.stdout, result.stderr
        )["offline_graph_accepted"]
        is True
    )


def test_tmpfs_backing_dependency_is_rejected_not_hidden(tmp_path):
    _tree(tmp_path, corrected=True, split_mounts=False, tmpfs_backing=True)
    result = _verify(tmp_path)
    with pytest.raises(boot.BootGraphRejected):
        boot.accept_offline_verification(
            result.returncode, result.stdout, result.stderr
        )
    assert "cycle" in (result.stdout + result.stderr).lower(), (
        result.stdout + result.stderr
    )


def test_proposal_retains_partial_scope_and_does_not_install():
    plan = boot.proposal()
    assert plan["prepared_source_commit"] == "13b76558f585f432acc831b6ad0448ee5909b5bd"
    assert (
        plan["activation_authorized"] is False
        and plan["real_host_dependency_graph_verified"] is False
    )
    assert plan["operator_integrated_in_main"] is False
    assert "After=local-fs.target" not in boot.SWAP_UNIT
    assert "RequiresMountsFor=" in boot.SWAP_UNIT
    assert "Requires=" + SWAP_NAME in boot.TMP_UNIT
    assert "size=8G" in boot.TMP_UNIT and "mode=1777,nodev,nosuid" in boot.TMP_UNIT
    assert len(plan["remaining_prerequisites"]) == 4
    json.dumps(plan)


@pytest.mark.parametrize(
    "code,out,err",
    [
        (0, "", "Job deleted to break ordering cycle"),
        (0, "warning", ""),
        (1, "", ""),
        (True, "", ""),
    ],
)
def test_zero_exit_with_diagnostics_is_not_graph_acceptance(code, out, err):
    with pytest.raises(boot.BootGraphRejected):
        boot.accept_offline_verification(code, out, err)
