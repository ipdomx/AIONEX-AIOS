"""FR-02 part 2: reporting is independent of sensitive command argv.

All execution is mocked. These tests do not connect to or deploy any host.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "fr02_summary_deployment", ROOT / "scripts/phase24b/deploy_inventory.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    marker = "synthetic-private-summary-marker"
    control = module.InventoryTarget("control-plane", marker + "-control", marker + "@control.example", tmp_path / marker)
    hosts = tuple(
        module.InventoryTarget("agent", marker + str(i), marker + f"@host{i}.example", tmp_path / marker)
        for i in range(3)
    )
    monkeypatch.setattr(module, "load_inventory", Mock(return_value=(control, hosts)))
    monkeypatch.setattr(module, "source_archive", Mock())
    process = Mock(return_value=subprocess.CompletedProcess([], 0, marker, marker))
    monkeypatch.setattr(module, "run", process)
    monkeypatch.setattr(sys, "argv", [
        "deploy_inventory.py", "--inventory", str(tmp_path / "inventory.json"),
        "--bundle-root", str(tmp_path), "--project-root", str(tmp_path),
    ])
    return module, process, marker


@pytest.mark.parametrize("apply", [False, True])
def test_cli_public_summary_has_correct_counts_without_private_arguments(deployment, monkeypatch, capsys, apply):
    module, process, marker = deployment
    if apply:
        monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    assert module.main() == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    expected = ["ssh", "scp", "scp", "scp", "ssh"] + ["ssh", "scp", "scp", "ssh"] * 3
    assert report == {
        "mode": "apply" if apply else "dry-run",
        "targets": ["control-plane", "agent", "agent", "agent"],
        "commands": [{"sequence": i + 1, "transport": kind} for i, kind in enumerate(expected)],
        "command_count": 17,
        "command_arguments_omitted": True,
        "remote_targets_modified": apply,
        "production_modified": False,
    }
    assert marker not in captured.out + captured.err
    assert "host-secrets" not in captured.out + captured.err
    assert "sudo" not in captured.out + captured.err
    assert process.call_count == (17 if apply else 0)
    if apply:
        for call in process.call_args_list:
            assert "StrictHostKeyChecking=yes" in call.args[0]
            assert "BatchMode=yes" in call.args[0]


@pytest.mark.parametrize("apply", [False, True])
def test_builder_return_values_cannot_flow_into_summary(deployment, monkeypatch, capsys, apply):
    module, process, marker = deployment
    # A regression to inspecting even argv[0] would leak this synthetic marker.
    monkeypatch.setattr(module, "ssh", Mock(return_value=[marker, marker]))
    monkeypatch.setattr(module, "scp", Mock(return_value=[marker, marker]))
    if apply:
        monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    assert module.main() == 0
    output = capsys.readouterr().out
    assert marker not in output
    report = json.loads(output)
    assert report["command_count"] == 17
    assert {c["transport"] for c in report["commands"]} == {"ssh", "scp"}
    process.assert_not_called()


def test_failed_execution_does_not_print_success_summary(deployment, monkeypatch, capsys):
    module, process, _ = deployment
    process.side_effect = RuntimeError("isolated failure; no execution occurred")
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    with pytest.raises(RuntimeError, match="isolated failure"):
        module.main()
    assert capsys.readouterr().out == ""
    assert process.call_count == 1
