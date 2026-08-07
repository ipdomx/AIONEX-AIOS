from __future__ import annotations

from hashlib import sha256

import pytest

from aios.three_d_web import PerformanceProfile
from aios.three_d_web.performance import (
    PerformanceBudget,
    PerformanceGate,
    PerformanceReceiptBuilder,
    PerformanceSample,
    ReleaseEvidence,
    ThreeDReleaseGate,
)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _sample(profile: PerformanceProfile) -> PerformanceSample:
    values = {
        PerformanceProfile.DESKTOP: (60, 16, 120, 600_000, 20_000_000, 2_000_000, 320),
        PerformanceProfile.MOBILE: (50, 19, 90, 350_000, 12_000_000, 1_500_000, 220),
        PerformanceProfile.LOW_POWER: (35, 28, 60, 180_000, 8_000_000, 1_000_000, 160),
    }[profile]
    return PerformanceSample(profile, *values)


def test_default_performance_gate_passes_representative_profiles() -> None:
    gate = PerformanceGate()
    results = [gate.evaluate(_sample(profile)) for profile in PerformanceProfile]
    assert all(result.passed for result in results)
    assert all(result.violations == () for result in results)


def test_performance_gate_reports_all_limit_breaches() -> None:
    budget = PerformanceBudget(60, 16, 10, 100, 1000, 500, 64)
    gate = PerformanceGate({PerformanceProfile.DESKTOP: budget})
    sample = PerformanceSample(PerformanceProfile.DESKTOP, 30, 40, 50, 900, 5000, 2000, 256)
    result = gate.evaluate(sample)
    assert not result.passed
    metrics = {item.metric for item in result.violations}
    assert metrics == {"fps", "frame_time_ms", "draw_calls", "triangles", "asset_bytes", "bundle_bytes", "gpu_memory_mb"}


def test_gpu_metric_is_fail_closed_when_budget_requires_it() -> None:
    sample = _sample(PerformanceProfile.MOBILE)
    sample = PerformanceSample(
        sample.profile, sample.fps, sample.frame_time_ms, sample.draw_calls, sample.triangles,
        sample.asset_bytes, sample.bundle_bytes, None,
    )
    result = PerformanceGate().evaluate(sample)
    assert not result.passed
    assert any(v.metric == "gpu_memory_mb" and v.actual is None for v in result.violations)


def test_negative_metrics_are_rejected() -> None:
    with pytest.raises(ValueError):
        PerformanceGate().evaluate(PerformanceSample(PerformanceProfile.DESKTOP, -1, 1, 1, 1, 1, 1, 1))


def test_performance_receipt_is_deterministic() -> None:
    sample = _sample(PerformanceProfile.DESKTOP)
    result = PerformanceGate().evaluate(sample)
    builder = PerformanceReceiptBuilder()
    first = builder.build(sample, result)
    second = builder.build(sample, result)
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert first.to_json() == second.to_json()


def test_release_evidence_requires_real_receipts_and_digests() -> None:
    evidence = ReleaseEvidence(
        build_id="build-30e",
        build_sha256=_digest("build"),
        asset_manifest_sha256=_digest("assets"),
        visual_qa_manifest_sha256=_digest("visual"),
        performance_receipt_sha256=_digest("performance"),
        deployment_receipt="deploy://receipt/30e",
        rollback_receipt="rollback://receipt/30e",
    )
    evidence.validate()
    with pytest.raises(ValueError):
        ReleaseEvidence(
            "x", "bad", _digest("a"), _digest("v"), _digest("p"), "deploy", "rollback"
        ).validate()


def test_release_gate_passes_only_with_all_profiles_and_evidence() -> None:
    perf = tuple(PerformanceGate().evaluate(_sample(profile)) for profile in PerformanceProfile)
    evidence = ReleaseEvidence(
        "build-30e", _digest("build"), _digest("assets"), _digest("visual"),
        _digest("performance"), "deploy://ok", "rollback://ok",
    )
    result = ThreeDReleaseGate().evaluate(
        performance_results=perf,
        visual_qa_passed=True,
        asset_gate_passed=True,
        production_build_passed=True,
        evidence=evidence,
    )
    assert result.passed
    assert result.reasons == ()


def test_release_gate_is_fail_closed_for_missing_profile_or_failed_evidence() -> None:
    perf = (PerformanceGate().evaluate(_sample(PerformanceProfile.DESKTOP)),)
    result = ThreeDReleaseGate().evaluate(
        performance_results=perf,
        visual_qa_passed=False,
        asset_gate_passed=False,
        production_build_passed=False,
        evidence=None,
    )
    assert not result.passed
    joined = " | ".join(result.reasons)
    assert "missing performance profiles" in joined
    assert "visual QA" in joined
    assert "asset gate" in joined
    assert "production build" in joined
    assert "release evidence" in joined
