from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping

from .assets import ArtifactManifest, AssetBudgetGate, AssetInspector, AssetMetadata
from .contracts import PerformanceProfile, Project3DBlueprint
from .performance import (
    PerformanceGate,
    PerformanceGateResult,
    PerformanceSample,
    ReleaseEvidence,
    ReleaseGateResult,
    ThreeDReleaseGate,
)
from .scaffold import RuntimeScaffold, ThreeDRuntimeScaffoldBuilder
from .visual_qa import BrowserRunReceipt, EvidenceManifestBuilder, VisualQAGate, VisualQAVerdict


class LifecycleStage(str, Enum):
    BLUEPRINT = "blueprint"
    SCAFFOLD = "scaffold"
    ASSETS = "assets"
    VISUAL_QA = "visual_qa"
    PERFORMANCE_QA = "performance_qa"
    APPROVAL = "approval"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class RemediationRecommendation:
    stage: LifecycleStage
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OwnerEvidence:
    project_id: str
    stage: LifecycleStage
    status: str
    sha256: str
    summary: str


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    approver: str | None
    reason: str | None = None

    def validate(self) -> None:
        if self.approved and not (self.approver or "").strip():
            raise ValueError("approved lifecycle requires an approver")
        if not self.approved and not (self.reason or "").strip():
            raise ValueError("rejected lifecycle requires a reason")


@dataclass(frozen=True, slots=True)
class LifecycleInputs:
    blueprint: Project3DBlueprint
    project_root: Path
    browser_runs: tuple[BrowserRunReceipt, ...]
    performance_samples: tuple[PerformanceSample, ...]
    production_build_passed: bool
    deployment_receipt: str | None
    rollback_receipt: str | None
    approval: ApprovalDecision


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    project_id: str
    passed: bool
    release_ready: bool
    scaffold: RuntimeScaffold | None
    asset_metadata: tuple[AssetMetadata, ...]
    asset_manifest: ArtifactManifest | None
    visual_qa: VisualQAVerdict
    performance_results: tuple[PerformanceGateResult, ...]
    release_gate: ReleaseGateResult
    evidence: tuple[OwnerEvidence, ...]
    remediation: tuple[RemediationRecommendation, ...]
    aggregate_sha256: str

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.value if hasattr(value, "value") else str(value),
        )


