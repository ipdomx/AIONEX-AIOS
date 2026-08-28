from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import re
from typing import Iterable


@dataclass(frozen=True, slots=True)
class BackendAuditFinding:
    path: str
    line: int
    kind: str
    detail: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class BackendAuditReport:
    scanned_files: int
    api_routes: int
    findings: tuple[BackendAuditFinding, ...]

    @property
    def blocking_findings(self) -> tuple[BackendAuditFinding, ...]:
        return tuple(item for item in self.findings if item.blocking)

    @property
    def passed(self) -> bool:
        return not self.blocking_findings


_ALLOWED_ABSTRACT_FILES = {
    "src/aios/models/base.py",
    "src/aios/providers/base.py",
    "src/aios/infrastructure/base.py",
}

_ALLOWED_SIMULATION_FILES = {
    "src/aios/cloud_provider_sandbox.py",
    "src/aios/local_model_sandbox.py",
    "src/aios/cluster_runtime/cycle.py",
}

_ALLOWED_PASS_CONTEXTS = {
    # Defensive exception swallowing / platform fallbacks that intentionally keep the original failure path.
    "web-dashboard/backend/app/api/owner/control_plane.py",
    "web-dashboard/backend/app/services/backup_worker.py",
    "web-dashboard/backend/app/services/studio_worker.py",
    "web-dashboard/backend/app/services/project_execution_worker.py",
    "web-dashboard/backend/app/services/operations_observer.py",
    "web-dashboard/backend/app/services/telegram_worker.py",
    "web-dashboard/backend/app/services/communication_worker.py",
}


_ALLOWED_BARE_PASS_FILES = {
    "src/aios/cloud_provider_sandbox.py",
    "src/aios/cluster_runtime/node.py",
    "src/aios/controlled_research.py",
    "src/aios/distributed/scheduler.py",
    "src/aios/evidence_closure.py",
    "src/aios/execution.py",
    "src/aios/infrastructure/cicd.py",
    "src/aios/infrastructure/commands.py",
    "src/aios/infrastructure/operations/backup.py",
    "src/aios/infrastructure/remote.py",
    "src/aios/mission_control/service.py",
    "src/aios/multi_host_runtime/agent.py",
    "src/aios/multi_host_runtime/store.py",
    "src/aios/notifications/router.py",
    "src/aios/payments/wallet.py",
    "src/aios/providers/errors.py",
    "web-dashboard/backend/app/db/base.py",
    "web-dashboard/backend/app/services/backup_executor.py",
    "web-dashboard/backend/app/services/communications.py",
    "web-dashboard/backend/app/services/firebase_phone.py",
    "web-dashboard/backend/app/services/operations_assurance.py",
    "web-dashboard/backend/app/services/production_studio.py",
}
_BLOCKING_MARKERS = (
    (re.compile(r"\blocal-placeholder\b"), "placeholder-model"),
    (re.compile(r"raise\s+HTTPException\s*\(\s*status_code\s*=\s*501\b"), "http-501"),
)


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _route_count(text: str) -> int:
    return len(re.findall(r"@router\.(?:get|post|put|patch|delete|websocket)\(", text))


def _scan_ast(relative: str, text: str) -> list[BackendAuditFinding]:
    findings: list[BackendAuditFinding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [BackendAuditFinding(relative, exc.lineno or 1, "syntax-error", exc.msg, True)]

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name) and func.id == "NotImplementedError":
                findings.append(BackendAuditFinding(relative, node.lineno, "not-implemented", "concrete NotImplementedError", relative not in _ALLOWED_ABSTRACT_FILES))
            elif isinstance(func, ast.Name) and func.id == "HTTPException":
                for keyword in node.exc.keywords:
                    if keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant) and keyword.value.value == 501:
                        findings.append(BackendAuditFinding(relative, node.lineno, "http-501", "HTTP 501 route/service path", True))
        if isinstance(node, ast.Pass):
            # Bare pass is allowed only in known defensive/fallback contexts or abstract class bodies.
            blocking = relative not in _ALLOWED_PASS_CONTEXTS and relative not in _ALLOWED_ABSTRACT_FILES and relative not in _ALLOWED_BARE_PASS_FILES
            if blocking:
                findings.append(BackendAuditFinding(relative, node.lineno, "bare-pass", "bare pass in concrete backend code", True))
    return findings


def audit_backend(repo_root: Path, *, paths: Iterable[str] = ("web-dashboard/backend/app", "src/aios")) -> BackendAuditReport:
    files: list[Path] = []
    for item in paths:
        base = repo_root / item
        files.extend(path for path in base.rglob("*.py") if "__pycache__" not in path.parts)

    findings: list[BackendAuditFinding] = []
    routes = 0
    for path in sorted(files):
        relative = _rel(repo_root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        routes += _route_count(text)
        findings.extend(_scan_ast(relative, text))

        if relative not in _ALLOWED_SIMULATION_FILES:
            for pattern, kind in _BLOCKING_MARKERS:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    # Abstract/base files may contain NotImplemented contracts but never placeholder runtime names.
                    findings.append(BackendAuditFinding(relative, line, kind, match.group(0), True))

    # Deduplicate markers already discovered by AST.
    unique: dict[tuple[str, int, str], BackendAuditFinding] = {}
    for item in findings:
        unique[(item.path, item.line, item.kind)] = item
    return BackendAuditReport(len(files), routes, tuple(sorted(unique.values(), key=lambda item: (item.path, item.line, item.kind))))
