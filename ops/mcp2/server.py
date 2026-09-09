from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastmcp import FastMCP


mcp = FastMCP("AIONEX General Server Operator")

PROJECT_ROOT = Path("/opt/AIOS")
MCP_SERVER_PATH = Path("/opt/AIOS/tools/aionex_phase22c_mcp2.py")
TUNNEL_PROFILE = "aionex-phase22c-2"
TUNNEL_SERVICE = "aionex-phase22c-2-tunnel.service"
SERVER_VERSION = "2026.09.10.1"
PROJECT_REPORT = PROJECT_ROOT / "docs/project/PROJECT-REPORT.md"
TUNNEL_RUNTIME_KEY = Path("/root/.config/aionex/aionex-tunnel-runtime.key")
TUNNEL_LOG = Path("/var/log/aionex-phase22c-tunnel.log")
DEPLOY_KEY = Path("/root/.ssh/aionex_aios_deploy")
PYTHON_BIN = Path("/opt/AIOS/.venv/bin/python")
RUNPOD_ENV = Path("/opt/AIOS/web-dashboard/secrets/RUNPOD_GPU.env")
MAX_OUTPUT_CHARS = 240_000


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{12,}\b"),
    re.compile(r"(?i)((?:api[_-]?key|token|password)\s*[=:]\s*)[^\s\"']+"),
)


def _redact(text: str) -> str:
    value = text
    value = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", value)
    value = _SECRET_PATTERNS[1].sub("[REDACTED]", value)
    value = _SECRET_PATTERNS[2].sub("[REDACTED]", value)
    value = _SECRET_PATTERNS[3].sub(r"\1[REDACTED]", value)
    return value


def _safe_output(text: str | bytes) -> str:
    decoded = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
    value = _redact(decoded)
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + f"\n...[TRUNCATED {len(value) - MAX_OUTPUT_CHARS} CHARS]"


def _path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _cwd(value: str | Path) -> Path:
    directory = _path(value)
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))
    return directory


def _run(args: list[str], *, cwd: str | Path = PROJECT_ROOT, timeout_seconds: int = 120, env: dict[str, str] | None = None) -> dict[str, Any]:
    timeout = max(1, min(int(timeout_seconds), 1800))
    try:
        completed = subprocess.run(args, cwd=str(_cwd(cwd)), env=env or os.environ.copy(), text=True, capture_output=True, timeout=timeout, check=False)
        return {"exit_code": completed.returncode, "stdout": _safe_output(completed.stdout), "stderr": _safe_output(completed.stderr)}
    except subprocess.TimeoutExpired as exc:
        return {"exit_code": 124, "stdout": _safe_output(exc.stdout or ""), "stderr": f"command timed out after {timeout} seconds"}


