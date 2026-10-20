"""Offline primary-GLB admission/copy regressions; no provider, build, or browser QA."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct

import pytest


DESKTOP_MAX_BYTES = 24 * 1024 * 1024


@pytest.fixture
def delivery():
    path = (
        Path(__file__).resolve().parents[1]
        / "web-dashboard/backend/app/services/three_d_project_delivery.py"
    )
    spec = importlib.util.spec_from_file_location("fr16_primary_integrity_service", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _glb(document=None) -> bytes:
    # Match the existing offline LOD fixtures: JSON-only GLBs need no BIN chunk.
    if document is None:
        document = {
            "asset": {"version": "2.0"},
            "accessors": [{"count": 12, "type": "SCALAR", "componentType": 5123}],
            "meshes": [{"primitives": [{"indices": 0}]}],
        }
    payload = json.dumps(document).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload), len(payload), 0x4E4F534A) + payload


def _rewrite(manifest, asset):
    manifest.write_text(
        json.dumps({"schema_version": 1, "assets": [asset]}), encoding="utf-8",
    )


def _staging(tmp_path, *, relative="scene.glb", payload=None):
    root = tmp_path / "staging"
    root.mkdir()
    content = _glb() if payload is None else payload
    source = root / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    asset = {
        "artifact_id": "primary-fixture", "provider": "local-fixture",
        "path": relative, "sha256": sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
    manifest = root / "manifest.json"
    _rewrite(manifest, asset)
    return manifest, asset, source, content


def _blueprint(delivery, records):
    return delivery.ThreeDWebDeliveryBuilder._blueprint(
        project_id="primary-fixture", project_name="Primary fixture",
        objective="Offline bounded primary asset copy", asset_records=records,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "../scene.glb"), ("path", "/scene.glb"),
        ("path", "./scene.glb"), ("path", "nested//scene.glb"),
        ("path", "nested/./scene.glb"), ("path", "nested/../scene.glb"),
        ("path", "scene.glb/"), ("path", r"nested\scene.glb"),
        ("path", "scene\x00.glb"), ("path", "scene.gltf"),
        ("path", ""), ("path", None), ("path", 7),
        ("sha256", "g" * 64), ("sha256", "a" * 63),
        ("sha256", "a" * 65), ("sha256", None), ("sha256", []),
        ("size_bytes", True), ("size_bytes", "168"),
        ("size_bytes", 168.0), ("size_bytes", 0), ("size_bytes", -1),
        ("size_bytes", None), ("size_bytes", []),
        ("size_bytes", DESKTOP_MAX_BYTES + 1),
    ],
)
def test_primary_rejects_malformed_or_noncanonical_evidence(delivery, tmp_path, field, value):
    manifest, asset, _, content = _staging(tmp_path)
    # The normalized nested aliases must resolve to a real file, so rejection
    # proves the canonical-path rule rather than an unrelated missing file.
    nested = manifest.parent / "nested"
    nested.mkdir()
    (nested / "scene.glb").write_bytes(content)
    asset[field] = value
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize("field", ["path", "sha256", "size_bytes"])
def test_primary_evidence_fields_are_required(delivery, tmp_path, field):
    manifest, asset, _, _ = _staging(tmp_path)
    del asset[field]
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize("case", ["checksum", "smaller", "larger", "numeric-string", "float"])
def test_primary_checks_actual_content_and_strict_size_type(delivery, tmp_path, case):
    manifest, asset, _, content = _staging(tmp_path)
    if case == "checksum":
        asset["sha256"] = "0" * 64
    elif case == "numeric-string":
        asset["size_bytes"] = str(len(content))
    elif case == "float":
        asset["size_bytes"] = float(len(content))
    else:
        asset["size_bytes"] = len(content) + (-1 if case == "smaller" else 1)
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize(
    "kind", ["in-root-file-symlink", "in-root-directory-symlink", "hardlink", "fifo", "directory"],
)
def test_primary_rejects_links_and_special_files_even_inside_staging(delivery, tmp_path, kind):
    manifest, asset, source, content = _staging(tmp_path)
    root = manifest.parent
    source.unlink()
    if kind == "in-root-directory-symlink":
        real = root / "real"
        real.mkdir()
        (real / "scene.glb").write_bytes(content)
        (root / "linked").symlink_to(real, target_is_directory=True)
        asset["path"] = "linked/scene.glb"
    elif kind in {"in-root-file-symlink", "hardlink"}:
        target = root / "original.glb"
        target.write_bytes(content)
        if kind == "hardlink":
            os.link(target, source)
        else:
            source.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(source)
    else:
        source.mkdir()
    _rewrite(manifest, asset)
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize(
    ("collection", "uri"),
    [
        ("buffers", "mesh.bin"), ("buffers", "../mesh.bin"),
        ("images", "texture.png"), ("images", "https://example.invalid/texture.png"),
        ("images", "file:///tmp/texture.png"), ("images", 1),
    ],
)
def test_primary_cannot_introduce_external_glb_resources(delivery, tmp_path, collection, uri):
    payload = _glb({"asset": {"version": "2.0"}, collection: [{"uri": uri}]})
    manifest, _, _, _ = _staging(tmp_path, payload=payload)
    with pytest.raises(delivery.ThreeDProjectDeliveryError, match="self-contained GLB"):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-a-glb", b"BAD!" + _glb()[4:], _glb()[:-1],
        _glb()[:4] + struct.pack("<I", 1) + _glb()[8:],
        _glb([]), _glb({"buffers": {}}), _glb({"images": [[]]}),
    ],
    ids=["short", "magic", "truncated", "version", "non-object", "resource-list", "resource-entry"],
)
def test_primary_rejects_invalid_glb_even_with_matching_digest(delivery, tmp_path, payload):
    manifest, _, _, _ = _staging(tmp_path, payload=payload)
    with pytest.raises(delivery.ThreeDProjectDeliveryError, match="self-contained GLB"):
        delivery._load_staged_assets(manifest)


@pytest.mark.parametrize(
    "change", ["same-size-bytes", "growth", "file-symlink", "directory-symlink", "hardlink", "fifo"],
)
def test_primary_is_reverified_before_copy(delivery, tmp_path, change):
    manifest, _, source, content = _staging(tmp_path, relative="nested/scene.glb")
    records = delivery._load_staged_assets(manifest)
    blueprint = _blueprint(delivery, records)
    if change == "same-size-bytes":
        source.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    elif change == "growth":
        source.write_bytes(content + b"unexpected")
    elif change == "file-symlink":
        target = manifest.parent / "replacement.glb"
        target.write_bytes(content)
        source.unlink()
        source.symlink_to(target)
    elif change == "directory-symlink":
        original_directory = source.parent
        moved = manifest.parent / "moved"
        original_directory.rename(moved)
        original_directory.symlink_to(moved, target_is_directory=True)
    elif change == "hardlink":
        os.link(source, manifest.parent / "second-link.glb")
    else:
        source.unlink()
        os.mkfifo(source)
    output = tmp_path / "delivery"
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._copy_staged_assets(records, blueprint, output)
    assert not (output / "public/assets/asset-01.glb").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("size_bytes", DESKTOP_MAX_BYTES + 1), ("relative_path", "nested//scene.glb")],
)
def test_copy_rechecks_evidence_before_publishing_primary(delivery, tmp_path, field, value):
    manifest, _, _, _ = _staging(tmp_path, relative="nested/scene.glb")
    records = delivery._load_staged_assets(manifest)
    blueprint = _blueprint(delivery, records)
    records[0][field] = value
    output = tmp_path / "delivery"
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._copy_staged_assets(records, blueprint, output)
    assert not (output / "public/assets/asset-01.glb").exists()


@pytest.mark.parametrize("existing", ["regular", "symlink"])
def test_primary_copy_never_overwrites_an_existing_destination(delivery, tmp_path, existing):
    manifest, _, _, _ = _staging(tmp_path)
    records = delivery._load_staged_assets(manifest)
    blueprint = _blueprint(delivery, records)
    output = tmp_path / "delivery"
    destination = output / "public/assets/asset-01.glb"
    destination.parent.mkdir(parents=True)
    protected = tmp_path / "protected.glb"
    protected.write_bytes(b"existing evidence must survive")
    if existing == "symlink":
        destination.symlink_to(protected)
    else:
        destination.write_bytes(protected.read_bytes())
    with pytest.raises(FileExistsError):
        delivery._copy_staged_assets(records, blueprint, output)
    assert destination.read_bytes() == protected.read_bytes() == b"existing evidence must survive"
    assert destination.is_symlink() is (existing == "symlink")


def test_nested_legacy_primary_remains_compatible(delivery, tmp_path):
    manifest, asset, source, content = _staging(tmp_path, relative="nested/models/scene.GLB")
    asset["sha256"] = asset["sha256"].upper()
    asset["metadata"] = {"legacy": True}
    del asset["artifact_id"]
    del asset["provider"]
    _rewrite(manifest, asset)
    records = delivery._load_staged_assets(manifest)
    record = records[0]
    assert record["source"] == source
    assert record["staging_root"] == manifest.parent.resolve()
    assert record["relative_path"] == asset["path"]
    assert record["sha256"] == sha256(content).hexdigest()
    assert record["metadata"] == {"legacy": True}
    assert record["artifact_id"] == "artifact-1"
    assert record["job_id"] == ""
    assert record["provider"] == "unknown"
    assert record["lod_variants"] == []
    blueprint = _blueprint(delivery, records)
    assert len(blueprint.assets) == 1
    assert blueprint.assets[0].lod_profile is None
    output = tmp_path / "delivery"
    copied = delivery._copy_staged_assets(records, blueprint, output)
    destination = output / copied[0]["path"]
    assert destination.read_bytes() == source.read_bytes() == content
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert copied[0]["sha256"] == record["sha256"]
    assert copied[0]["size_bytes"] == len(content)
    assert copied[0]["triangles"] == 4
    assert copied[0]["lod_variants"] == []


def test_autogenerated_records_are_reverifiable_and_copyable(delivery, tmp_path, monkeypatch):
    # Exercise the real record-producing function with an entirely local client.
    content = _glb()
    calls = []

    class LocalTripoClient:
        def __init__(self, api_key, *, timeout_seconds):
            assert api_key == ""

        def submit(self, prompt, *, seed, face_limit):
            assert isinstance(prompt, str) and prompt
            calls.append("submit")
            return "offline-task"

        def wait(self, task_id):
            assert task_id == "offline-task"
            calls.append("wait")
            return {
                "output": {"model_url": "https://example.invalid/offline-fixture.glb"},
                "credits_consumed": 0,
            }

        def download_glb(self, url, destination):
            assert url == "https://example.invalid/offline-fixture.glb"
            calls.append("download-fixture")
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    monkeypatch.setattr(delivery, "TripoTextToModelClient", LocalTripoClient)
    records = delivery._autogenerate_tripo_assets(
        root=tmp_path / "execution", project_name="Offline fixture",
        objective="Verify generated primary provenance", api_key="", count=1,
    )
    assert calls == ["submit", "wait", "download-fixture"]
    assert len(records) == 1
    record = records[0]
    source = record["source"]
    assert record["staging_root"] / record["relative_path"] == source
    assert record["sha256"] == sha256(content).hexdigest()
    assert record["size_bytes"] == len(content)
    assert "lod_variants" not in record
    output = tmp_path / "delivery"
    copied = delivery._copy_staged_assets(records, _blueprint(delivery, records), output)
    assert copied[0]["artifact_id"] == "tripo:offline-task"
    assert copied[0]["job_id"] == "offline-task"
    assert copied[0]["provider"] == "tripo3d"
    assert copied[0]["sha256"] == record["sha256"]
    assert copied[0]["size_bytes"] == len(content)
    assert copied[0]["triangles"] == 4
    assert copied[0]["lod_variants"] == []
    assert (output / copied[0]["path"]).read_bytes() == source.read_bytes() == content


def test_embedded_data_resource_remains_admissible(delivery, tmp_path):
    payload = _glb({
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 4, "uri": "data:application/octet-stream;base64,AAAAAA=="}],
    })
    manifest, _, _, _ = _staging(tmp_path, payload=payload)
    records = delivery._load_staged_assets(manifest)
    assert records[0]["size_bytes"] == len(payload)
    assert records[0]["sha256"] == sha256(payload).hexdigest()
