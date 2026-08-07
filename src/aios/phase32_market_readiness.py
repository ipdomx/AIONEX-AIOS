from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from shutil import which
from typing import Iterable, Mapping

from .backend_zero_dead import audit_backend
from .live_activation import build_activation_snapshot
from .phase31f_certification import certify_repository


@dataclass(frozen=True, slots=True)
class MarketReadinessFinding:
    code: str
    severity: str
    surface: str
    detail: str
    activation_boundary: bool = False


@dataclass(frozen=True, slots=True)
class MarketReadinessReport:
    passed: bool
    findings: tuple[MarketReadinessFinding, ...]
    aggregate_sha256: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def certify_market_readiness(
    root: Path,
    *,
    running_services: Iterable[str],
    configured_env: Iterable[str],
    executable_overrides: Mapping[str, str] | None = None,
) -> MarketReadinessReport:
    """Certify repository/runtime readiness without making CI depend on host-only tools.

    Blender/glTF Transform are required for the designated production host, but remain
    truthful activation boundaries on generic CI runners unless explicit executable
    overrides are supplied. Host release validation should pass the discovered paths.
    """
    findings: list[MarketReadinessFinding] = []

    backend = audit_backend(root)
    for item in backend.blocking_findings:
        findings.append(MarketReadinessFinding(
            code=item.kind,
            severity="high",
            surface=item.path,
            detail=item.detail,
        ))

    repo = certify_repository(root)
    for item in repo.findings:
        findings.append(MarketReadinessFinding(
            code=item.code,
            severity="high",
            surface=item.path,
            detail=item.detail,
        ))

    activation = build_activation_snapshot(
        running_services=running_services,
        configured_env=configured_env,
        executable_overrides=executable_overrides,
    )
    optional_boundaries = {
        "telegram-worker", "tripo3d", "meshy", "kubernetes", "helm",
    }
    host_tool_boundaries = {"blender", "gltf-transform"}
    for row in (*activation.workers, *activation.tools, *activation.providers, *activation.integrations):
        if row.status == "ready":
            continue
        optional = row.surface_id in optional_boundaries
        host_tool = row.surface_id in host_tool_boundaries and executable_overrides is None
        boundary = optional or host_tool
        findings.append(MarketReadinessFinding(
            code="activation-boundary" if boundary else "required-runtime-unavailable",
            severity="info" if boundary else "high",
            surface=row.surface_id,
            detail=row.reason,
            activation_boundary=boundary,
        ))

    required_tools = ("git", "gh", "docker", "node", "npm", "python3")
    for tool in required_tools:
        if not which(tool):
            findings.append(MarketReadinessFinding(
                code="required-tool-missing",
                severity="high",
                surface=tool,
                detail=f"Required market-release tool is missing: {tool}",
            ))

    blocking = tuple(item for item in findings if item.severity in {"high", "critical"})
    canonical = json.dumps(
        [asdict(item) for item in sorted(findings, key=lambda x: (x.severity, x.surface, x.code, x.detail))],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return MarketReadinessReport(not blocking, tuple(findings), sha256(canonical).hexdigest())
