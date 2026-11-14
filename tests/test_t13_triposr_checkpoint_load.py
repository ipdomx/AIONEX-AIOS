"""T-13: the pinned TripoSR checkpoint must load under the installed transformers.

The first live RunPod job on the 01c7cf7d image failed because transformers 5
renamed the ViT encoder parameters, and model.safetensors was 0600 root so the
non-root worker could not read it. These tests pin both fixes without needing
torch: the remap function is extracted from handler.py and run on plain keys.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIPOSR = ROOT / "infra/runpod/triposr"
HANDLER = (TRIPOSR / "handler.py").read_text()
DOCKERFILE = (TRIPOSR / "Dockerfile").read_text()


def _remap():
    tree = ast.parse(HANDLER)
    keep = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == "remap_checkpoint_keys")
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in {"_VIT_PREFIX", "_VIT_V5_RENAMES"} for t in node.targets)
        )
    ]
    namespace: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "handler_remap", "exec"), namespace)
    return namespace["remap_checkpoint_keys"]


def _v4_block(n: int) -> list[str]:
    base = f"image_tokenizer.model.encoder.layer.{n}."
    parts = [
        "attention.attention.query",
        "attention.attention.key",
        "attention.attention.value",
        "attention.output.dense",
        "intermediate.dense",
        "output.dense",
        "layernorm_before",
        "layernorm_after",
    ]
    return [base + p + s for p in parts for s in (".weight", ".bias")]


def _v5_block(n: int) -> list[str]:
    base = f"image_tokenizer.model.layers.{n}."
    parts = [
        "attention.q_proj",
        "attention.k_proj",
        "attention.v_proj",
        "attention.o_proj",
        "mlp.fc1",
        "mlp.fc2",
        "layernorm_before",
        "layernorm_after",
    ]
    return [base + p + s for p in parts for s in (".weight", ".bias")]


def test_v4_checkpoint_keys_map_exactly_onto_v5_vit_module() -> None:
    remap = _remap()
    shared = ["image_tokenizer.model.embeddings.cls_token", "backbone.proj_in.weight"]
    state = {k: k for n in range(12) for k in _v4_block(n)} | {k: k for k in shared}
    expected = [k for n in range(12) for k in _v5_block(n)] + shared
    out = remap(state, expected)
    assert set(out) == set(expected)
    # Values follow their key: layer 3 query weight becomes layer 3 q_proj weight.
    assert out["image_tokenizer.model.layers.3.attention.q_proj.weight"] == (
        "image_tokenizer.model.encoder.layer.3.attention.attention.query.weight"
    )
    assert out["image_tokenizer.model.layers.7.mlp.fc2.bias"] == "image_tokenizer.model.encoder.layer.7.output.dense.bias"


def test_remap_is_a_no_op_when_installed_transformers_still_uses_v4_names() -> None:
    remap = _remap()
    state = {k: k for k in _v4_block(0)}
    assert remap(state, list(state)) is state


def test_worker_loads_strictly_and_build_proves_it() -> None:
    assert "strict=True" in HANDLER
    assert "_MODEL = build_model()" in HANDLER
    strict_step = re.search(r"^RUN .*handler\.build_model\(\).*strict load.*: PASS", DOCKERFILE, re.M)
    assert strict_step, "the image build must strictly load the pinned checkpoint"
    # It runs after USER aionex, i.e. with the same identity as the RunPod worker.
    assert DOCKERFILE.index("USER aionex") < strict_step.start()


def test_background_removal_uses_only_the_baked_u2net_model() -> None:
    # rembg 2.0.87 defaults to "bria-rmbg", which is not baked; the second live job
    # (2026-11-13) failed trying to download it into the read-only /models.
    assert 'rembg.new_session("u2net")' in HANDLER
    assert "rembg.new_session()" not in HANDLER
    assert "type(handler.get_rembg()).__name__ == 'U2netSession'" in DOCKERFILE


def test_model_assets_are_world_readable_but_not_writable() -> None:
    assert "chmod -R a+rX,go-w /opt/triposr /models" in DOCKERFILE


# ----------------------------------------------------------------- Hunyuan3D (T-18)
HUNYUAN = ROOT / "infra/runpod/hunyuan3d"
HY_DOCKERFILE = (HUNYUAN / "Dockerfile").read_text()


def _apply_hunyuan_dinov2_patch(tmp_path: Path) -> dict:
    import importlib.util
    import sys

    pipelines = tmp_path / "hy3dshape/hy3dshape/pipelines.py"
    pipelines.parent.mkdir(parents=True)
    pipelines.write_text(
        "import os\n\n\ndef retrieve_timesteps(x):\n    return x\n\n\n"
        "class Pipe:\n    def load(self, conditioner, ckpt):\n"
        "        conditioner.load_state_dict(ckpt['conditioner'])\n"
    )
    spec = importlib.util.spec_from_file_location("hy_patch_under_test", HUNYUAN / "patch_hunyuan_runtime.py")
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["patch_hunyuan_runtime.py", str(tmp_path)]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    module.patch_dinov2_v5_names()
    namespace: dict = {}
    exec(compile(pipelines.read_text(), str(pipelines), "exec"), namespace)
    return namespace


def test_hunyuan_conditioner_keys_follow_transformers_v5_dinov2_names(tmp_path: Path) -> None:
    ns = _apply_hunyuan_dinov2_patch(tmp_path)
    remap = ns["_aionex_remap_dinov2"]
    base = "main_image_encoder.model.encoder.layer.21.attention."
    state = {
        base + "attention.query.weight": 1,
        base + "attention.key.bias": 2,
        base + "attention.value.weight": 3,
        base + "output.dense.bias": 4,
        "main_image_encoder.model.encoder.layer.21.mlp.fc1.weight": 5,
        "main_image_encoder.model.embeddings.cls_token": 6,
    }
    expected = [
        base + "q_proj.weight",
        base + "k_proj.bias",
        base + "v_proj.weight",
        base + "o_proj.bias",
        "main_image_encoder.model.encoder.layer.21.mlp.fc1.weight",
        "main_image_encoder.model.embeddings.cls_token",
    ]
    out = remap(state, expected)
    assert set(out) == set(expected)
    assert out[base + "o_proj.bias"] == 4
    # No-op while the installed transformers still uses the 4.x names.
    assert remap(state, list(state)) is state


def test_hunyuan_patch_is_wired_and_release_build_strictly_loads_weights() -> None:
    patch = (HUNYUAN / "patch_hunyuan_runtime.py").read_text()
    main_body = patch[patch.index("def main() -> None:"):]
    assert "patch_dinov2_v5_names()" in main_body
    release = HY_DOCKERFILE[HY_DOCKERFILE.index("FROM runtime AS release"):]
    assert "Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(" in release
    assert 'device="cpu"' in release
    assert "Hunyuan checkpoint strict load (shape + paint) and remesh/UV: PASS" in release
    assert "remesh_mesh(" in release and "mesh_uv_wrap(" in release
    assert "multiviewDiffusionNet(SimpleNamespace(" in release
    # The runtime stage switched to the non-root user; release must not switch back.
    assert "USER root" not in release


def test_hunyuan_paint_pipeline_is_built_from_local_components() -> None:
    # model_index.json: "unet": ["modules", "UNet2p5DConditionModel"]. diffusers 0.42
    # from_pretrained rejected the passed plain-torch unet (live job 2026-11-13), so the
    # pipeline is constructed from its components, each from its own baked folder.
    patch = (HUNYUAN / "patch_hunyuan_runtime.py").read_text()
    block = patch[patch.index("pipeline = HunyuanPaintPipeline(\\n"):patch.index("# 2. UNet weights")]
    for component in ("vae", "text_encoder", "tokenizer", "scheduler", "feature_extractor"):
        assert f'os.path.join(model_path, \\"{component}\\")' in block, component
    assert "unet=unet" in block
    assert "HunyuanPaintPipeline.from_pretrained(" not in patch
    assert 'sys.modules.setdefault(\\"modules\\"' not in patch
    assert "trust_remote_code" not in patch.split("# 7. Post-conditions")[0]


def test_hunyuan_remesh_does_not_need_open3d() -> None:
    # trimesh.simplify_quadric_decimation imports open3d, which is not installed; the
    # third live job (2026-11-13) failed with ModuleNotFoundError: open3d.
    patch = (HUNYUAN / "patch_hunyuan_runtime.py").read_text()
    assert "simplify_quadric_decimation\\(target_count\\)" in patch
    assert "meshing_decimation_quadric_edge_collapse(targetfacenum=int(target_count)" in patch
    main_body = patch[patch.index("def main() -> None:"):]
    assert main_body.index("simplify_mesh_utils.py") < main_body.index("# 7. Post-conditions")
