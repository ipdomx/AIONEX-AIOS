from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from typing import Mapping

from .contracts import PerformanceProfile


@dataclass(frozen=True, slots=True)
class PerformanceBudget:
    min_fps: float
    max_frame_time_ms: float
    max_draw_calls: int
    max_triangles: int
    max_asset_bytes: int
    max_bundle_bytes: int
    max_gpu_memory_mb: int | None = None


DEFAULT_PERFORMANCE_BUDGETS: Mapping[PerformanceProfile, PerformanceBudget] = {
    PerformanceProfile.DESKTOP: PerformanceBudget(
        min_fps=55.0,
        max_frame_time_ms=20.0,
        max_draw_calls=350,
        max_triangles=2_500_000,
        max_asset_bytes=80 * 1024 * 1024,
        max_bundle_bytes=8 * 1024 * 1024,
        max_gpu_memory_mb=768,
    ),
    PerformanceProfile.MOBILE: PerformanceBudget(
        min_fps=45.0,
        max_frame_time_ms=24.0,
        max_draw_calls=180,
        max_triangles=900_000,
        max_asset_bytes=35 * 1024 * 1024,
        max_bundle_bytes=5 * 1024 * 1024,
        max_gpu_memory_mb=384,
    ),
    PerformanceProfile.LOW_POWER: PerformanceBudget(
        min_fps=30.0,
        max_frame_time_ms=34.0,
        max_draw_calls=110,
        max_triangles=450_000,
        max_asset_bytes=20 * 1024 * 1024,
        max_bundle_bytes=3 * 1024 * 1024,
        max_gpu_memory_mb=256,
    ),
}


@dataclass(frozen=True, slots=True)
class PerformanceSample:
    profile: PerformanceProfile
    fps: float
    frame_time_ms: float
    draw_calls: int
    triangles: int
    asset_bytes: int
    bundle_bytes: int
    gpu_memory_mb: int | None = None

    def validate(self) -> None:
        if self.fps < 0 or self.frame_time_ms < 0:
            raise ValueError("fps and frame_time_ms must be non-negative")
        for value in (self.draw_calls, self.triangles, self.asset_bytes, self.bundle_bytes):
            if value < 0:
                raise ValueError("performance counters must be non-negative")
        if self.gpu_memory_mb is not None and self.gpu_memory_mb < 0:
            raise ValueError("gpu_memory_mb must be non-negative")


@dataclass(frozen=True, slots=True)
class PerformanceViolation:
    metric: str
    actual: float | int | None
    limit: float | int | None
    relation: str


@dataclass(frozen=True, slots=True)
class PerformanceGateResult:
    profile: PerformanceProfile
    passed: bool
    violations: tuple[PerformanceViolation, ...]


class PerformanceGate:
    def __init__(self, budgets: Mapping[PerformanceProfile, PerformanceBudget] | None = None) -> None:
        self._budgets = dict(budgets or DEFAULT_PERFORMANCE_BUDGETS)

    def evaluate(self, sample: PerformanceSample) -> PerformanceGateResult:
        sample.validate()
        budget = self._budgets[sample.profile]
        violations: list[PerformanceViolation] = []
        lower = (("fps", sample.fps, budget.min_fps),)
        upper = (
            ("frame_time_ms", sample.frame_time_ms, budget.max_frame_time_ms),
            ("draw_calls", sample.draw_calls, budget.max_draw_calls),
            ("triangles", sample.triangles, budget.max_triangles),
            ("asset_bytes", sample.asset_bytes, budget.max_asset_bytes),
            ("bundle_bytes", sample.bundle_bytes, budget.max_bundle_bytes),
        )
        for metric, actual, limit in lower:
            if actual < limit:
                violations.append(PerformanceViolation(metric, actual, limit, ">="))
        for metric, actual, limit in upper:
            if actual > limit:
                violations.append(PerformanceViolation(metric, actual, limit, "<="))
        if budget.max_gpu_memory_mb is not None:
            if sample.gpu_memory_mb is None:
                violations.append(PerformanceViolation("gpu_memory_mb", None, budget.max_gpu_memory_mb, "required<="))
            elif sample.gpu_memory_mb > budget.max_gpu_memory_mb:
                violations.append(PerformanceViolation("gpu_memory_mb", sample.gpu_memory_mb, budget.max_gpu_memory_mb, "<="))
        return PerformanceGateResult(sample.profile, not violations, tuple(violations))


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    build_id: str
    build_sha256: str
    asset_manifest_sha256: str
    visual_qa_manifest_sha256: str
    performance_receipt_sha256: str
    deployment_receipt: str
    rollback_receipt: str

    def validate(self) -> None:
        if not self.build_id.strip():
            raise ValueError("build_id is required")
        for name in (
            "build_sha256",
            "asset_manifest_sha256",
            "visual_qa_manifest_sha256",
            "performance_receipt_sha256",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise ValueError(f"{name} must be a SHA-256 digest")
        if not self.deployment_receipt.strip() or not self.rollback_receipt.strip():
            raise ValueError("deployment and rollback receipts are required")


@dataclass(frozen=True, slots=True)
class PerformanceReceipt:
    version: int
    sample: PerformanceSample
    gate: PerformanceGateResult
    sha256: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "sample": asdict(self.sample),
                "gate": asdict(self.gate),
                "sha256": self.sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.value if hasattr(value, "value") else value,
        )


class PerformanceReceiptBuilder:
    def build(self, sample: PerformanceSample, gate: PerformanceGateResult) -> PerformanceReceipt:
        payload = json.dumps(
            {"sample": asdict(sample), "gate": asdict(gate)},
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.value if hasattr(value, "value") else value,
        ).encode()
        return PerformanceReceipt(1, sample, gate, sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class ReleaseGateResult:
    passed: bool
    reasons: tuple[str, ...]


class ThreeDReleaseGate:
    """Fail-closed production release gate for 3D web projects."""

    def evaluate(
        self,
        *,
        performance_results: tuple[PerformanceGateResult, ...],
        visual_qa_passed: bool,
        asset_gate_passed: bool,
        production_build_passed: bool,
        evidence: ReleaseEvidence | None,
    ) -> ReleaseGateResult:
        reasons: list[str] = []
        required_profiles = {
            PerformanceProfile.DESKTOP,
            PerformanceProfile.MOBILE,
            PerformanceProfile.LOW_POWER,
        }
        seen = {result.profile for result in performance_results}
        missing = required_profiles - seen
        if missing:
            reasons.append("missing performance profiles: " + ",".join(sorted(p.value for p in missing)))
        failed = [result.profile.value for result in performance_results if not result.passed]
        if failed:
            reasons.append("performance gate failed: " + ",".join(sorted(failed)))
        if not visual_qa_passed:
            reasons.append("visual QA did not pass")
        if not asset_gate_passed:
            reasons.append("asset gate did not pass")
        if not production_build_passed:
            reasons.append("production build did not pass")
        if evidence is None:
            reasons.append("release evidence is missing")
        else:
            try:
                evidence.validate()
            except ValueError as exc:
                reasons.append(str(exc))
        return ReleaseGateResult(not reasons, tuple(reasons))
