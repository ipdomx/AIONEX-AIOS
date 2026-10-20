"""Registered LOD selection and the matching low-power asset budget boundary."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from aios.three_d_web.contracts import (
    AssetKind, PerformanceProfile, SceneAsset, SceneZone, ThreeDProjectPlanner,
)
from aios.three_d_web.lifecycle import (
    ApprovalDecision, LifecycleInputs, LifecycleStage, ThreeDProjectLifecycle,
)
from aios.three_d_web.scaffold import RuntimeScaffold, ThreeDRuntimeScaffoldBuilder


def variants(group="hero"):
    return tuple(
        SceneAsset(
            f"{group}-{profile.value}", AssetKind.GLB,
            f"public/assets/{group}-{profile.value}.glb",
            lod_group=group, lod_profile=profile,
        )
        for profile in PerformanceProfile
    )


def blueprint(assets, references=None):
    return ThreeDProjectPlanner().plan(
        project_id="profile-assets", title="Profile assets", objective="Select a registered model for each device.",
        assets=assets,
        zones=(SceneZone("home", "Home", (0, 0, 0), 4,
                         tuple(references if references is not None else (asset.asset_id for asset in assets))),),
    )


def write_triangle_glb(path, *, binary_bytes=44):
    """One valid triangle, with optional unused BIN padding for a real byte-budget test."""
    binary = struct.pack("<9f3H2x", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    binary += b"\0" * (binary_bytes - len(binary))
    payload = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    raw = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    raw += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    raw += struct.pack("<II", len(binary), 0x004E4942) + binary
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


class ProfileAssetContracts(unittest.TestCase):
    def test_default_and_positional_constructors_preserve_legacy_groups(self):
        original = SceneAsset("original", AssetKind.GLB, "assets/original.glb", True, True, "legacy", "a" * 64)
        second = SceneAsset("second", AssetKind.GLB, "assets/second.glb", lod_group="legacy")
        self.assertIsNone(original.lod_profile)
        self.assertEqual(original.checksum, "a" * 64)
        blueprint((original, second)).validate()

    def test_complete_group_can_be_referenced_by_one_registered_member(self):
        assets = variants()
        bp = blueprint(assets, ["hero-desktop"])
        bp.validate()
        source = ThreeDRuntimeScaffoldBuilder()._blueprint_source(bp)
        for profile in PerformanceProfile:
            self.assertIn(f'"lodProfile": "{profile.value}"', source)
            self.assertIn(f'"/assets/hero-{profile.value}.glb"', source)

    def test_partial_duplicate_and_mixed_groups_fail_before_source_generation(self):
        complete = variants()
        cases = {
            "missing": complete[:-1],
            "duplicate": complete + (replace(complete[0], asset_id="duplicate"),),
            "mixed": complete + (SceneAsset("unprofiled", AssetKind.GLB, "assets/legacy.glb", lod_group="hero"),),
        }
        for label, assets in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "exactly one model"):
                blueprint(assets)

    def test_profile_requires_valid_group_kind_and_enum(self):
        original = variants()[0]
        cases = [
            replace(original, lod_group=None), replace(original, lod_group=" "),
            replace(original, lod_profile="desktop"), replace(original, lod_profile=True),
            replace(original, kind=AssetKind.TEXTURE, path="assets/hero.png"),
        ]
        for asset in cases:
            with self.subTest(asset=asset), self.assertRaises(ValueError):
                asset.validate()

    def test_scaffold_requires_the_selector_imported_by_its_client(self):
        scaffold = ThreeDRuntimeScaffoldBuilder().build(blueprint(variants()))
        scaffold.validate()
        missing_selector = RuntimeScaffold(
            scaffold.project_id,
            tuple(item for item in scaffold.files if item.path != "src/runtime/assets.ts"),
        )
        with self.assertRaisesRegex(ValueError, "src/runtime/assets.ts"):
            missing_selector.validate()


NODE = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
NODE_STRIPS_TYPES = bool(NODE) and subprocess.run(
    [NODE, "--experimental-strip-types", "--version"], capture_output=True, timeout=10,
).returncode == 0


class GeneratedProfileSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NODE_STRIPS_TYPES:
            message = "Node with native TypeScript stripping is required for generated-client execution"
            if os.environ.get("CI", "").lower() == "true":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)

    def run_client(self, bp, assertions):
        builder = ThreeDRuntimeScaffoldBuilder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"assets.mts").write_text(builder._asset_selection(), encoding="utf-8")
            (root/"blueprint.mts").write_text(builder._blueprint_source(bp), encoding="utf-8")
            script = '''import assert from "node:assert/strict";
import { blueprint } from "./blueprint.mts";
import { selectZoneAssets, usesLowPowerProxy } from "./assets.mts";
''' + assertions
            (root/"check.mts").write_text(script, encoding="utf-8")
            completed = subprocess.run(
                [NODE, "--experimental-strip-types", str(root/"check.mts")],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_each_profile_selects_one_original_registered_path_without_mutation(self):
        self.run_client(blueprint(variants()), '''
const before = JSON.stringify(blueprint);
for (const profile of ["desktop", "mobile", "low_power"]) {
  const selected = selectZoneAssets(blueprint.assets, blueprint.zones[0].assetIds, profile);
  assert.deepEqual(selected.map(asset => asset.id), [`hero-${profile}`]);
  assert.equal(selected[0].path, `/assets/hero-${profile}.glb`);
  assert.equal(selected[0], blueprint.assets.find(asset => asset.id === `hero-${profile}`));
  assert.equal(usesLowPowerProxy(selected[0], profile), false);
}
assert.equal(JSON.stringify(blueprint), before);
''')

    def test_zone_references_resolve_only_their_groups_and_keep_legacy_assets(self):
        legacy = SceneAsset("legacy", AssetKind.GLB, "assets/legacy.glb", lod_group="old-group")
        assets = (*variants(), *variants("other"), legacy)
        self.run_client(blueprint(assets, ["hero-desktop", "hero-mobile", "legacy"]), '''
const selected = selectZoneAssets(blueprint.assets, blueprint.zones[0].assetIds, "low_power");
assert.deepEqual(selected.map(asset => asset.id), ["hero-low_power", "legacy"]);
assert.equal(usesLowPowerProxy(selected[0], "low_power"), false);
assert.equal(usesLowPowerProxy(selected[1], "low_power"), true);
assert.equal(usesLowPowerProxy({...selected[1], lazy:false}, "low_power"), false);
assert.equal(usesLowPowerProxy(selected[1], "mobile"), false);
assert.deepEqual(selectZoneAssets(blueprint.assets, [], "desktop"), []);
''')

    def test_legacy_groups_without_profiles_still_keep_all_referenced_members(self):
        assets = (
            SceneAsset("one", AssetKind.GLB, "assets/one.glb", lod_group="legacy"),
            SceneAsset("two", AssetKind.GLTF, "assets/two.gltf", lod_group="legacy"),
        )
        self.run_client(blueprint(assets), '''
for (const profile of ["desktop", "mobile", "low_power"]) {
  assert.deepEqual(selectZoneAssets(blueprint.assets, ["one","two"], profile).map(asset => asset.id), ["one","two"]);
}
''')

    def test_missing_duplicate_or_invalid_client_variant_never_falls_back(self):
        self.run_client(blueprint(variants(), ["hero-desktop"]), '''
const registry = blueprint.assets;
assert.throws(() => selectZoneAssets(registry.slice(0, 2), ["hero-desktop"], "low_power"), /exactly one/);
assert.throws(() => selectZoneAssets([...registry, {...registry[0],id:"duplicate"}], ["hero-desktop"], "desktop"), /exactly one/);
assert.throws(() => selectZoneAssets(registry.map(asset => asset.lodProfile === "mobile" ? {...asset,kind:"texture"} : asset), ["hero-desktop"], "mobile"), /exactly one/);
assert.throws(() => selectZoneAssets(registry, ["hero-desktop"], "unknown"), /Unknown runtime profile/);
''')


class LowPowerVariantBudget(unittest.TestCase):
    def run_lifecycle(self, assets, *, oversized_id):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for asset in assets:
                write_triangle_glb(root/asset.path, binary_bytes=7 * 1024 * 1024 if asset.asset_id == oversized_id else 44)
            inputs = LifecycleInputs(
                blueprint=blueprint(assets), project_root=root, browser_runs=(), performance_samples=(),
                production_build_passed=False, deployment_receipt=None, rollback_receipt=None,
                approval=ApprovalDecision(False, None, "Unit test does not authorize release"),
            )
            return ThreeDProjectLifecycle().run(inputs)

    def test_oversized_explicit_lazy_low_power_variant_fails_actual_asset_budget(self):
        assets = variants()
        self.assertTrue(next(a for a in assets if a.lod_profile == PerformanceProfile.LOW_POWER).lazy)
        result = self.run_lifecycle(assets, oversized_id="hero-low_power")
        violations = [r for r in result.remediation if r.stage == LifecycleStage.ASSETS]
        self.assertTrue(any(r.code == "asset-bytes" and "hero-low_power" in r.message and "low_power" in r.message for r in violations))
        self.assertFalse(any("desktop" in r.message or "mobile" in r.message for r in violations))
        self.assertTrue(any(e.stage == LifecycleStage.ASSETS and e.status == "failed" for e in result.evidence))
        self.assertFalse(result.release_ready)
        self.assertEqual(len(result.asset_manifest.entries), 3)
        self.assertTrue(all(entry.bytes > 0 for entry in result.asset_manifest.entries))

    def test_legacy_lazy_proxy_still_excludes_that_asset_from_low_power_budget(self):
        asset = SceneAsset("legacy", AssetKind.GLB, "assets/legacy.glb")
        result = self.run_lifecycle((asset,), oversized_id="legacy")
        self.assertFalse(any(r.stage == LifecycleStage.ASSETS for r in result.remediation))
        self.assertTrue(any(e.stage == LifecycleStage.ASSETS and e.status == "passed" for e in result.evidence))
        self.assertFalse(result.release_ready)


if __name__ == "__main__":
    unittest.main(verbosity=2)
