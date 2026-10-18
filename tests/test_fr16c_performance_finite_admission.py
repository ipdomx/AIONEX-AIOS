from __future__ import annotations

from dataclasses import replace
import json

import pytest

from aios.three_d_web import PerformanceProfile
from aios.three_d_web.performance import (
    PerformanceGate,
    PerformanceReceiptBuilder,
    PerformanceSample,
)


METRICS = (
    "fps", "frame_time_ms", "draw_calls", "triangles",
    "asset_bytes", "bundle_bytes", "gpu_memory_mb",
)
NONFINITE_VALUES = (
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="positive-infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
)


def _sample() -> PerformanceSample:
    return PerformanceSample(
        PerformanceProfile.DESKTOP, 60, 16, 120, 600_000,
        20_000_000, 2_000_000, 320,
    )


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("value", NONFINITE_VALUES)
@pytest.mark.parametrize("authoritative", (True, False))
def test_gate_rejects_nonfinite_measurements(
    metric: str, value: float, authoritative: bool,
) -> None:
    sample = replace(
        _sample(), **{metric: value},
        timing_measurement_authoritative=authoritative,
    )
    with pytest.raises(ValueError, match=rf"^{metric} must be finite$"):
        PerformanceGate().evaluate(sample)


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("value", NONFINITE_VALUES)
def test_receipt_builder_rejects_nonfinite_measurements(
    metric: str, value: float,
) -> None:
    valid_sample = _sample()
    gate = PerformanceGate().evaluate(valid_sample)
    invalid_sample = replace(valid_sample, **{metric: value})
    with pytest.raises(ValueError, match=rf"^{metric} must be finite$"):
        PerformanceReceiptBuilder().build(invalid_sample, gate)


@pytest.mark.parametrize("metric", METRICS)
def test_large_finite_integers_reach_existing_budget_comparisons(metric: str) -> None:
    large = 10**1000
    sample = replace(_sample(), **{metric: large})
    result = PerformanceGate().evaluate(sample)
    if metric == "fps":
        assert result.passed
        assert result.violations == ()
    else:
        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].metric == metric
        assert result.violations[0].actual == large
    receipt = PerformanceReceiptBuilder().build(sample, result)
    assert json.loads(receipt.to_json())["sample"][metric] == large


def test_finite_nonauthoritative_timing_keeps_existing_budget_semantics() -> None:
    sample = replace(
        _sample(), fps=0, frame_time_ms=9999,
        timing_measurement_authoritative=False,
    )
    assert PerformanceGate().evaluate(sample).passed
    authoritative = PerformanceGate().evaluate(
        replace(sample, timing_measurement_authoritative=True)
    )
    assert not authoritative.passed
    assert {violation.metric for violation in authoritative.violations} == {
        "fps", "frame_time_ms",
    }
