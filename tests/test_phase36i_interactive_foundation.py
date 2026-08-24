from __future__ import annotations

import pytest

from aios.three_d_web.expansion import (
    BLENDER_PRODUCTION_BASELINE,
    THREE_JS_PRODUCTION_BASELINE,
    DeliveryBoundary,
    InteractiveFoundationError,
    InteractiveProductionPlanner,
    InteractiveTarget,
    RendererProbe,
)


def test_all_phase36i_families_have_deterministic_plans() -> None:
    planner = InteractiveProductionPlanner(current_three_js="0.180.0")
    plans = planner.all_plans()
    assert {item.target for item in plans} == set(InteractiveTarget)
    assert len({item.template for item in plans}) == len(InteractiveTarget)
    assert all(item.outputs for item in plans)
    assert all(item.compression_required for item in plans)
    assert all(item.snapshot()["runtime_executed"] is False for item in plans)


def test_webxr_requires_secure_context_device_acceptance_lod_and_compression() -> None:
    planner = InteractiveProductionPlanner(current_three_js="0.180.0")
    for target in (InteractiveTarget.WEBXR_AR, InteractiveTarget.WEBXR_VR):
        plan = planner.plan(target)
        assert plan.requires_secure_context is True
        assert plan.requires_xr_device_acceptance is True
        assert plan.requires_blender is True
        assert plan.requires_three_js is True
        assert plan.lod_required is True
        assert plan.compression_required is True
        assert plan.target_three_js == THREE_JS_PRODUCTION_BASELINE
        assert plan.three_js_migration_required is True


def test_2d_and_vfx_plans_do_not_fake_3d_renderer_execution() -> None:
    planner = InteractiveProductionPlanner(current_three_js="0.180.0")
    animation = planner.plan(InteractiveTarget.TWO_D_ANIMATION)
    game = planner.plan(InteractiveTarget.TWO_D_GAME)
    vfx = planner.plan(InteractiveTarget.VFX_COMPOSITE)
    assert animation.requires_blender is False
    assert game.requires_blender is False
    assert vfx.requires_blender is False
    assert animation.requires_video_compositor is True
    assert vfx.requires_video_compositor is True
    assert game.requires_video_compositor is False


def test_application_tunnel_is_https_delivery_evidence_not_turn_certification() -> None:
    boundary = DeliveryBoundary(
        public_origin="https://ai.vip-e.net",
        application_tunnel_present=True,
    ).snapshot()
    assert boundary["secure_context"] is True
    assert boundary["https_webgl_delivery_supported"] is True
    assert boundary["https_webxr_delivery_supported"] is True
    assert boundary["direct_udp_turn_certified_by_tunnel"] is False


def test_delivery_boundary_rejects_insecure_or_credentialed_origins() -> None:
    with pytest.raises(InteractiveFoundationError, match="HTTPS"):
        DeliveryBoundary(public_origin="http://ai.vip-e.net", application_tunnel_present=True)
    with pytest.raises(InteractiveFoundationError, match="credentials"):
        DeliveryBoundary(public_origin="https://user:pass@ai.vip-e.net", application_tunnel_present=True)


def test_renderer_baseline_is_fail_closed_for_old_blender() -> None:
    old = RendererProbe(executable="/usr/bin/blender", version="4.0.2")
    current = RendererProbe(executable="/opt/blender/blender", version=BLENDER_PRODUCTION_BASELINE)
    assert old.production_approved is False
    assert current.production_approved is True
    assert old.snapshot()["network_used"] is False
