"""Offline regression tests for the project-specific operator; no provider calls."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "ops/mcp2/server.py"
EXPECTED_TOOLS = {
    "server_status", "run_command", "file_status", "list_directory", "read_file",
    "write_file", "append_file", "make_directory", "copy_path", "move_path",
    "delete_path", "chmod_path", "chown_path", "download_file", "git_status",
    "git_command", "github_command", "docker_command", "run_pytest",
    "runpod_endpoint_status", "runpod_delete_endpoint", "runpod_purge_queue",
    "runpod_submit_image", "runpod_job_status", "runpod_cancel_job",
    "runpod_wait_job", "mcp_install_update", "mcp_restart_tunnel",
}


@pytest.fixture
def operator(monkeypatch):
    class FakeMCP:
        def __init__(self, name):
            self.tools = {}

        def tool(self):
            def register(fn):
                self.tools[fn.__name__] = fn
                return fn
            return register

    fake = types.ModuleType("fastmcp")
    fake.FastMCP = FakeMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake)
    spec = importlib.util.spec_from_file_location("mcp2_operator_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_existing_tool_contract(operator):
    assert set(operator.mcp.tools) == EXPECTED_TOOLS
    assert len(operator.mcp.tools) == 28


def test_fixed_project_and_canonical_report(operator):
    assert operator.PROJECT_ROOT == Path("/opt/AIOS")
    assert operator.PROJECT_REPORT == Path("/opt/AIOS/docs/project/PROJECT-REPORT.md")
    assert operator.server_status()["version"] == "2026.09.10.1"


@pytest.mark.parametrize("name", [
    "run_command", "list_directory", "git_status", "git_command",
    "github_command", "docker_command", "run_pytest",
])
def test_all_public_defaults_point_to_production(name):
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    defaults = dict(zip([a.arg for a in node.args.args][-len(node.args.defaults):], node.args.defaults))
    assert ast.literal_eval(defaults["path" if name == "list_directory" else "cwd"]) == "/opt/AIOS"


def test_relative_paths_do_not_depend_on_tunnel_workdir(operator):
    assert operator._path("docs/project") == Path("/opt/AIOS/docs/project")
    assert operator._path("/tmp/explicit") == Path("/tmp/explicit")


def test_no_dynamic_backup_selection_or_legacy_cloud_mutations():
    text = SOURCE.read_text()
    assert "MCP2_PHASE33_WRAPPER" not in text
    assert "__phase33_create__" not in text
    assert "__phase33_patch_template__" not in text
    assert ".glob(" not in text
    assert "exec(compile(" not in text
    assert "pkill" not in text


@pytest.mark.parametrize("tool,method,suffix", [
    ("runpod_delete_endpoint", "DELETE", "endpoints/example"),
    ("runpod_purge_queue", "POST", "example/purge-queue"),
])
def test_cloud_mutation_names_have_only_the_documented_semantics(operator, monkeypatch, tool, method, suffix):
    request = Mock(return_value={"http_status": 204})
    monkeypatch.setattr(operator, "_runpod_request", request)
    getattr(operator, tool)("example")
    args = request.call_args.args
    assert args[0] == method
    assert args[1].endswith(suffix)
    assert request.call_count == 1


def test_restart_targets_only_own_systemd_service(operator, monkeypatch):
    run = Mock(return_value={"exit_code": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(operator, "_run", run)
    result = operator.mcp_restart_tunnel()
    assert run.call_args.args[0] == [
        "systemctl", "--no-block", "restart", "aionex-phase22c-2-tunnel.service"
    ]
    assert result["success"] is True
    assert result["verification_required"] is True
    assert result["status"] == "restart-requested"


def test_restart_error_never_claims_success(operator, monkeypatch):
    monkeypatch.setattr(operator, "_run", Mock(return_value={"exit_code": 1, "stdout": "", "stderr": "denied"}))
    assert operator.mcp_restart_tunnel()["success"] is False


def test_timeout_accepts_partial_bytes_and_redacts(operator, monkeypatch, tmp_path):
    error = subprocess.TimeoutExpired(["example"], 1, output=b"password=private-test-value")
    monkeypatch.setattr(operator.subprocess, "run", Mock(side_effect=error))
    result = operator._run(["example"], cwd=tmp_path, timeout_seconds=1)
    assert result["exit_code"] == 124
    assert "private-test-value" not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]


def test_atomic_update_compiles_from_valid_root(operator, monkeypatch, tmp_path):
    installed = tmp_path / "server.py"
    installed.write_text("old = True\n")
    candidate = tmp_path / "candidate.py"
    candidate.write_text("new = True\n")
    monkeypatch.setattr(operator, "MCP_SERVER_PATH", installed)
    monkeypatch.setattr(operator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(operator, "PYTHON_BIN", Path(sys.executable))
    result = operator.mcp_install_update(str(candidate))
    assert result["success"] is True
    assert installed.read_text() == "new = True\n"
    assert Path(result["backup"]).read_text() == "old = True\n"
    assert installed.stat().st_mode & 0o777 == 0o600


def test_bad_update_preserves_working_server(operator, monkeypatch, tmp_path):
    installed = tmp_path / "server.py"
    installed.write_text("old = True\n")
    candidate = tmp_path / "candidate.py"
    candidate.write_text("invalid python ?\n")
    monkeypatch.setattr(operator, "MCP_SERVER_PATH", installed)
    monkeypatch.setattr(operator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(operator, "PYTHON_BIN", Path(sys.executable))
    result = operator.mcp_install_update(str(candidate))
    assert result["success"] is False
    assert installed.read_text() == "old = True\n"


def test_safe_write_and_read_keep_secret_redaction(operator, tmp_path):
    path = tmp_path / "sample.txt"
    operator.write_file(str(path), "api_key=private-test-value", mode="0600")
    result = operator.read_file(str(path))
    assert "private-test-value" not in result["content"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_pytest_runs_as_module_to_keep_project_imports(operator, monkeypatch):
    run = Mock(return_value={"exit_code": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(operator, "_run", run)
    operator.run_pytest("tests/test_example.py")
    assert run.call_args.args[0][1:] == ["-m", "pytest", "-q", "tests/test_example.py"]
    assert run.call_args.kwargs["cwd"] == "/opt/AIOS"
