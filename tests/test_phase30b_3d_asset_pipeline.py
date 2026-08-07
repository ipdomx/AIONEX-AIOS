from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct

import pytest

from aios.three_d_web import AssetKind, PerformanceProfile, SceneAsset
from aios.three_d_web.assets import (
    ArtifactManifestBuilder,
    AssetBudget,
    AssetBudgetGate,
    AssetInspector,
    CompressionKind,
    OptimizationPlanner,
)


def _glb(path: Path, *, extensions=(), index_count=300, textures=1) -> None:
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{}],
        "nodes": [{}],
        "meshes": [{"primitives": [{"indices": 0}]}],
        "accessors": [{"count": index_count}],
        "materials": [{}],
        "textures": [{} for _ in range(textures)],
        "images": [{} for _ in range(textures)],
        "animations": [{}],
        "extensionsUsed": list(extensions),
    }
    payload = json.dumps(doc, separators=(",", ":")).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    raw = struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
    raw += struct.pack("<II", len(payload), 0x4E4F534A) + payload
    path.write_bytes(raw)


def test_glb_inspection_extracts_counts_triangles_compression_and_checksum(tmp_path: Path) -> None:
    _glb(tmp_path / "world.glb", extensions=("EXT_meshopt_compression", "KHR_texture_basisu"), index_count=900)
    asset = SceneAsset("world", AssetKind.GLB, "world.glb")
    meta = AssetInspector().inspect(asset, tmp_path)
    assert meta.metadata_available is True
    assert (meta.meshes, meta.materials, meta.textures, meta.animations, meta.triangles) == (1, 1, 1, 1, 300)
    assert {CompressionKind.MESHOPT, CompressionKind.KTX2, CompressionKind.BASIS}.issubset(meta.compression)
    assert len(meta.checksum_sha256) == 64


def test_gltf_and_non_model_assets_are_inspected_without_execution(tmp_path: Path) -> None:
    (tmp_path / "scene.gltf").write_text(json.dumps({"asset": {"version": "2.0"}, "meshes": []}), encoding="utf-8")
    (tmp_path / "albedo.png").write_bytes(b"not-decoded-by-inspector")
    gltf = AssetInspector().inspect(SceneAsset("scene", AssetKind.GLTF, "scene.gltf"), tmp_path)
    texture = AssetInspector().inspect(SceneAsset("albedo", AssetKind.TEXTURE, "albedo.png"), tmp_path)
    assert gltf.metadata_available and gltf.meshes == 0
    assert texture.metadata_available is False and texture.bytes == len(b"not-decoded-by-inspector")


def test_asset_path_cannot_escape_project_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "escape.glb"
    _glb(outside)
    with pytest.raises(ValueError):
        AssetInspector().inspect(SceneAsset("bad", AssetKind.GLB, "../escape.glb"), tmp_path)


def test_budget_gate_is_profile_specific_and_fail_closed_on_known_metrics(tmp_path: Path) -> None:
    _glb(tmp_path / "heavy.glb", index_count=30_000)
    meta = AssetInspector().inspect(SceneAsset("heavy", AssetKind.GLB, "heavy.glb"), tmp_path)
    tiny = AssetBudget(max_asset_bytes=10_000_000, max_total_bytes=10_000_000, max_triangles=5_000)
    result = AssetBudgetGate({PerformanceProfile.MOBILE: tiny}).evaluate([meta], PerformanceProfile.MOBILE)
    assert result.passed is False
    assert any(v.metric == "triangles" and v.asset_id == "heavy" for v in result.violations)


def test_optimization_plan_covers_mesh_texture_and_lod_without_false_execution_claim(tmp_path: Path) -> None:
    _glb(tmp_path / "raw.glb", index_count=900, textures=2)
    meta = AssetInspector().inspect(SceneAsset("raw", AssetKind.GLB, "raw.glb"), tmp_path)
    plan = OptimizationPlanner().plan([meta], PerformanceProfile.MOBILE)
    actions = {item.action for item in plan.actions}
    assert {"mesh-compression", "generate-lod", "texture-compression"}.issubset(actions)
    assert all("executed" not in item.reason.lower() for item in plan.actions)


def test_manifest_is_deterministic_checksum_addressed_and_detects_tampering(tmp_path: Path) -> None:
    _glb(tmp_path / "world.glb", index_count=300)
    (tmp_path / "tone.ogg").write_bytes(b"audio")
    assets = (
        SceneAsset("world", AssetKind.GLB, "world.glb", checksum=None, lod_group="world"),
        SceneAsset("tone", AssetKind.AUDIO, "tone.ogg"),
    )
    builder = ArtifactManifestBuilder()
    first = builder.build(assets, tmp_path)
    second = builder.build(reversed(assets), tmp_path)
    assert first.to_json() == second.to_json()
    assert len(first.aggregate_sha256) == 64 and first.total_bytes > 0
    assert builder.verify(first, tmp_path) == ()
    (tmp_path / "tone.ogg").write_bytes(b"tampered")
    assert builder.verify(first, tmp_path) == ("tone",)
