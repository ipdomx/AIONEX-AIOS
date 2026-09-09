"""Install the reviewed MCP2 source atomically; never restart a tunnel here."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/opt/AIOS")
TARGET = ROOT / "tools/aionex_phase22c_mcp2.py"
SOURCE = ROOT / "ops/mcp2/server.py"
RUNTIME = ROOT / "docs/project/runtime"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_source(data: bytes) -> int:
    text = data.decode("utf-8")
    tree = ast.parse(text)
    compile(text, str(SOURCE), "exec")
    count = sum(
        isinstance(node, ast.FunctionDef)
        and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "tool" for d in node.decorator_list)
        for node in tree.body
    )
    if count != 28 or 'PROJECT_ROOT = Path("/opt/AIOS")' not in text:
        raise ValueError("MCP2 contract or production root mismatch")
    if any(marker in text for marker in ["MCP2_PHASE33_WRAPPER", "pkill", "/opt/AIOS-worktrees/session2"]):
        raise ValueError("unsafe legacy operator behavior")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-main-commit", required=True)
    parser.add_argument("--expected-current-sha256", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("root is required for this project operator")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if commit != args.expected_main_commit:
        raise ValueError("production source changed since approval")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "ops/mcp2"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    for path in [SOURCE, TARGET]:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise ValueError("operator source and target must be root-owned regular files without links")
    data, before = SOURCE.read_bytes(), TARGET.read_bytes()
    if sha256(data) != args.expected_candidate_sha256:
        raise ValueError("candidate digest mismatch")
    if sha256(before) != args.expected_current_sha256:
        raise ValueError("live operator changed; refusing overwrite")
    tools = validate_source(data)
    result = {"status": "PREFLIGHT_PASS", "main_commit": commit, "candidate_sha256": sha256(data), "previous_sha256": sha256(before), "registered_tools": tools, "restart_performed": False}
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = RUNTIME / "mcp2-backups" / f"before-{stamp}.py"
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(before)
            stream.flush()
            os.fsync(stream.fileno())
        fd, temporary = tempfile.mkstemp(prefix=".mcp2-reviewed-", dir=TARGET.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, TARGET)
            directory_fd = os.open(TARGET.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if sha256(TARGET.read_bytes()) != sha256(data):
            raise RuntimeError("post-install digest mismatch; retained backup requires reconciliation")
        result.update(status="INSTALLED_NOT_YET_CONNECTION_VERIFIED", backup_path=str(backup), target=str(TARGET), installed_at=datetime.now(timezone.utc).isoformat())
        receipt = RUNTIME / f"mcp2-install-{stamp}.json"
        receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        result["receipt_path"] = str(receipt)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