def _shell(command: str, *, cwd: str | Path = PROJECT_ROOT, timeout_seconds: int = 120, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not command.strip():
        raise ValueError("command is required")
    return _run(["/bin/bash", "-lc", command], cwd=cwd, timeout_seconds=timeout_seconds, env=env)


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    if DEPLOY_KEY.is_file():
        env["GIT_SSH_COMMAND"] = f"ssh -i {shlex.quote(str(DEPLOY_KEY))} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    return env


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _runpod_key() -> str:
    key = _load_env_file(RUNPOD_ENV).get("RUNPOD_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RUNPOD_API_KEY is missing")
    return key


def _runpod_request(method: str, url: str, body: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {_runpod_key()}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=max(1, min(int(timeout), 600))) as response:
            raw = response.read()
            payload = json.loads(raw.decode()) if raw else {}
            return {"http_status": response.status, "data": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return {"http_status": exc.code, "error": _safe_output(raw[:4000])}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"http_status": None, "error": type(exc).__name__}


def _safe_endpoint(data: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "name", "templateId", "workersMin", "workersMax", "workersStandby", "idleTimeout", "executionTimeoutMs", "gpuCount", "gpuTypeIds", "networkVolumeId", "networkVolumeIds", "scalerType", "scalerValue")
    return {k: data.get(k) for k in keys}


def _safe_job(data: dict[str, Any]) -> dict[str, Any]:
    result = {k: data.get(k) for k in ("id", "status", "delayTime", "executionTime", "error")}
    output = data.get("output")
    if isinstance(output, dict):
        result["output"] = {k: output.get(k) for k in ("filename", "content_type", "size_bytes")}
    return result


def _probe_file(path: Path) -> bool | None:
    """Report unknown rather than crash or claim missing on denied metadata."""
    try:
        return path.is_file()
    except OSError:
        return None


@mcp.tool()
def server_status() -> dict[str, Any]:
    return {"status": "online", "purpose": "general-server-operator", "version": SERVER_VERSION, "canonical_report": str(PROJECT_REPORT), "tunnel_service": TUNNEL_SERVICE, "uid": os.getuid(), "euid": os.geteuid(), "project_root": str(PROJECT_ROOT), "project_exists": PROJECT_ROOT.is_dir(), "mcp_server_path": str(MCP_SERVER_PATH), "mcp_server_exists": _probe_file(MCP_SERVER_PATH), "tunnel_profile": TUNNEL_PROFILE, "runtime_key_exists": _probe_file(TUNNEL_RUNTIME_KEY), "deploy_key_exists": _probe_file(DEPLOY_KEY)}


@mcp.tool()
def run_command(command: str, cwd: str = "/opt/AIOS", timeout_seconds: int = 120) -> dict[str, Any]:
    return _shell(command, cwd=cwd, timeout_seconds=timeout_seconds)


@mcp.tool()
def file_status(path: str) -> dict[str, Any]:
    target = _path(path)
    if not target.exists() and not target.is_symlink():
        return {"exists": False, "path": str(target)}
    info = target.lstat()
    return {"exists": True, "path": str(target), "resolved_path": str(target.resolve(strict=False)), "is_file": target.is_file(), "is_directory": target.is_dir(), "is_symlink": target.is_symlink(), "size_bytes": info.st_size, "uid": info.st_uid, "gid": info.st_gid, "mode": oct(stat.S_IMODE(info.st_mode)), "modified_at": info.st_mtime}


@mcp.tool()
def list_directory(path: str = "/opt/AIOS", max_entries: int = 1000) -> dict[str, Any]:
    directory = _path(path)
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))
    limit = max(1, min(int(max_entries), 5000))
    entries: list[dict[str, Any]] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name.lower())[:limit]:
        try:
            info = child.lstat()
            entries.append({"name": child.name, "path": str(child), "type": "symlink" if child.is_symlink() else "directory" if child.is_dir() else "file" if child.is_file() else "other", "size_bytes": info.st_size, "mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid, "gid": info.st_gid})
        except OSError as exc:
            entries.append({"name": child.name, "path": str(child), "error": type(exc).__name__})
    return {"path": str(directory), "count": len(entries), "entries": entries}


@mcp.tool()
def read_file(path: str, max_chars: int = 200000) -> dict[str, Any]:
    target = _path(path)
    if not target.is_file():
        raise FileNotFoundError(str(target))
    limit = max(1, min(int(max_chars), 1_000_000))
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": str(target), "total_chars": len(content), "content": _safe_output(content[:limit]), "truncated": len(content) > limit}


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = True, create_parents: bool = True, mode: str = "0644") -> dict[str, Any]:
    target = _path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.mcp-tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.chmod(temporary, int(mode, 8))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"success": True, "path": str(target), "size_bytes": target.stat().st_size, "mode": oct(stat.S_IMODE(target.stat().st_mode))}


@mcp.tool()
def append_file(path: str, content: str, create_parents: bool = True) -> dict[str, Any]:
    target = _path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(content); stream.flush(); os.fsync(stream.fileno())
    return {"success": True, "path": str(target), "size_bytes": target.stat().st_size}


@mcp.tool()
def make_directory(path: str, parents: bool = True, mode: str = "0755") -> dict[str, Any]:
    target = _path(path); target.mkdir(parents=parents, exist_ok=True, mode=int(mode, 8)); return {"success": True, "path": str(target)}


@mcp.tool()
def copy_path(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    src, dst = _path(source), _path(destination)
    if not src.exists() and not src.is_symlink(): raise FileNotFoundError(str(src))
    if dst.exists() or dst.is_symlink():
        if not overwrite: raise FileExistsError(str(dst))
        shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True) if src.is_dir() and not src.is_symlink() else shutil.copy2(src, dst, follow_symlinks=False)
    return {"success": True, "source": str(src), "destination": str(dst)}


@mcp.tool()
def move_path(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    src, dst = _path(source), _path(destination)
    if not src.exists() and not src.is_symlink(): raise FileNotFoundError(str(src))
    if dst.exists() or dst.is_symlink():
        if not overwrite: raise FileExistsError(str(dst))
        shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(src), str(dst)); return {"success": True, "source": str(src), "destination": str(dst)}


@mcp.tool()
def delete_path(path: str, recursive: bool = False) -> dict[str, Any]:
    target = _path(path)
    if not target.exists() and not target.is_symlink(): return {"success": True, "deleted": False, "path": str(target)}
    if target.is_dir() and not target.is_symlink(): shutil.rmtree(target) if recursive else target.rmdir()
    else: target.unlink()
    return {"success": True, "deleted": True, "path": str(target)}


