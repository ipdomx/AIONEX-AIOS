from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from .three_d_web import (
    ApprovalDecision,
    BrowserRunReceipt,
    BrowserSpec,
    BrowserSupport,
    EvidenceEntry,
    EvidenceKind,
    LifecycleInputs,
    PerformanceProfile,
    PerformanceSample,
    SceneZone,
    ScenarioResult,
    ThreeDProjectLifecycle,
    ThreeDProjectPlanner,
    ViewportSpec,
)
from .three_d_web.visual_qa import checksum_bytes


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    case_id: str
    project_type: str
    description: str
    passed: bool
    evidence_sha256: str
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Phase31EAcceptanceReport:
    version: int
    cases: tuple[AcceptanceCase, ...]
    passed: bool
    aggregate_sha256: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _digest(payload: object) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _browser_runs() -> tuple[BrowserRunReceipt, ...]:
    scenarios = (
        ScenarioResult("route-home", True),
        ScenarioResult("asset-world", True),
        ScenarioResult("interaction-primary", True),
        ScenarioResult("camera-follow-focus", True),
    )
    return tuple(
        BrowserRunReceipt(
            BrowserSpec("chromium", "chromium", BrowserSupport.SUPPORTED),
            viewport,
            (),
            (),
            scenarios,
            (
                EvidenceEntry(
                    f"shot-{viewport.viewport_id}",
                    EvidenceKind.SCREENSHOT,
                    f"evidence/{viewport.viewport_id}.png",
                    checksum_bytes(viewport.viewport_id.encode()),
                    viewport_id=viewport.viewport_id,
                    browser_id="chromium",
                ),
            ),
        )
        for viewport in (
            ViewportSpec("desktop-1440", 1440, 900),
            ViewportSpec("mobile-390", 390, 844, 3.0, True),
        )
    )


def _performance_samples() -> tuple[PerformanceSample, ...]:
    return tuple(
        PerformanceSample(
            profile=profile,
            fps=60.0,
            frame_time_ms=16.0,
            draw_calls=50,
            triangles=100_000,
            asset_bytes=1_000_000,
            bundle_bytes=1_000_000,
            gpu_memory_mb=128,
        )
        for profile in (
            PerformanceProfile.DESKTOP,
            PerformanceProfile.MOBILE,
            PerformanceProfile.LOW_POWER,
        )
    )


def run_3d_acceptance(tmp_root: Path) -> AcceptanceCase:
    blueprint = ThreeDProjectPlanner().plan(
        project_id="phase31e-3d",
        title="Phase 31E 3D Acceptance",
        objective="Prove AIOS can govern a complete 3D web project lifecycle.",
        zones=(
            SceneZone("home", "Home", (0.0, 0.0, 0.0), 12.0),
            SceneZone("experience", "Experience", (18.0, 0.0, 12.0), 10.0),
        ),
    )
    result = ThreeDProjectLifecycle().run(
        LifecycleInputs(
            blueprint=blueprint,
            project_root=tmp_root,
            browser_runs=_browser_runs(),
            performance_samples=_performance_samples(),
            production_build_passed=True,
            deployment_receipt="phase31e-deployment-evidence",
            rollback_receipt="phase31e-rollback-evidence",
            approval=ApprovalDecision(True, "phase31e-owner-acceptance"),
        )
    )
    details = (
        f"release_ready={result.release_ready}",
        f"evidence_items={len(result.evidence)}",
        f"remediation_items={len(result.remediation)}",
        f"lifecycle_sha256={result.aggregate_sha256}",
    )
    return AcceptanceCase(
        "3d-web-lifecycle",
        "3d_web_project",
        "Blueprint, scaffold, assets, browser QA, performance, approval and release gate.",
        result.passed and result.release_ready and not result.remediation,
        result.aggregate_sha256,
        details,
    )


def run_repository_acceptance(project_root: Path) -> AcceptanceCase:
    required = (
        "src/aios/three_d_web/contracts.py",
        "src/aios/three_d_web/assets.py",
        "src/aios/three_d_web/scaffold.py",
        "src/aios/three_d_web/visual_qa.py",
        "src/aios/three_d_web/performance.py",
        "src/aios/three_d_web/lifecycle.py",
        "src/aios/backend_zero_dead.py",
        "src/aios/live_activation.py",
        "web-dashboard/backend/app/api/v1/router.py",
        "web-dashboard/frontend/src/app/owner/page.tsx",
    )
    missing = tuple(path for path in required if not (project_root / path).is_file())
    payload = {"required": required, "missing": missing}
    return AcceptanceCase(
        "repository-capability-chain",
        "platform",
        "Required Phase 30/31 runtime surfaces are present in the repository.",
        not missing,
        _digest(payload),
        (f"required_files={len(required)}", f"missing={len(missing)}") + missing,
    )


def build_phase31e_report(project_root: Path, tmp_root: Path) -> Phase31EAcceptanceReport:
    cases = (
        run_repository_acceptance(project_root),
        run_3d_acceptance(tmp_root),
    )
    canonical = [asdict(case) for case in cases]
    return Phase31EAcceptanceReport(
        version=1,
        cases=cases,
        passed=all(case.passed for case in cases),
        aggregate_sha256=_digest(canonical),
    )
