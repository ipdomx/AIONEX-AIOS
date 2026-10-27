"""Actual 4x CPU-throttled low-power 3D browser readiness budget contract."""
from __future__ import annotations

import pytest

from aios.three_d_web import PerformanceProfile
from app.services.three_d_project_delivery import _browser_ready_timeout_seconds


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (PerformanceProfile.DESKTOP, 35),
        (PerformanceProfile.MOBILE, 35),
        (PerformanceProfile.LOW_POWER, 80),
    ],
)
def test_three_d_readiness_budget_preserves_real_low_power_browser_checks(
    profile: PerformanceProfile, expected: int,
) -> None:
    assert _browser_ready_timeout_seconds(profile) == expected