@mcp.tool()
def chmod_path(path: str, mode: str) -> dict[str, Any]:
    target = _path(path); os.chmod(target, int(mode, 8), follow_symlinks=False); return {"success": True, "path": str(target), "mode": oct(stat.S_IMODE(target.lstat().st_mode))}


@mcp.tool()
def chown_path(path: str, uid: int, gid: int) -> dict[str, Any]:
    target = _path(path); os.chown(target, int(uid), int(gid), follow_symlinks=False); info = target.lstat(); return {"success": True, "path": str(target), "uid": info.st_uid, "gid": info.st_gid}


@mcp.tool()
def download_file(url: str, destination: str, overwrite: bool = False, timeout_seconds: int = 120) -> dict[str, Any]:
    if not url.startswith(("https://", "http://")): raise ValueError("only http and https URLs are supported")
    target = _path(destination)
    if target.exists() and not overwrite: raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AIONEX-MCP/1.0"})
    temporary = target.with_name(f".{target.name}.download-{os.getpid()}")
    try:
        with urllib.request.urlopen(request, timeout=max(1, min(int(timeout_seconds), 600))) as response, temporary.open("wb") as stream: shutil.copyfileobj(response, stream)
        os.replace(temporary, target)
    finally: temporary.unlink(missing_ok=True)
    return {"success": True, "path": str(target), "size_bytes": target.stat().st_size}


@mcp.tool()
def git_status(cwd: str = "/opt/AIOS") -> dict[str, Any]:
    return _run(["git", "status", "--short", "--branch"], cwd=cwd, timeout_seconds=30, env=_git_env())


@mcp.tool()
def git_command(arguments: str, cwd: str = "/opt/AIOS", timeout_seconds: int = 120) -> dict[str, Any]:
    args = shlex.split(arguments)
    if not args: raise ValueError("Git arguments are required")
    return _run(["git", *args], cwd=cwd, timeout_seconds=timeout_seconds, env=_git_env())


@mcp.tool()
def github_command(arguments: str, cwd: str = "/opt/AIOS", timeout_seconds: int = 180) -> dict[str, Any]:
    args = shlex.split(arguments)
    if not args: raise ValueError("GitHub CLI arguments are required")
    return _run(["gh", *args], cwd=cwd, timeout_seconds=timeout_seconds, env=_git_env())


@mcp.tool()
def docker_command(arguments: str, cwd: str = "/opt/AIOS", timeout_seconds: int = 180) -> dict[str, Any]:
    args = shlex.split(arguments)
    if not args: raise ValueError("Docker arguments are required")
    return _run(["docker", *args], cwd=cwd, timeout_seconds=timeout_seconds)


@mcp.tool()
def run_pytest(targets: str = "", cwd: str = "/opt/AIOS", timeout_seconds: int = 600) -> dict[str, Any]:
    executable = PYTHON_BIN if PYTHON_BIN.is_file() else Path(sys.executable)
    return _run([str(executable), "-m", "pytest", "-q", *shlex.split(targets)], cwd=cwd, timeout_seconds=timeout_seconds)


@mcp.tool()
def runpod_endpoint_status(endpoint_id: str) -> dict[str, Any]:
    endpoint = _runpod_request("GET", f"https://rest.runpod.io/v1/endpoints/{endpoint_id}")
    health = _runpod_request("GET", f"https://api.runpod.ai/v2/{endpoint_id}/health")
    result: dict[str, Any] = {"endpoint": None, "health": None, "errors": []}
    if endpoint.get("http_status") == 200 and isinstance(endpoint.get("data"), dict): result["endpoint"] = _safe_endpoint(endpoint["data"])
    else: result["errors"].append({"source": "endpoint", **endpoint})
    if health.get("http_status") == 200 and isinstance(health.get("data"), dict): result["health"] = health["data"]
    else: result["errors"].append({"source": "health", **health})
    return result


@mcp.tool()
def runpod_delete_endpoint(endpoint_id: str) -> dict[str, Any]:
    result = _runpod_request("DELETE", f"https://rest.runpod.io/v1/endpoints/{endpoint_id}")
    if result.get("http_status") in (200, 202, 204): return {"success": True, "endpoint_id": endpoint_id, "http_status": result.get("http_status")}
    return {"success": False, "endpoint_id": endpoint_id, **result}


