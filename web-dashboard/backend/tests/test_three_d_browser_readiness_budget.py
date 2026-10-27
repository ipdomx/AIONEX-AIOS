"""The low-power software-rendered WebGL QA wait is distinct from performance SLOs."""

from aios.three_d_web import PerformanceProfile
from app.services.three_d_project_delivery import _browser_ready_wait_seconds


def test_3d_cpu_throttled_scene_boot_budget_is_profile_specific():
    assert _browser_ready_wait_seconds(PerformanceProfile.DESKTOP) == 35
    assert _browser_ready_wait_seconds(PerformanceProfile.MOBILE) == 35
    assert _browser_ready_wait_seconds(PerformanceProfile.LOW_POWER) == 80


def test_these_are_readiness_waits_not_automatic_release_approval():
    assert _browser_ready_wait_seconds(PerformanceProfile.LOW_POWER) > 35
    assert _browser_ready_wait_seconds(PerformanceProfile.MOBILE) < 80
