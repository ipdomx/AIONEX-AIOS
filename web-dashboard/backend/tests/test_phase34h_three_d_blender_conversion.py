"""Roadmap 2.4: Blender exports/previews degrade honestly and stay validated.

Blender itself is never executed here. The converter sidecar is simulated by a
fake that answers the spool protocol, so these tests cover the worker side:
capability detection, input/output validation, storage and link issuance.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
import time
from types import SimpleNamespace
import zipfile

import pytest

from app.core.config import settings
from app.services import three_d_conversion as conversion
from app.services.three_d_storage import (
    ThreeDStorageError,
    issue_local_artifact_token,
    verify_local_artifact_token,
)

SECRET = "fr16d-test-secret-key-with-at-least-32-chars"
IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)


def _png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00" + b"\x00" * 4


def _glb(document: dict, binary: bytes = b"") -> bytes:
    raw = json.dumps(document).encode()
    raw += b" " * (-len(raw) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(raw), 0x4E4F534A) + raw
    if binary:
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _model(texture: bytes | None = None, **extra: object) -> bytes:
    document: dict = {"asset": {"version": "2.0"}, "meshes": [{"primitives": []}], "accessors": [{"count": 3}]}
    binary = b""
    if texture is not None:
        document["bufferViews"] = [{"buffer": 0, "byteOffset": 0, "byteLength": len(texture)}]
        document["images"] = [{"bufferView": 0, "mimeType": "image/png"}]
        document["buffers"] = [{"byteLength": len(texture)}]
        binary = texture
    document.update(extra)
    return _glb(document, binary)


@pytest.fixture()
def spool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "spool"
    for bucket in ("requests", "work", "done"):
        (root / bucket).mkdir(parents=True)
    monkeypatch.setattr(settings, "THREE_D_CONVERSION_SPOOL", str(root))
    monkeypatch.setattr(settings, "THREE_D_BLENDER_ENABLED", True)
    monkeypatch.setattr(settings, "THREE_D_THUMBNAIL_SIZE", 64)
    monkeypatch.setattr(settings, "THREE_D_CONVERSION_TIMEOUT_SECONDS", 10)
    return root


def _heartbeat(root: Path, **overrides: object) -> None:
    status = {
        "available": True,
        "blender_version": "5.2.3",
        "formats": ["obj", "fbx", "usdz"],
        "thumbnail": True,
        "updated_at": time.time(),
        "reason": "ready",
    }
    status.update(overrides)
    (root / "status.json").write_text(json.dumps(status))


def _fake_converter(root: Path, *, fbx: bytes = b"Kaydara FBX Binary  \x00rest", thumbnail_edge: int = 64, report: dict | None = None):
    """Stands in for the network-less sidecar: answers one spool request."""

    def answer(_seconds: float) -> None:
        for request in list((root / "requests").iterdir()):
            spec = json.loads((request / "request.json").read_text())
            assert spec["input_format"] == "glb" and (request / "input.glb").read_bytes()[:4] == b"glTF"
            out = request / "out"
            (out / "obj").mkdir(parents=True)
            (out / "obj" / "model.obj").write_text("o cube\nv 0 0 0\n")
            (out / "obj" / "model.mtl").write_text("newmtl m\n")
            (out / "fbx").mkdir()
            (out / "fbx" / "model.fbx").write_bytes(fbx)
            (out / "usdz").mkdir()
            with zipfile.ZipFile(out / "usdz" / "model.usdz", "w") as archive:
                archive.writestr("model.usdc", b"PXR-USDC")
            (out / "preview.png").write_bytes(_png(thumbnail_edge, thumbnail_edge))
            results = report or {kind: {"ok": True} for kind in [*spec["formats"], "thumbnail"]}
            (request / "result.json").write_text(json.dumps({"ok": True, "results": results}))
            request.rename(root / "done" / request.name)

    return answer


def test_capability_is_unavailable_without_a_fresh_pinned_converter(spool: Path) -> None:
    assert conversion.probe_blender_capability().reason == "converter_not_running"
    _heartbeat(spool, updated_at=time.time() - 3600)
    assert conversion.probe_blender_capability().reason == "converter_status_stale"
    _heartbeat(spool, blender_version="4.2.0")
    cap = conversion.probe_blender_capability()
    assert not cap.available and cap.reason == "blender_version_not_pinned"
    _heartbeat(spool, available=False, reason="blender_probe_failed", blender_version=None)
    assert conversion.probe_blender_capability().reason == "blender_probe_failed"
    _heartbeat(spool)
    ready = conversion.probe_blender_capability()
    assert ready.available and ready.formats == ("obj", "fbx", "usdz") and ready.thumbnail


def test_missing_converter_produces_no_exports_and_never_raises(spool: Path) -> None:
    result = conversion.convert_glb(_model(_png(4, 4)))
    assert result.files == {} and result.capability.available is False


def test_valid_conversion_returns_only_verified_files_and_cleans_the_spool(spool: Path) -> None:
    _heartbeat(spool)
    result = conversion.convert_glb(_model(_png(4, 4)), sleep=_fake_converter(spool))
    assert set(result.files) == {"obj", "fbx", "usdz", "thumbnail"}
    with zipfile.ZipFile(__import__("io").BytesIO(result.files["obj"].body)) as archive:
        assert sorted(archive.namelist()) == ["model.mtl", "model.obj"]
    assert result.files["usdz"].media_type == "model/vnd.usdz+zip"
    assert all(not any((spool / bucket).iterdir()) for bucket in ("requests", "done"))


def test_outputs_that_fail_validation_are_not_offered(spool: Path) -> None:
    _heartbeat(spool)
    result = conversion.convert_glb(_model(_png(4, 4)), sleep=_fake_converter(spool, fbx=b"ascii fbx", thumbnail_edge=32))
    assert "fbx" not in result.files and "thumbnail" not in result.files
    assert result.failures["fbx"] == "FBX export is not binary FBX"
    assert set(result.files) == {"obj", "usdz"}


def test_failed_formats_reported_by_blender_are_not_offered(spool: Path) -> None:
    _heartbeat(spool)
    report = {"obj": {"ok": True}, "fbx": {"ok": False, "error": "RuntimeError"}, "usdz": {"ok": True}, "thumbnail": {"ok": True}}
    result = conversion.convert_glb(_model(_png(4, 4)), sleep=_fake_converter(spool, report=report))
    assert "fbx" not in result.files and result.failures["fbx"] == "RuntimeError"


def test_converter_timeout_degrades_without_exports(spool: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _heartbeat(spool)
    monkeypatch.setattr(settings, "THREE_D_CONVERSION_TIMEOUT_SECONDS", 0)
    result = conversion.convert_glb(_model(_png(4, 4)), sleep=lambda _s: None)
    assert result.files == {}
    assert not any((spool / "requests").iterdir())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"not a glb at all, definitely", "input is not a GLB"),
        (_model(_png(4, 4), images=[{"uri": "file:///etc/passwd"}]), "external or inline URI"),
        (_model(_png(9000, 9000)), "texture dimensions"),
        (_model(None, accessors=[{"count": 10**9}]), "geometry exceeds"),
        (_model(None, meshes=[]), "mesh count"),
    ],
)
def test_untrusted_glb_is_rejected_before_blender(body: bytes, message: str) -> None:
    with pytest.raises(conversion.ThreeDConversionError, match=message):
        conversion.validate_glb(body)


def test_texture_pixel_budget_blocks_decompression_bombs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "THREE_D_CONVERSION_MAX_TEXTURE_PIXELS", 1024 * 1024)
    with pytest.raises(conversion.ThreeDConversionError, match="pixel budget"):
        conversion.validate_glb(_model(_png(2048, 2048)))


def test_only_well_formed_stored_exports_are_listed() -> None:
    metadata = {
        "exports": {
            "fbx": {"object_key": "3d/a/b/c/exports/model.fbx", "sha256": "a" * 64, "size_bytes": 10},
            "usdz": {"object_key": "x", "sha256": "short", "size_bytes": 10},
            "exe": {"object_key": "x", "sha256": "a" * 64, "size_bytes": 10},
        }
    }
    assert set(conversion.stored_exports(metadata)) == {"fbx"}
    assert conversion.export_object_keys(metadata) == ["3d/a/b/c/exports/model.fbx"]
    assert conversion.stored_exports({}) == {}
    assert conversion.export_key("3d/o/p/j/final.glb", "usdz") == "3d/o/p/j/exports/model.usdz"


def test_local_tokens_name_a_variant_and_keep_glb_tokens_unchanged() -> None:
    project, job, artifact = IDS
    glb = issue_local_artifact_token(project_id=project, job_id=job, artifact_id=artifact, inline=False, secret=SECRET, ttl_seconds=300, now_epoch=1000)
    assert verify_local_artifact_token(glb, secret=SECRET, now_epoch=1000).variant == "glb"
    assert b"variant" not in __import__("base64").urlsafe_b64decode(glb.split(".")[0] + "==")
    fbx = issue_local_artifact_token(project_id=project, job_id=job, artifact_id=artifact, inline=False, secret=SECRET, ttl_seconds=300, now_epoch=1000, variant="fbx")
    assert verify_local_artifact_token(fbx, secret=SECRET, now_epoch=1000).variant == "fbx"
    with pytest.raises(ThreeDStorageError):
        issue_local_artifact_token(project_id=project, job_id=job, artifact_id=artifact, inline=False, secret=SECRET, ttl_seconds=300, variant="exe")


def test_worker_stores_only_checksum_matching_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import three_d_worker

    files = {
        "fbx": conversion.ConvertedFile("fbx", "model.fbx", "application/octet-stream", b"fbx-bytes", __import__("hashlib").sha256(b"fbx-bytes").hexdigest()),
        "usdz": conversion.ConvertedFile("usdz", "model.usdz", "model/vnd.usdz+zip", b"usdz", "0" * 64),
    }
    capability = conversion.BlenderCapability(True, "ready", "5.2.3", ("obj", "fbx", "usdz"), True)
    monkeypatch.setattr(three_d_worker, "convert_glb", lambda _body: conversion.ConversionResult(capability, dict(files), {"obj": "export_failed"}))
    stored: dict[str, bytes] = {}
    deleted: list[str] = []

    def put_bytes(key: str, body: bytes, _media: str, *, metadata: dict) -> SimpleNamespace:
        stored[key] = body
        return SimpleNamespace(sha256=__import__("hashlib").sha256(body).hexdigest())

    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.storage = SimpleNamespace(put_bytes=put_bytes, delete=deleted.append)
    exports, cap, keys = asyncio.run(worker._derive_exports("3d/o/p/j/final.glb", b"glTF", metadata={}))
    assert set(exports) == {"fbx"}
    assert exports["fbx"]["object_key"] == "3d/o/p/j/exports/model.fbx"
    assert deleted == ["3d/o/p/j/exports/model.usdz"] and keys == ["3d/o/p/j/exports/model.fbx"]
    assert cap["failures"] == {"obj": "export_failed", "usdz": "storage_checksum_mismatch"}


def test_worker_records_no_exports_when_input_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import three_d_worker

    def reject(_body: bytes):
        raise conversion.ThreeDConversionError("GLB references an external or inline URI")

    monkeypatch.setattr(three_d_worker, "convert_glb", reject)
    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.storage = SimpleNamespace()
    exports, cap, keys = asyncio.run(worker._derive_exports("3d/o/p/j/final.glb", b"glTF", metadata={}))
    assert exports == {} and keys == [] and cap["reason"] == "input_rejected"
