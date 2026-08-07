from pathlib import Path
import json
import pytest

from aios.three_d_web import (
    AssetKind, SceneAsset, SceneZone, ThreeDProjectPlanner, ThreeDRuntimeScaffoldBuilder,
)
from aios.three_d_web.scaffold import RuntimeScaffold, ScaffoldFile


def _blueprint():
    return ThreeDProjectPlanner().plan(
        project_id="orbital_expo",
        title="Orbital Expo",
        objective="Explore interactive spatial product zones.",
        zones=(
            SceneZone("launch", "Launch", (0, 0, 0), 4, ("hub",)),
            SceneZone("lab", "Lab", (15, 0, -8), 5, ("lab",)),
        ),
        assets=(
            SceneAsset("hub", AssetKind.GLB, "assets/hub.glb", lod_group="hub"),
            SceneAsset("lab", AssetKind.GLTF, "assets/lab.gltf", lod_group="lab"),
        ),
    )


def test_runtime_scaffold_contains_complete_r3f_world_architecture():
    scaffold = ThreeDRuntimeScaffoldBuilder().build(_blueprint())
    files = scaffold.as_mapping()
    package = json.loads(files["package.json"])
    assert {"three", "@react-three/fiber", "@react-three/drei", "zustand"}.issubset(package["dependencies"])
    assert "<Canvas" in files["src/App.tsx"]
    assert "<PlayerController" in files["src/scene/World.tsx"]
    assert "<CameraController" in files["src/scene/World.tsx"]
    assert "targetZone" in files["src/state/worldStore.ts"]
    assert "Ray" not in files["src/controllers/PlayerController.tsx"]  # raycast remains R3F pointer-event driven.


def test_blueprint_generation_is_deterministic_and_preserves_zones_assets():
    builder = ThreeDRuntimeScaffoldBuilder()
    first = builder.build(_blueprint()).as_mapping()["src/generated/blueprint.ts"]
    second = builder.build(_blueprint()).as_mapping()["src/generated/blueprint.ts"]
    assert first == second
    assert '"launch"' in first and '"lab"' in first
    assert '"/assets/hub.glb"' in first and '"/assets/lab.gltf"' in first


def test_scaffold_materializes_only_inside_destination(tmp_path: Path):
    scaffold = ThreeDRuntimeScaffoldBuilder().build(_blueprint())
    written = ThreeDRuntimeScaffoldBuilder().materialize(scaffold, tmp_path / "project")
    assert len(written) == len(scaffold.files)
    assert (tmp_path / "project/src/scene/World.tsx").is_file()
    assert all((tmp_path / "project") in path.parents for path in written)


def test_scaffold_rejects_traversal_and_duplicates():
    with pytest.raises(ValueError):
        RuntimeScaffold("x", (ScaffoldFile("../escape.ts", "x"),)).validate()
    with pytest.raises(ValueError):
        RuntimeScaffold("x", (ScaffoldFile("package.json", "a"), ScaffoldFile("package.json", "b"))).validate()


def test_runtime_includes_manual_assisted_touch_pointer_wheel_and_html_overlay():
    files = ThreeDRuntimeScaffoldBuilder().build(_blueprint()).as_mapping()
    player = files["src/controllers/PlayerController.tsx"]
    controls = files["src/controllers/ResponsiveControls.tsx"]
    overlay = files["src/overlays/ContentOverlay.tsx"]
    assert all(token in player for token in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "AUTO_SPEED"))
    assert "pointerdown" in controls and "wheel" in controls
    assert "touch-pad" in overlay and "setTarget" in overlay and "aria-live" in overlay
