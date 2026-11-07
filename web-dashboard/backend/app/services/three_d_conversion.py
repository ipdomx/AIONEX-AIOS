"""Headless Blender format conversions and previews for stored 3D artifacts.

Blender never runs in the API or three-d-worker containers. A dedicated
``three-d-converter`` sidecar (``infra/blender-converter``) carries the pinned,
checksum-verified Blender build, has no network at all and runs each request in
a sandboxed child process (timeout, rlimits, private temp dirs, factory startup,
no add-on/script auto-execution). The three-d-worker talks to it only through a
shared spool directory:

* ``status.json``: heartbeat written by the converter (Blender version, formats)
* ``requests/<id>/``: request + validated GLB, renamed in atomically
* ``done/<id>/``: result + produced files, validated again here before storage

If the sidecar is absent, stale or on an unpinned Blender, the capability is
reported unavailable and nothing beyond the generated GLB is recorded. Users are
only ever offered formats that were produced, validated and stored for that
specific artifact, so missing Blender degrades honestly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import time
from typing import Any
import zipfile

from app.core.config import settings

EXPORT_FORMATS: tuple[str, ...] = ("obj", "fbx", "usdz")
THUMBNAIL_KEY = "thumbnail"
EXPORT_MEDIA_TYPES: Mapping[str, str] = {
    "obj": "application/zip",
    "fbx": "application/octet-stream",
    "usdz": "model/vnd.usdz+zip",
    THUMBNAIL_KEY: "image/png",
}
EXPORT_FILENAMES: Mapping[str, str] = {
    "obj": "model-obj.zip",
    "fbx": "model.fbx",
    "usdz": "model.usdz",
    THUMBNAIL_KEY: "preview.png",
}
_VERSION_LINE = re.compile(r"Blender\s+(\d+\.\d+\.\d+)(?:\s+LTS)?")
_FBX_MAGIC = b"Kaydara FBX Binary  \x00"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_GLB_JSON = 0x4E4F534A


class ThreeDConversionError(RuntimeError):
    """The input, Blender run or output failed a conversion safety check."""


@dataclass(frozen=True)
class BlenderCapability:
    available: bool
    reason: str
    version: str | None = None
    formats: tuple[str, ...] = ()
    thumbnail: bool = False

    def as_metadata(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "blender_version": self.version,
            "formats": list(self.formats),
            "thumbnail": self.thumbnail,
        }


@dataclass(frozen=True)
class ConvertedFile:
    kind: str
    filename: str
    media_type: str
    body: bytes
    sha256: str


@dataclass
class ConversionResult:
    capability: BlenderCapability
    files: dict[str, ConvertedFile] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


_ID_BYTES = 16


def _spool() -> Path:
    return Path(settings.THREE_D_CONVERSION_SPOOL)


def probe_blender_capability(*, now: float | None = None) -> BlenderCapability:
    """Read the converter sidecar heartbeat; never runs Blender here."""
    if not settings.THREE_D_BLENDER_ENABLED:
        return BlenderCapability(False, "disabled")
    status_path = _spool() / "status.json"
    try:
        if status_path.is_symlink():
            return BlenderCapability(False, "converter_status_unsafe")
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return BlenderCapability(False, "converter_not_running")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return BlenderCapability(False, "converter_status_invalid")
    if not isinstance(status, dict):
        return BlenderCapability(False, "converter_status_invalid")
    moment = time.time() if now is None else now
    try:
        age = moment - float(status.get("updated_at") or 0)
    except (TypeError, ValueError):
        return BlenderCapability(False, "converter_status_invalid")
    if age > int(settings.THREE_D_CONVERTER_STATUS_MAX_AGE_SECONDS) or age < -30:
        return BlenderCapability(False, "converter_status_stale")
    version = str(status.get("blender_version") or "")
    match = _VERSION_LINE.fullmatch(f"Blender {version}") if version else None
    series = settings.THREE_D_BLENDER_REQUIRED_SERIES.strip()
    if not status.get("available") or match is None:
        return BlenderCapability(False, str(status.get("reason") or "blender_unavailable")[:80])
    if not (version == series or version.startswith(series + ".")):
        return BlenderCapability(False, "blender_version_not_pinned", version=version)
    formats = tuple(fmt for fmt in EXPORT_FORMATS if fmt in (status.get("formats") or []))
    return BlenderCapability(True, "ready", version=version, formats=formats, thumbnail=bool(status.get("thumbnail")))


def _image_dimensions(blob: bytes, mime: str) -> tuple[int, int]:
    if mime == "image/png" or blob[:8] == _PNG_MAGIC:
        if blob[:8] != _PNG_MAGIC or len(blob) < 24 or blob[12:16] != b"IHDR":
            raise ThreeDConversionError("embedded PNG texture is malformed")
        return struct.unpack(">II", blob[16:24])
    if mime == "image/jpeg" or blob[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(blob):
            if blob[index] != 0xFF:
                raise ThreeDConversionError("embedded JPEG texture is malformed")
            marker = blob[index + 1]
            length = struct.unpack(">H", blob[index + 2 : index + 4])[0]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", blob[index + 5 : index + 9])
                return width, height
            index += 2 + length
        raise ThreeDConversionError("embedded JPEG texture has no frame header")
    if mime == "image/webp" or (blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"):
        chunk = blob[12:16]
        if chunk == b"VP8X" and len(blob) >= 30:
            width = 1 + int.from_bytes(blob[24:27], "little")
            height = 1 + int.from_bytes(blob[27:30], "little")
            return width, height
        if chunk == b"VP8 " and len(blob) >= 30:
            width, height = struct.unpack("<HH", blob[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if chunk == b"VP8L" and len(blob) >= 25:
            bits = int.from_bytes(blob[21:25], "little")
            return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        raise ThreeDConversionError("embedded WebP texture is malformed")
    raise ThreeDConversionError("embedded texture type is not allowed")


def validate_glb(body: bytes) -> dict[str, int]:
    """Structural and decompression-bomb checks before Blender parses anything."""
    if len(body) > int(settings.THREE_D_CONVERSION_MAX_INPUT_BYTES):
        raise ThreeDConversionError("GLB exceeds the conversion input limit")
    if len(body) < 20 or body[:4] != b"glTF":
        raise ThreeDConversionError("input is not a GLB")
    version, total = struct.unpack_from("<II", body, 4)
    if version != 2 or total != len(body):
        raise ThreeDConversionError("GLB header is invalid")
    json_length, json_type = struct.unpack_from("<II", body, 12)
    if json_type != _GLB_JSON or 20 + json_length > len(body) or json_length > 16 * 1024 * 1024:
        raise ThreeDConversionError("GLB JSON chunk is invalid")
    try:
        document = json.loads(body[20 : 20 + json_length].decode("utf-8").rstrip(" \x00"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThreeDConversionError("GLB JSON chunk is invalid") from exc
    if not isinstance(document, dict):
        raise ThreeDConversionError("GLB JSON chunk is invalid")
    bin_start = 20 + json_length
    binary = b""
    if bin_start + 8 <= len(body):
        bin_length, _ = struct.unpack_from("<II", body, bin_start)
        binary = body[bin_start + 8 : bin_start + 8 + bin_length]
    for collection in ("buffers", "images"):
        for item in document.get(collection) or []:
            if isinstance(item, dict) and "uri" in item:
                raise ThreeDConversionError("GLB references an external or inline URI")
    meshes = document.get("meshes") or []
    if not meshes or len(meshes) > int(settings.THREE_D_CONVERSION_MAX_MESHES):
        raise ThreeDConversionError("GLB mesh count is outside the conversion limit")
    accessors = document.get("accessors") or []
    elements = sum(int(item.get("count") or 0) for item in accessors if isinstance(item, dict))
    if elements > int(settings.THREE_D_CONVERSION_MAX_ACCESSOR_ELEMENTS):
        raise ThreeDConversionError("GLB geometry exceeds the conversion limit")
    views = document.get("bufferViews") or []
    total_pixels = 0
    images = document.get("images") or []
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("bufferView"), int):
            raise ThreeDConversionError("GLB image is not embedded")
        index = image["bufferView"]
        if index < 0 or index >= len(views):
            raise ThreeDConversionError("GLB image buffer view is invalid")
        view = views[index]
        offset = int(view.get("byteOffset") or 0)
        length = int(view.get("byteLength") or 0)
        blob = binary[offset : offset + length]
        if len(blob) != length or length == 0:
            raise ThreeDConversionError("GLB image buffer is truncated")
        width, height = _image_dimensions(blob, str(image.get("mimeType") or ""))
        limit = int(settings.THREE_D_CONVERSION_MAX_TEXTURE_EDGE)
        if not (0 < width <= limit and 0 < height <= limit):
            raise ThreeDConversionError("GLB texture dimensions exceed the conversion limit")
        total_pixels += width * height
    if total_pixels > int(settings.THREE_D_CONVERSION_MAX_TEXTURE_PIXELS):
        raise ThreeDConversionError("GLB textures exceed the conversion pixel budget")
    return {"meshes": len(meshes), "images": len(images), "texture_pixels": total_pixels, "accessor_elements": elements}


def _validate_output(kind: str, path: Path, workdir: Path) -> bytes:
    limit = int(settings.THREE_D_CONVERSION_MAX_OUTPUT_BYTES)
    if kind == "obj":
        folder = path.parent
        members = sorted(item for item in folder.rglob("*") if item.is_file())
        if not any(item.suffix == ".obj" for item in members):
            raise ThreeDConversionError("OBJ export produced no .obj file")
        bundle = workdir / "obj-bundle.zip"
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in members:
                if item.is_symlink():
                    raise ThreeDConversionError("OBJ export produced a symlink")
                info = zipfile.ZipInfo(item.relative_to(folder).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, item.read_bytes())
        path = bundle
    if not path.is_file() or path.is_symlink():
        raise ThreeDConversionError(f"{kind} export is missing")
    size = path.stat().st_size
    if size == 0 or size > limit:
        raise ThreeDConversionError(f"{kind} export size is outside the allowed range")
    body = path.read_bytes()
    if kind == "fbx" and not body.startswith(_FBX_MAGIC):
        raise ThreeDConversionError("FBX export is not binary FBX")
    if kind in {"usdz", "obj"} and not body.startswith(b"PK\x03\x04"):
        raise ThreeDConversionError(f"{kind} export is not a zip package")
    if kind == "usdz":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not names or not names[0].endswith((".usdc", ".usda", ".usd")):
                raise ThreeDConversionError("USDZ export has no root layer")
    if kind == THUMBNAIL_KEY:
        if not body.startswith(_PNG_MAGIC):
            raise ThreeDConversionError("thumbnail is not PNG")
        width, height = _image_dimensions(body, "image/png")
        edge = int(settings.THREE_D_THUMBNAIL_SIZE)
        if (width, height) != (edge, edge):
            raise ThreeDConversionError("thumbnail dimensions are wrong")
    return body


def _submit(body: bytes, formats: list[str], thumbnail: bool) -> str:
    spool = _spool()
    request_id = secrets.token_hex(_ID_BYTES)
    staging = spool / "incoming" / request_id
    staging.mkdir(mode=0o770, parents=True)
    (staging / "input.glb").write_bytes(body)
    (staging / "request.json").write_text(
        json.dumps(
            {
                "input_format": "glb",
                "formats": formats,
                "thumbnail": thumbnail,
                "thumbnail_size": int(settings.THREE_D_THUMBNAIL_SIZE),
            }
        ),
        encoding="utf-8",
    )
    os.replace(staging, spool / "requests" / request_id)
    return request_id


def _await_result(request_id: str, timeout: float, sleep: Callable[[float], None]) -> Path | None:
    done = _spool() / "done" / request_id
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (done / "result.json").is_file():
            return done
        sleep(0.5)
    return None


def _discard(request_id: str) -> None:
    for bucket in ("requests", "incoming", "done"):
        shutil.rmtree(_spool() / bucket / request_id, ignore_errors=True)


def convert_glb(
    body: bytes,
    *,
    formats: Iterable[str] = EXPORT_FORMATS,
    thumbnail: bool = True,
    capability: BlenderCapability | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ConversionResult:
    """Convert a GLB through the sandboxed converter sidecar.

    Never raises for an unavailable converter or a failed format: the result's
    ``files`` hold only formats that were produced and verified. Input that
    fails validation raises ``ThreeDConversionError`` since nothing may be
    offered for it.
    """
    started = time.monotonic()
    cap = capability or probe_blender_capability()
    result = ConversionResult(capability=cap)
    if not cap.available:
        return result
    requested = [fmt for fmt in formats if fmt in cap.formats]
    want_thumbnail = bool(thumbnail and cap.thumbnail)
    if not requested and not want_thumbnail:
        return result
    validate_glb(body)
    kinds = [*requested, *([THUMBNAIL_KEY] if want_thumbnail else [])]
    try:
        request_id = _submit(body, requested, want_thumbnail)
    except OSError as exc:
        result.failures = {kind: f"spool_unavailable:{type(exc).__name__}" for kind in kinds}
        return result
    try:
        folder = _await_result(request_id, float(settings.THREE_D_CONVERSION_TIMEOUT_SECONDS), sleep)
        if folder is None:
            result.failures = {kind: "timeout" for kind in kinds}
            return result
        try:
            report = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            report = {}
        entries = report.get("results") if isinstance(report, dict) and report.get("ok") else None
        if not isinstance(entries, dict):
            reason = str(report.get("reason") if isinstance(report, dict) else "") or "converter_failed"
            result.failures = {kind: reason[:80] for kind in kinds}
            return result
        paths = {fmt: folder / "out" / fmt / ("model." + fmt) for fmt in requested}
        if want_thumbnail:
            paths[THUMBNAIL_KEY] = folder / "out" / "preview.png"
        for kind, path in paths.items():
            entry = entries.get(kind)
            if not isinstance(entry, dict) or not entry.get("ok"):
                result.failures[kind] = str((entry or {}).get("error") or "export_failed")[:80]
                continue
            try:
                data = _validate_output(kind, path, folder)
            except (ThreeDConversionError, OSError, zipfile.BadZipFile) as exc:
                result.failures[kind] = str(exc) if isinstance(exc, ThreeDConversionError) else type(exc).__name__
                continue
            result.files[kind] = ConvertedFile(
                kind=kind,
                filename=EXPORT_FILENAMES[kind],
                media_type=EXPORT_MEDIA_TYPES[kind],
                body=data,
                sha256=sha256(data).hexdigest(),
            )
    finally:
        _discard(request_id)
        result.seconds = round(time.monotonic() - started, 3)
    return result


def export_key(output_key: str, kind: str) -> str:
    if kind not in EXPORT_FILENAMES:
        raise ThreeDConversionError("unknown export kind")
    base = output_key.rsplit("/", 1)[0]
    return f"{base}/exports/{EXPORT_FILENAMES[kind]}"


def stored_exports(metadata: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Exports that were really produced and stored for an artifact."""
    exports = (metadata or {}).get("exports")
    if not isinstance(exports, dict):
        return {}
    valid: dict[str, dict[str, Any]] = {}
    for kind, entry in exports.items():
        if kind not in EXPORT_FILENAMES or not isinstance(entry, dict):
            continue
        checksum = str(entry.get("sha256") or "")
        if (
            isinstance(entry.get("object_key"), str)
            and len(checksum) == 64
            and isinstance(entry.get("size_bytes"), int)
            and entry["size_bytes"] > 0
        ):
            valid[kind] = entry
    return valid


def export_object_keys(metadata: Mapping[str, Any] | None) -> list[str]:
    return [entry["object_key"] for entry in stored_exports(metadata).values()]
