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
    strict_step = re.search(r"^RUN .*handler\.build_model\(\).*strict load: PASS", DOCKERFILE, re.M)
    assert strict_step, "the image build must strictly load the pinned checkpoint"
    # It runs after USER aionex, i.e. with the same identity as the RunPod worker.
    assert DOCKERFILE.index("USER aionex") < strict_step.start()


def test_model_assets_are_world_readable_but_not_writable() -> None:
    assert "chmod -R a+rX,go-w /opt/triposr /models" in DOCKERFILE
