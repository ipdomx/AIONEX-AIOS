from __future__ import annotations

from pathlib import Path

import pytest

from aios.three_d_web.blender_candidate import (
    AnimationPlan,
    Blender52CandidateRunner,
    BlenderCandidateError,
    BlenderScenePlan,
    EnvironmentPlan,
    PBRMaterialPlan,
)


def test_scene_plans_validate_material_animation_and_environment() -> None:
    BlenderScenePlan("scene-01").validate()
    with pytest.raises(BlenderCandidateError, match="material name"):
        PBRMaterialPlan(name="bad/name").validate()
    with pytest.raises(BlenderCandidateError, match="frame range"):
        AnimationPlan(frame_start=20, frame_end=10).validate()
    with pytest.raises(BlenderCandidateError, match="ground size"):
        EnvironmentPlan(ground_size=100).validate()


def test_destination_cannot_escape_workspace(tmp_path: Path) -> None:
    runner = Blender52CandidateRunner(executable="/bin/false", workspace_root=tmp_path / "safe")
    with pytest.raises(BlenderCandidateError, match="escapes"):
        runner.render(BlenderScenePlan("scene-01"), tmp_path / "escape")


def test_generated_script_is_offline_deterministic_and_exports_material_animation_environment(tmp_path: Path) -> None:
    plan = BlenderScenePlan("scene-01")
    script = Blender52CandidateRunner._script(plan, tmp_path / "scene.glb", tmp_path / "preview.png")
    for required in (
        "AIOSGeneratedTexture",
        "Principled BSDF",
        "keyframe_insert",
        "AIOS_Environment_Ground",
        "BLENDER_EEVEE",
        "export_scene.gltf",
        "AIOS_PHASE36I_SCENE_OK",
    ):
        assert required in script
    for forbidden in ("urllib", "requests", "httpx", "socket", "subprocess"):
        assert forbidden not in script


def test_artifact_snapshot_cannot_contain_provider_or_network_success_claims(tmp_path: Path) -> None:
    source = Path("src/aios/three_d_web/blender_candidate.py").read_text(encoding="utf-8")
    assert '"--offline-mode"' in source
    assert '"--disable-autoexec"' in source
    assert "network_used: bool = False" in source
    assert "provider_used: bool = False" in source
    assert "gpu_job_used: bool = False" in source
