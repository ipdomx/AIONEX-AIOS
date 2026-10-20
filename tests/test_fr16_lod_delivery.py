"""Offline delivery integration tests; these do not attest browser or device QA."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from aios.three_d_web import (
    ApprovalDecision, AssetKind, LifecycleInputs, PerformanceProfile,
    SceneAsset, SceneZone, ThreeDProjectLifecycle, ThreeDProjectPlanner,
)


@pytest.fixture
def delivery():
    path = (
        Path(__file__).resolve().parents[1]
        / "web-dashboard/backend/app/services/three_d_project_delivery.py"
    )
    spec = importlib.util.spec_from_file_location("fr16_lod_delivery_service", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _glb(
    triangles: int = 4, *, external: bool = False, padding_bytes: int = 0,
) -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": triangles * 3, "type": "SCALAR", "componentType": 5123}],
        "meshes": [{"primitives": [{"indices": 0}]}],
    }
    if external:
        document["images"] = [{"uri": "https://example.invalid/texture.png"}]
    payload = json.dumps(document).encode() + b" " * padding_bytes
    payload += b" " * (-len(payload) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload), len(payload), 0x4E4F534A) + payload


def _staging(tmp_path: Path, *, variants: bool = True):
    root = tmp_path / "staging"
    root.mkdir()
    files = {"scene.glb": _glb(1000)}
    if variants:
        files.update({"mobile.glb": _glb(400), "low.glb": _glb(100)})
    for name, content in files.items():
        (root / name).write_bytes(content)
    asset = {
        "artifact_id": "fixture", "provider": "local-fixture", "path": "scene.glb",
        "sha256": sha256(files["scene.glb"]).hexdigest(), "size_bytes": len(files["scene.glb"]),
    }
    if variants:
        asset["lod_variants"] = [
            {
                "profile": profile, "path": name,
                "sha256": sha256(files[name]).hexdigest(), "size_bytes": len(files[name]),
            }
            for profile, name in (("mobile", "mobile.glb"), ("low_power", "low.glb"))
        ]
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "assets": [asset]}), encoding="utf-8")
    return manifest, asset, files


def _rewrite(manifest, asset):
    manifest.write_text(json.dumps({"schema_version": 1, "assets": [asset]}), encoding="utf-8")


def test_staging_retains_verified_profile_variants(delivery, tmp_path):
    manifest, _, files = _staging(tmp_path)
    records = delivery._load_staged_assets(manifest)
    assert {item["profile"] for item in records[0]["lod_variants"]} == {"mobile", "low_power"}
    blueprint = delivery.ThreeDWebDeliveryBuilder._blueprint(
        project_id="fixture", project_name="Fixture", objective="Local integration",
        asset_records=records,
    )
    blueprint.validate()
    assert {item.lod_profile for item in blueprint.assets} == set(PerformanceProfile)
    assert len(blueprint.assets) == 3
    assert blueprint.zones[0].asset_ids == ("asset-01",)
    assert all(not zone.asset_ids for zone in blueprint.zones[1:])
    for item in records[0]["lod_variants"]:
        assert delivery._read_lod_payload(item) == files[item["relative_path"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile", "ultra"), ("profile", "desktop"), ("profile", None), ("profile", []),
        ("path", "../mobile.glb"), ("path", "/mobile.glb"),
        ("path", r"sub\mobile.glb"), ("path", "sub//mobile.glb"),
        ("path", "mobile.gltf"), ("path", None),
        ("sha256", "g" * 64), ("sha256", "0" * 64), ("sha256", None),
        ("size_bytes", True), ("size_bytes", "100"), ("size_bytes", 0),
        ("size_bytes", 24 * 1024 * 1024 + 1),
    ],
)
def test_invalid_variant_evidence_fails_closed(delivery, tmp_path, field, value):
    manifest, asset, _ = _staging(tmp_path)
    asset["lod_variants"][0][field] = value
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize("case", ["duplicate-profile", "duplicate-path", "too-many", "not-list", "incomplete"])
def test_ambiguous_or_unbounded_variants_are_rejected(delivery, tmp_path, case):
    manifest, asset, _ = _staging(tmp_path)
    if case == "duplicate-profile":
        asset["lod_variants"][1]["profile"] = "mobile"
    elif case == "duplicate-path":
        asset["lod_variants"][1]["path"] = "mobile.glb"
    elif case == "too-many":
        asset["lod_variants"] *= 2
    elif case == "incomplete":
        asset["lod_variants"].pop()
    else:
        asset["lod_variants"] = {}
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize("kind", ["file-symlink", "directory-symlink", "fifo", "hardlink"])
def test_variant_paths_cannot_follow_links_or_special_files(delivery, tmp_path, kind):
    manifest, asset, files = _staging(tmp_path)
    root = manifest.parent
    original = root / "mobile.glb"
    if kind == "directory-symlink":
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "mobile.glb").write_bytes(files["mobile.glb"])
        (root / "linked").symlink_to(elsewhere, target_is_directory=True)
        asset["lod_variants"][0]["path"] = "linked/mobile.glb"
    else:
        original.unlink()
        target = tmp_path / "mobile.glb"
        target.write_bytes(files["mobile.glb"])
        if kind == "file-symlink":
            original.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(original)
        else:
            os.link(target, original)
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize("payload", [b"not-a-glb", _glb(external=True)])
def test_variants_must_be_embedded_glb_files(delivery, tmp_path, payload):
    manifest, asset, _ = _staging(tmp_path)
    (manifest.parent / "mobile.glb").write_bytes(payload)
    asset["lod_variants"][0].update(sha256=sha256(payload).hexdigest(), size_bytes=len(payload))
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError, match="self-contained GLB"):
        delivery._load_staged_assets(manifest)


def test_variant_is_reverified_after_staging_admission(delivery, tmp_path):
    manifest, _, _ = _staging(tmp_path)
    record = next(
        item for item in delivery._load_staged_assets(manifest)[0]["lod_variants"]
        if item["profile"] == "mobile"
    )
    path = manifest.parent / "mobile.glb"
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(delivery.ThreeDProjectDeliveryError, match="integrity"):
        delivery._read_lod_payload(record)


@pytest.mark.parametrize("with_variants", [False, True])
def test_delivery_copies_and_accounts_for_the_selected_profile_payload(
    delivery, tmp_path, monkeypatch, with_variants,
):
    manifest, _, files = _staging(tmp_path, variants=with_variants)
    monkeypatch.setenv("PROJECT_3D_AUTOGEN_ENABLED", "false")
    monkeypatch.setenv("PROJECT_EXECUTION_NPM_CACHE", str(tmp_path / "npm-cache"))
    measured = {}

    def build_stub(command, **kwargs):
        if command == ["npm", "run", "build"]:
            root = Path(kwargs["cwd"])
            dist = root / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Unit fixture</title>")
            shutil.copytree(root / "public/assets", dist / "assets")
        return subprocess.CompletedProcess(command, 0, stdout="offline packaging fixture")

    def no_browser_acceptance(
        dist, qa_root, *, asset_bytes_by_profile, asset_paths_by_profile, bundle_bytes,
    ):
        measured.update(asset_bytes_by_profile)
        return (), ()

    monkeypatch.setattr(delivery, "_browser_qa", no_browser_acceptance)
    result = delivery.ThreeDWebDeliveryBuilder(command_runner=build_stub).build(
        project_id="fixture", project_name="Fixture", objective="Local integration",
        execution_root=tmp_path / "execution", asset_manifest_path=manifest,
    )
    root = tmp_path / "execution/delivery-package/3d-web"
    output = json.loads((root / "aionex-3d-build.json").read_text())
    expected = {
        "desktop": len(files["scene.glb"]),
        "mobile": len(files["mobile.glb"] if with_variants else files["scene.glb"]),
        "low_power": len(files["low.glb"]) if with_variants else 0,
    }
    assert {profile.value: size for profile, size in measured.items()} == expected
    assert output["profile_asset_bytes"] == result["profile_asset_bytes"] == expected
    assert output["model_payload_bytes"] == result["asset_bytes"] == sum(map(len, files.values()))
    assert output["lod_variant_count"] == (2 if with_variants else 0)
    assert output["low_power_lazy_assets_use_procedural_proxies"] is (not with_variants)
    assert output["low_power_proxy_asset_ids"] == ([] if with_variants else ["asset-01"])
    assert output["lod_optimization_executed_by_delivery"] is False
    assert result["release_ready"] is False
    packaged = output["assets"][0]
    entries = [packaged, *packaged["lod_variants"]]
    assert len(entries) == len(files)
    for entry in entries:
        payload = (root / entry["path"]).read_bytes()
        assert sha256(payload).hexdigest() == entry["sha256"]
        assert len(payload) == entry["size_bytes"]
    lifecycle = json.loads((root / "aionex-3d-lifecycle.json").read_text())
    assert lifecycle["asset_manifest"] is not None
    assert len(lifecycle["asset_manifest"]["entries"]) == len(files)


@pytest.mark.parametrize(
    ("observed", "expected", "matches"),
    [
        ([], [], True),
        (["http://127.0.0.1:8080/assets/low.glb"], ["/assets/low.glb"], True),
        (["http://127.0.0.1:8080/assets/desktop.glb"], ["/assets/low.glb"], False),
        ([], ["/assets/low.glb"], False),
        (["http://127.0.0.1:8080/assets/low.glb"], [], False),
        (["https://external.invalid/assets/low.glb"], ["/assets/low.glb"], False),
        (
            ["http://127.0.0.1:8080/assets/low.glb", "http://127.0.0.1:8080/assets/desktop.glb"],
            ["/assets/low.glb"], False,
        ),
    ],
)
def test_browser_resource_gate_proves_the_selected_model(delivery, observed, expected, matches):
    assert delivery._profile_model_resources_match(
        observed, expected, "http://127.0.0.1:8080",
    ) is matches


@pytest.mark.parametrize("count", [8, 9])
@pytest.mark.parametrize("with_variants", [False, True])
def test_delivery_never_admits_more_models_than_it_can_reference(
    delivery, tmp_path, count, with_variants,
):
    manifest, asset, _ = _staging(tmp_path, variants=with_variants)
    manifest.write_text(
        json.dumps({"schema_version": 1, "assets": [asset] * count}), encoding="utf-8",
    )
    if count > 8:
        with pytest.raises(delivery.ThreeDProjectDeliveryError, match="at most eight"):
            delivery._load_staged_assets(manifest)
    else:
        records = delivery._load_staged_assets(manifest)
        blueprint = delivery.ThreeDWebDeliveryBuilder._blueprint(
            project_id="fixture", project_name="Fixture", objective="Bounded registry",
            asset_records=records,
        )
        assert len(blueprint.zones) == 8
        assert {asset_id for zone in blueprint.zones for asset_id in zone.asset_ids} == {
            f"asset-{index+1:02d}" for index in range(8)
        }
        assert len(blueprint.assets) == (24 if with_variants else 8)


@pytest.mark.parametrize("mobile_mib", [5, 11])
def test_lifecycle_budgets_only_the_explicit_variant_loaded_by_each_profile(tmp_path, mobile_mib):
    assets = []
    zones = []
    for group in range(3):
        group_id = f"group-{group}"
        for profile, size_mib in (
            (PerformanceProfile.DESKTOP, 11),
            (PerformanceProfile.MOBILE, mobile_mib),
            (PerformanceProfile.LOW_POWER, 1),
        ):
            asset_id = f"{group_id}-{profile.value}"
            path = f"{asset_id}.glb"
            (tmp_path / path).write_bytes(_glb(padding_bytes=size_mib * 1024 * 1024))
            assets.append(SceneAsset(
                asset_id, AssetKind.GLB, path, lazy=True,
                lod_group=group_id, lod_profile=profile,
            ))
        zones.append(SceneZone(
            group_id, group_id, (0, 0, 0), 3, asset_ids=(f"{group_id}-desktop",),
        ))
    blueprint = ThreeDProjectPlanner().plan(
        project_id="budgets", title="Budgets", objective="Selected model transfer",
        assets=assets, zones=zones,
    )
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=blueprint, project_root=tmp_path, browser_runs=(), performance_samples=(),
        production_build_passed=False, deployment_receipt=None, rollback_receipt=None,
        approval=ApprovalDecision(False, None, "Unit test does not authorize release"),
    ))
    asset_failures = [item for item in result.remediation if item.stage.value == "assets"]
    if mobile_mib == 5:
        # Desktop files exceed the mobile per-file limit, and the full package
        # exceeds its total limit; mobile still loads only three 5 MiB variants.
        assert not asset_failures
    else:
        assert any(item.code == "asset-bytes" and "mobile" in item.message for item in asset_failures)
        assert all("desktop" not in item.message and "low_power" not in item.message for item in asset_failures)
    assert result.asset_manifest is not None
    assert len(result.asset_manifest.entries) == 9
    assert result.release_ready is False
