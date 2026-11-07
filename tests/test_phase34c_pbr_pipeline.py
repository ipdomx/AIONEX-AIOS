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
    # FR-16D: pinned Blender binary, headless, no add-on/script auto-execution.
    assert 'BLENDER = "/opt/blender/blender"' in HANDLER
    assert 'BLENDER, "--background", "--factory-startup", "--disable-autoexec", "--offline-mode"' in HANDLER
    assert 'GLTF_TRANSFORM, "optimize"' in HANDLER
    assert 'GLTF_TRANSFORM, "inspect"' in HANDLER
    assert "remove_doubles" in BLENDER
    assert "normals_make_consistent" in BLENDER


def test_compression_policy_is_explicit_and_compatible_by_default():
    assert 'compression_policy", "compat"' in HANDLER
    assert '{"compat", "meshopt"}' in HANDLER
    assert 'compress = "false" if policy == "compat" else "meshopt"' in HANDLER
    lock = (ROOT / "infra/runpod/hunyuan3d/gltf-tools/package-lock.json").read_text()
    assert '"@gltf-transform/cli": "4.4.2"' in lock
    assert "npm ci --omit=dev --ignore-scripts" in DOCKERFILE


def test_model_dependencies_are_baked_for_no_runtime_downloads():
    weights = (ROOT / "infra/runpod/hunyuan3d/weights.lock.json").read_text()
    patch = (ROOT / "infra/runpod/hunyuan3d/patch_hunyuan_runtime.py").read_text()
    assert "facebook/dinov2-giant" in weights
    assert "611a9d42f2335e0f921f1e313ad3c1b7178d206d" in weights
    assert "/models/dinov2-giant" in patch + HANDLER
    assert "multiview_pretrained_path" in patch
    assert "fetch_weights.py" in DOCKERFILE


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


def test_basicsr_stack_and_its_torchvision_shim_are_gone():
    # FR-16D replaced realesrgan/basicsr (pickle torch.load, tb-nightly) with a
    # reviewed safetensors-only implementation, so the torchvision shim that
    # only basicsr needed is no longer imported.
    assert "torchvision_fix" not in HANDLER
    override = (ROOT / "infra/runpod/hunyuan3d/overrides/image_super_utils.py").read_text()
    assert "safetensors.torch.load_file" in override and "torch.load(" not in override
    lock = (ROOT / "infra/runpod/hunyuan3d/requirements.lock").read_text()
    for removed in ("basicsr", "realesrgan", "tb-nightly", "pytorch-lightning", "gradio"):
        assert f"\n{removed}==" not in lock


def test_worker_cwd_matches_hunyuan_root_for_relative_assets():
    assert 'os.chdir(ROOT)' in HANDLER


def test_paint_keeps_real_mesh_utils_and_only_stubs_bpy_import():
    assert 'types.ModuleType("bpy")' in HANDLER
    assert 'types.ModuleType("DifferentiableRenderer.mesh_utils")' not in HANDLER
    assert 'load_mesh/save_mesh remain available' in HANDLER


def test_blender_runtime_is_pinned_and_checksum_verified():
    assert "ARG BLENDER_VERSION=5.2.3" in DOCKERFILE
    assert "ARG BLENDER_SHA256=78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec" in DOCKERFILE
    assert 'sha256sum -c -' in DOCKERFILE
