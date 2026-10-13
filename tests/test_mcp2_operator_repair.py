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
    monkeypatch.delenv("AIONEX_MCP_INSTANCE", raising=False)
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



def test_new_instance_targets_only_the_independent_new_tunnel(operator, monkeypatch):
    monkeypatch.setenv("AIONEX_MCP_INSTANCE", "new")
    spec = importlib.util.spec_from_file_location("aionex_new_operator_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # CI does not have the production filesystem: mock presence, never assert
    # actual /opt/AIOS contents on the isolated test runner.
    monkeypatch.setattr(
        module, "_probe_file",
        lambda path: path == Path("/opt/AIOS/ops/mcp2/server.py"),
    )

    status = module.server_status()
    assert status["runtime_instance"] == "new"
    assert status["mcp_server_path"] == "/opt/AIOS/ops/mcp2/server.py"
    assert status["mcp_server_exists"] is True
    assert status["tunnel_profile"] == "aionex-new"
    assert status["tunnel_service"] == "aionex-new-mcp-tunnel.service"
    assert set(module.mcp.tools) == EXPECTED_TOOLS

    run = Mock(return_value={"exit_code": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(module, "_run", run)
    result = module.mcp_restart_tunnel()
    assert run.call_args.args[0] == [
        "systemctl", "--no-block", "restart", "aionex-new-mcp-tunnel.service"
    ]
    assert result["success"] is True
    assert result["verification_required"] is True


def test_unsupported_mcp_runtime_instance_is_fail_closed(operator, monkeypatch):
    monkeypatch.setenv("AIONEX_MCP_INSTANCE", "untrusted-path")
    spec = importlib.util.spec_from_file_location("unknown_mcp_operator_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(RuntimeError, match="Unsupported AIONEX MCP runtime instance"):
        spec.loader.exec_module(module)

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


def test_timeout_accepts_partial_bytes_and_redacts(operator, tmp_path):
    # Real timeout plumbing rather than mocking the removed subprocess.run call.
    payload = "synthetic-sensitive-marker"
    program = "import time;print('password=' + " + repr(payload) + ",flush=True);time.sleep(5)"
    result = operator._run([sys.executable, "-c", program], cwd=tmp_path, timeout_seconds=1)
    assert result["exit_code"] == 124
    assert payload not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]
    assert result["outcome"] == "unknown" and result["automatic_retry"] is False


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


def test_status_permission_denied_is_unknown_not_missing(operator, monkeypatch):
    monkeypatch.setattr(Path, "is_file", Mock(side_effect=PermissionError("denied")))
    status = operator.server_status()
    assert status["status"] == "online"
    assert status["runtime_key_exists"] is None
    assert status["deploy_key_exists"] is None
    assert status["mcp_server_exists"] is None


@pytest.mark.parametrize("template", [
    "--token {value}", "--token={value}", '--token "{value}"',
    "--api-key {value}", "--password {value}", "--access-token {value}",
    '\"token\": \"{value}\"', '\"client_secret\": \"{value}\"',
    '\"api_key\": \"{value}\"', '\"access_token\": \"{value}\"',
])
def test_command_and_json_credentials_are_redacted(operator, template):
    secret_value = "synthetic-credential-for-redaction-test"
    output = operator._safe_output(template.format(value=secret_value))
    assert secret_value not in output
    assert "[REDACTED]" in output


def test_redaction_preserves_operator_metadata(operator):
    output = operator._safe_output('project_root=/opt/AIOS; token_count=28; status=online')
    assert 'project_root=/opt/AIOS' in output
    assert 'token_count=28' in output
    assert 'status=online' in output

def _synthetic_private_key(tmp_path: Path, filename: str) -> Path:
    """Generate disposable test-only material; never read a real operator key."""
    identity = tmp_path / filename
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(identity)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=10,
    )
    identity.chmod(0o600)
    return identity


def test_empty_legacy_key_does_not_count_as_deploy_identity(operator, tmp_path):
    placeholder = tmp_path / "legacy-deploy"
    placeholder.touch(mode=0o600)
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(operator, "MCP_INSTANCE", "legacy")
        monkeypatch.setattr(operator, "DEPLOY_KEY", placeholder)
        assert operator._private_deploy_key_status(placeholder) is False
        assert operator._selected_deploy_key() is None
        assert operator._deploy_key_presence() is False
        monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /injected/credential")
        assert "GIT_SSH_COMMAND" not in operator._git_env()
    finally:
        monkeypatch.undo()


def test_nonempty_invalid_key_is_rejected_by_real_ssh_parser(operator, tmp_path):
    fake = tmp_path / "invalid-openssh"
    fake.write_bytes(b"x" * 420)
    fake.chmod(0o600)
    assert operator._root_owned_private_file_status(fake) is True
    assert operator._private_deploy_key_status(fake) is False


def test_key_permissions_symlinks_and_hardlinks_fail_closed(operator, tmp_path):
    identity = _synthetic_private_key(tmp_path, "isolated-test-key")
    assert operator._private_deploy_key_status(identity) is True
    identity.chmod(0o644)
    assert operator._private_deploy_key_status(identity) is False
    identity.chmod(0o600)
    link = tmp_path / "key-symlink"
    link.symlink_to(identity)
    assert operator._private_deploy_key_status(link) is False
    import os
    other = tmp_path / "key-hardlink"
    os.link(identity, other)
    assert operator._private_deploy_key_status(identity) is False


def test_new_instance_uses_valid_vault_identity_and_pinned_known_hosts(
    operator, monkeypatch, tmp_path
):
    identity = _synthetic_private_key(tmp_path, "vault-test-identity")
    empty = tmp_path / "empty-legacy"
    empty.touch(mode=0o600)
    hosts = tmp_path / "pinned-hosts"
    hosts.write_bytes(b"github.com ssh-ed25519 " + b"A" * 90 + b"\n")
    hosts.chmod(0o600)
    monkeypatch.setattr(operator, "MCP_INSTANCE", "new")
    monkeypatch.setattr(operator, "VAULT_DEPLOY_KEY", identity)
    monkeypatch.setattr(operator, "DEPLOY_KEY", empty)
    monkeypatch.setattr(operator, "PINNED_GITHUB_KNOWN_HOSTS", hosts)
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /injected/key")
    assert operator._selected_deploy_key() == identity
    assert operator._deploy_key_presence() is True
    command = operator._git_env()["GIT_SSH_COMMAND"]
    assert str(identity) in command
    assert str(hosts) in command
    assert "StrictHostKeyChecking=yes" in command
    assert "IdentitiesOnly=yes" in command
    assert "BatchMode=yes" in command
    assert "accept-new" not in command
    assert "/injected/key" not in command


def test_new_instance_never_uses_legacy_key_without_host_pin(
    operator, monkeypatch, tmp_path
):
    legacy = _synthetic_private_key(tmp_path, "valid-fallback-but-unpinned")
    missing = tmp_path / "missing-host-pin"
    monkeypatch.setattr(operator, "MCP_INSTANCE", "new")
    monkeypatch.setattr(operator, "VAULT_DEPLOY_KEY", tmp_path / "missing-vault")
    monkeypatch.setattr(operator, "DEPLOY_KEY", legacy)
    monkeypatch.setattr(operator, "PINNED_GITHUB_KNOWN_HOSTS", missing)
    assert operator._deploy_key_presence() is True
    assert operator._selected_deploy_key() is None
    assert "GIT_SSH_COMMAND" not in operator._git_env()


def test_legacy_instance_preserves_authenticated_legacy_ssh_routing(
    operator, monkeypatch, tmp_path
):
    legacy = _synthetic_private_key(tmp_path, "synthetic-legacy")
    monkeypatch.setattr(operator, "MCP_INSTANCE", "legacy")
    monkeypatch.setattr(operator, "DEPLOY_KEY", legacy)
    assert operator._selected_deploy_key() == legacy
    assert "StrictHostKeyChecking=accept-new" in operator._git_env()["GIT_SSH_COMMAND"]
