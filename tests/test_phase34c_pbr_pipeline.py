from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = (ROOT / "infra/runpod/hunyuan3d/handler.py").read_text()
DOCKERFILE = (ROOT / "infra/runpod/hunyuan3d/Dockerfile").read_text()
BLENDER = (ROOT / "infra/runpod/hunyuan3d/phase34c_blender.py").read_text()


def test_full_pbr_pipeline_is_fail_closed_by_default():
    assert 'allow_shape_fallback", False' in HANDLER
    assert "if not allow_fallback" in HANDLER
    assert '"fallback_used": False' in HANDLER


def test_pipeline_requires_pbr_textures_and_material_validation():
    assert '"albedo"' in HANDLER
    assert '"metallic"' in HANDLER
    assert '"roughness"' in HANDLER
    assert "pbrMetallicRoughness" in HANDLER
    assert "optimized GLB has no PBR" in HANDLER


def test_blender_and_gltf_transform_are_real_pipeline_stages():
    assert '"blender", "--background"' in HANDLER
    assert '"gltf-transform", "optimize"' in HANDLER
    assert '"gltf-transform", "inspect"' in HANDLER
    assert "remove_doubles" in BLENDER
    assert "normals_make_consistent" in BLENDER


def test_compression_policy_is_explicit_and_compatible_by_default():
    assert 'compression_policy", "compat"' in HANDLER
    assert '{"compat", "meshopt"}' in HANDLER
    assert 'compress = "false" if policy == "compat" else "meshopt"' in HANDLER
    assert "@gltf-transform/cli@4.4.2" in DOCKERFILE


def test_model_dependencies_are_baked_for_no_runtime_downloads():
    assert "facebook/dinov2-giant" in DOCKERFILE
    assert "/models/dinov2-giant" in DOCKERFILE
    assert "multiview_pretrained_path" in DOCKERFILE


def test_manifest_records_quality_size_hash_and_stage_timings():
    for token in (
        "pre_optimization_bytes",
        "post_optimization_bytes",
        "optimization_ratio",
        "pbr_material_count",
        "texture_count",
        "sha256",
        "shape_seconds",
        "texture_seconds",
        "blender_seconds",
        "gltf_transform_seconds",
        "total_seconds",
    ):
        assert token in HANDLER


def test_serverless_handler_is_started():
    assert 'runpod.serverless.start({"handler": handler})' in HANDLER


def test_torchvision_compatibility_fix_precedes_paint_import():
    assert 'from torchvision_fix import apply_fix' in HANDLER
    assert HANDLER.index('apply_fix()') < HANDLER.index('from textureGenPipeline import')


def test_worker_cwd_matches_hunyuan_root_for_relative_assets():
    assert 'os.chdir(ROOT)' in HANDLER


def test_paint_keeps_real_mesh_utils_and_only_stubs_bpy_import():
    assert 'types.ModuleType("bpy")' in HANDLER
    assert 'types.ModuleType("DifferentiableRenderer.mesh_utils")' not in HANDLER
    assert 'load_mesh/save_mesh remain available' in HANDLER


def test_blender_runtime_includes_numpy():
    assert "blender python3-numpy" in DOCKERFILE
