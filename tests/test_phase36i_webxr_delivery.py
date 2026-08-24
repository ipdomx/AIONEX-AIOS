from __future__ import annotations

import json

from aios.three_d_web import (
    AssetKind,
    SceneAsset,
    SceneZone,
    ThreeDProjectPlanner,
    ThreeDRuntimeScaffoldBuilder,
)
from aios.three_d_web.expansion import (
    DeliveryBoundary,
    InteractiveProductionPlanner,
    InteractiveTarget,
    THREE_JS_PRODUCTION_BASELINE,
)


def _blueprint():
    return ThreeDProjectPlanner().plan(
        project_id="phase36i_xr",
        title="Phase 36I XR",
        objective="Validate governed AR and VR delivery.",
        zones=(SceneZone("origin", "Origin", (0, 0, 0), 4, ("scene",)),),
        assets=(SceneAsset("scene", AssetKind.GLB, "assets/scene.glb", lod_group="scene"),),
    )


def test_runtime_scaffold_pins_current_three_and_contains_fail_closed_xr_bridge() -> None:
    files = ThreeDRuntimeScaffoldBuilder().build(_blueprint()).as_mapping()
    package = json.loads(files["package.json"])
    lock = json.loads(files["package-lock.json"])
    assert package["dependencies"]["three"] == "0.185.1"
    assert package["devDependencies"]["@types/three"] == "0.185.4"
    assert lock["packages"]["node_modules/three"]["version"] == "0.185.1"
    assert lock["packages"]["node_modules/@types/three"]["version"] == "0.185.4"
    assert THREE_JS_PRODUCTION_BASELINE == "0.185.1"
    assert "<WebXRBridge" in files["src/scene/World.tsx"]
    assert "<XRControls" in files["src/App.tsx"]
    bridge = files["src/xr/WebXRBridge.tsx"]
    controls = files["src/xr/XRControls.tsx"]
    assert "window.isSecureContext" in bridge
    assert 'isSessionSupported("immersive-ar")' in bridge
    assert 'isSessionSupported("immersive-vr")' in bridge
    assert "xr-unavailable" in bridge and "xr-mode-unsupported" in bridge
    assert "XR device/runtime required" in controls
    assert "requestSession" in bridge


def test_xr_plans_require_https_and_physical_device_acceptance_remains_explicit() -> None:
    planner = InteractiveProductionPlanner(current_three_js="0.185.1")
    for target in (InteractiveTarget.WEBXR_AR, InteractiveTarget.WEBXR_VR):
        plan = planner.plan(target)
        assert plan.requires_secure_context is True
        assert plan.requires_xr_device_acceptance is True
        assert plan.three_js_migration_required is False
    boundary = DeliveryBoundary("https://ai.vip-e.net", True).snapshot()
    assert boundary["secure_context"] is True
    assert boundary["https_webxr_delivery_supported"] is True
    assert boundary["direct_udp_turn_certified_by_tunnel"] is False