class ThreeDProjectLifecycle:
    """Deterministic end-to-end orchestration for governed 3D web delivery."""

    def __init__(self) -> None:
        self._scaffold = ThreeDRuntimeScaffoldBuilder()
        self._asset_inspector = AssetInspector()
        self._asset_gate = AssetBudgetGate()
        self._visual_gate = VisualQAGate()
        self._evidence_builder = EvidenceManifestBuilder()
        self._perf_gate = PerformanceGate()
        self._release_gate = ThreeDReleaseGate()

    def run(self, inputs: LifecycleInputs) -> LifecycleResult:
        blueprint = inputs.blueprint
        blueprint.validate()
        inputs.approval.validate()

        evidence: list[OwnerEvidence] = []
        remediation: list[RemediationRecommendation] = []

        scaffold = self._scaffold.build(blueprint)
        scaffold_digest = sha256(
            json.dumps(
                [(item.path, item.content) for item in scaffold.files],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.SCAFFOLD, "passed", scaffold_digest, "runtime scaffold generated"))

        metadata: list[AssetMetadata] = []
        asset_manifest: ArtifactManifest | None = None
        asset_gate_passed = True
        if blueprint.assets:
            from .assets import ArtifactManifestBuilder
            builder = ArtifactManifestBuilder()
            try:
                for asset in blueprint.assets:
                    metadata.append(self._asset_inspector.inspect(asset, inputs.project_root))
                for profile in blueprint.performance_profiles:
                    result = self._asset_gate.evaluate(metadata, profile)
                    if not result.passed:
                        asset_gate_passed = False
                        for violation in result.violations:
                            remediation.append(RemediationRecommendation(
                                LifecycleStage.ASSETS,
                                f"asset-{violation.metric}",
                                f"{violation.asset_id or 'project'} exceeds {violation.metric} budget for {profile.value}",
                            ))
                asset_manifest = builder.build(blueprint.assets, inputs.project_root)
                evidence.append(OwnerEvidence(
                    blueprint.project_id,
                    LifecycleStage.ASSETS,
                    "passed" if asset_gate_passed else "failed",
                    asset_manifest.aggregate_sha256,
                    f"{len(metadata)} registered assets inspected",
                ))
            except (FileNotFoundError, ValueError) as exc:
                asset_gate_passed = False
                remediation.append(RemediationRecommendation(LifecycleStage.ASSETS, "asset-validation", str(exc)))
        else:
            evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.ASSETS, "passed", sha256(b"no-assets").hexdigest(), "no external assets registered"))

        visual = self._visual_gate.evaluate(inputs.browser_runs)
        visual_manifest = self._evidence_builder.build(inputs.browser_runs) if inputs.browser_runs else None
        visual_digest = visual_manifest.aggregate_sha256 if visual_manifest else sha256(b"no-browser-runs").hexdigest()
        evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.VISUAL_QA, "passed" if visual.passed else "failed", visual_digest, "browser acceptance evaluated"))
        for violation in visual.violations:
            remediation.append(RemediationRecommendation(LifecycleStage.VISUAL_QA, "visual-qa", violation))

        perf_results: list[PerformanceGateResult] = []
        perf_payload: list[dict[str, object]] = []
        for sample in inputs.performance_samples:
            result = self._perf_gate.evaluate(sample)
            perf_results.append(result)
            perf_payload.append(asdict(result))
            for violation in result.violations:
                remediation.append(RemediationRecommendation(
                    LifecycleStage.PERFORMANCE_QA,
                    f"performance-{violation.metric}",
                    f"{sample.profile.value}: {violation.metric} must be {violation.relation} {violation.limit}",
                ))
        perf_digest = sha256(json.dumps(perf_payload, sort_keys=True, separators=(",", ":"), default=lambda v: v.value if hasattr(v, "value") else v).encode()).hexdigest()
        evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.PERFORMANCE_QA, "passed" if perf_results and all(r.passed for r in perf_results) else "failed", perf_digest, "3D performance profiles evaluated"))

        if not inputs.approval.approved:
            remediation.append(RemediationRecommendation(LifecycleStage.APPROVAL, "owner-approval", inputs.approval.reason or "approval required"))
        approval_digest = sha256(json.dumps(asdict(inputs.approval), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.APPROVAL, "passed" if inputs.approval.approved else "failed", approval_digest, inputs.approval.approver or inputs.approval.reason or "approval unresolved"))

        release_evidence: ReleaseEvidence | None = None
        if (
            asset_manifest is not None or not blueprint.assets
        ) and visual_manifest is not None and perf_results and inputs.deployment_receipt and inputs.rollback_receipt:
            build_digest = sha256(f"{blueprint.project_id}:{scaffold_digest}".encode()).hexdigest()
            asset_digest = asset_manifest.aggregate_sha256 if asset_manifest else sha256(b"no-assets").hexdigest()
            release_evidence = ReleaseEvidence(
                build_id=f"3d-{blueprint.project_id}",
                build_sha256=build_digest,
                asset_manifest_sha256=asset_digest,
                visual_qa_manifest_sha256=visual_digest,
                performance_receipt_sha256=perf_digest,
                deployment_receipt=inputs.deployment_receipt,
                rollback_receipt=inputs.rollback_receipt,
            )

        release_gate = self._release_gate.evaluate(
            performance_results=tuple(perf_results),
            visual_qa_passed=visual.passed,
            asset_gate_passed=asset_gate_passed,
            production_build_passed=inputs.production_build_passed,
            evidence=release_evidence,
        )
        if not inputs.approval.approved:
            release_gate = ReleaseGateResult(False, release_gate.reasons + ("owner approval missing",))
        for reason in release_gate.reasons:
            remediation.append(RemediationRecommendation(LifecycleStage.RELEASE, "release-gate", reason))
        release_digest = sha256(json.dumps(asdict(release_gate), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        evidence.append(OwnerEvidence(blueprint.project_id, LifecycleStage.RELEASE, "passed" if release_gate.passed else "failed", release_digest, "production release gate evaluated"))

        canonical = json.dumps(
            {
                "project_id": blueprint.project_id,
                "evidence": [asdict(item) for item in evidence],
                "remediation": [asdict(item) for item in remediation],
                "release_gate": asdict(release_gate),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.value if hasattr(value, "value") else value,
        ).encode()
        aggregate = sha256(canonical).hexdigest()
        passed = release_gate.passed and inputs.approval.approved
        return LifecycleResult(
            project_id=blueprint.project_id,
            passed=passed,
            release_ready=passed,
            scaffold=scaffold,
            asset_metadata=tuple(metadata),
            asset_manifest=asset_manifest,
            visual_qa=visual,
            performance_results=tuple(perf_results),
            release_gate=release_gate,
            evidence=tuple(evidence),
            remediation=tuple(remediation),
            aggregate_sha256=aggregate,
        )