@mcp.tool()
def runpod_purge_queue(endpoint_id: str) -> dict[str, Any]:
    result = _runpod_request("POST", f"https://api.runpod.ai/v2/{endpoint_id}/purge-queue")
    return {"success": result.get("http_status") == 200, **result}


@mcp.tool()
def runpod_submit_image(endpoint_id: str, image_path: str) -> dict[str, Any]:
    image = _path(image_path)
    if not image.is_file(): raise FileNotFoundError(str(image))
    payload = {"input": {"image": base64.b64encode(image.read_bytes()).decode("ascii")}}
    result = _runpod_request("POST", f"https://api.runpod.ai/v2/{endpoint_id}/run", payload, timeout=90)
    if result.get("http_status") == 200 and isinstance(result.get("data"), dict): return {"success": True, "job": _safe_job(result["data"])}
    return {"success": False, **result}


@mcp.tool()
def runpod_job_status(endpoint_id: str, job_id: str) -> dict[str, Any]:
    result = _runpod_request("GET", f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}")
    if result.get("http_status") == 200 and isinstance(result.get("data"), dict): return {"success": True, "job": _safe_job(result["data"])}
    return {"success": False, **result}


@mcp.tool()
def runpod_cancel_job(endpoint_id: str, job_id: str) -> dict[str, Any]:
    result = _runpod_request("POST", f"https://api.runpod.ai/v2/{endpoint_id}/cancel/{job_id}")
    if result.get("http_status") == 200 and isinstance(result.get("data"), dict): return {"success": True, "job": _safe_job(result["data"])}
    return {"success": False, **result}


@mcp.tool()
def runpod_wait_job(endpoint_id: str, job_id: str, output_path: str, timeout_seconds: int = 1800, poll_seconds: int = 15) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, min(int(timeout_seconds), 7200))
    poll = max(2, min(int(poll_seconds), 60))
    while True:
        result = _runpod_request("GET", f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}")
        if result.get("http_status") != 200 or not isinstance(result.get("data"), dict): return {"success": False, **result}
        data = result["data"]
        status = str(data.get("status") or "")
        if status == "COMPLETED":
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            encoded = output.get("content_base64")
            if not encoded: return {"success": False, "job": _safe_job(data), "error": "completed without content_base64"}
            target = _path(output_path); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(base64.b64decode(encoded))
            header = target.read_bytes()[:4]
            return {"success": True, "job": _safe_job(data), "output_path": str(target), "size_bytes": target.stat().st_size, "glb_magic_ok": header == b"glTF"}
        if status in {"FAILED", "CANCELLED", "TIMED_OUT"}: return {"success": False, "job": _safe_job(data)}
        if time.monotonic() >= deadline: return {"success": False, "job": _safe_job(data), "error": "wait timeout"}
        time.sleep(poll)


@mcp.tool()
def mcp_install_update(source_path: str) -> dict[str, Any]:
    source = _path(source_path)
    if not source.is_file(): raise FileNotFoundError(str(source))
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()); backup = MCP_SERVER_PATH.with_name(f"{MCP_SERVER_PATH.name}.backup-{timestamp}"); MCP_SERVER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MCP_SERVER_PATH.exists(): shutil.copy2(MCP_SERVER_PATH, backup)
    temporary = MCP_SERVER_PATH.with_name(f".{MCP_SERVER_PATH.name}.install-{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        python_bin = str(PYTHON_BIN if PYTHON_BIN.is_file() else Path(sys.executable)); compile_result = _run([python_bin, "-m", "py_compile", str(temporary)], cwd=PROJECT_ROOT, timeout_seconds=60)
        if compile_result["exit_code"] != 0: return {"success": False, "status": "compile-failed", "backup": str(backup) if backup.exists() else None, "compile": compile_result}
        os.chmod(temporary, 0o600); os.replace(temporary, MCP_SERVER_PATH)
    finally: temporary.unlink(missing_ok=True)
    return {"success": True, "status": "installed", "source": str(source), "destination": str(MCP_SERVER_PATH), "backup": str(backup) if backup.exists() else None}


@mcp.tool()
def mcp_restart_tunnel() -> dict[str, Any]:
    """Request restart of this connector only; never stop another tunnel."""
    result = _run(
        ["systemctl", "--no-block", "restart", TUNNEL_SERVICE],
        cwd=PROJECT_ROOT,
        timeout_seconds=30,
    )
    return {
        "success": result["exit_code"] == 0,
        "status": "restart-requested" if result["exit_code"] == 0 else "restart-failed",
        "profile": TUNNEL_PROFILE,
        "service": TUNNEL_SERVICE,
        "verification_required": True,
        "command": result,
    }


if __name__ == "__main__":
    mcp.run()
