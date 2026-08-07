import pytest
from aios.three_d_web import (
    AssetKind, InteractionMode, PerformanceProfile, SceneAsset, SceneZone, ThreeDProjectPlanner,
)


def test_planner_builds_complete_three_d_web_blueprint():
    planner = ThreeDProjectPlanner()
    bp = planner.plan(
        project_id="world-1", title="Explorable World", objective="Build an interactive 3D product world",
        assets=[SceneAsset("hub", AssetKind.GLB, "assets/hub.glb")],
        zones=[SceneZone("home", "Home", (0, 0, 0), 8, ("hub",), frozenset({InteractionMode.RAYCAST}))],
    )
    assert PerformanceProfile.DESKTOP in bp.performance_profiles
    assert PerformanceProfile.MOBILE in bp.performance_profiles
    assert InteractionMode.AUTO_TRAVEL in bp.interactions
    assert "visual QA evidence" in bp.requirements
    assert len(bp.acceptance_criteria) >= 6


def test_asset_paths_are_traversal_safe_and_type_checked():
    with pytest.raises(ValueError):
        SceneAsset("x", AssetKind.GLB, "../secret.glb").validate()
    with pytest.raises(ValueError):
        SceneAsset("x", AssetKind.GLB, "assets/x.png").validate()


def test_zone_must_reference_registered_assets():
    with pytest.raises(ValueError, match="unknown assets"):
        ThreeDProjectPlanner().plan(
            project_id="x", title="x", objective="x",
            zones=[SceneZone("z", "Z", (0,0,0), 1, ("missing",))],
        )
