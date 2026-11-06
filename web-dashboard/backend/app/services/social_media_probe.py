"""Dependency-free media header probing for P3 publishing validation.

Reads only container headers: JPEG/PNG/WebP/GIF dimensions and MP4/MOV
duration and track dimensions. The result feeds platform validation in the
composer and the worker; Meta still validates on its side. Nothing here
decodes pixels or trusts a client-declared size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

IMAGE_TYPES = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}
# A moov atom can sit at the end of an MP4; probing reads at most this much.
MAX_PROBE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class MediaProbe:
    kind: str  # image | video
    media_type: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class MediaProbeError(ValueError):
    """The bytes are not a supported image or video container."""


def sniff_media_type(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        return "video/quicktime" if brand == b"qt  " else "video/mp4"
    return None


def _png(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise MediaProbeError("png-header-invalid")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _gif(data: bytes) -> tuple[int, int]:
    if len(data) < 10:
        raise MediaProbeError("gif-header-invalid")
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _webp(data: bytes) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise MediaProbeError("webp-header-invalid")


_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data: bytes) -> tuple[int, int]:
    index = 2
    length = len(data)
    while index + 4 <= length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xFF:
            index += 1
            continue
        segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if marker in _JPEG_SOF:
            if index + 9 > length:
                break
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        if segment < 2:
            break
        index += 2 + segment
    raise MediaProbeError("jpeg-dimensions-missing")


_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(data: bytes, start: int, end: int):
    index = start
    while index + 8 <= end:
        size, kind = struct.unpack(">I4s", data[index : index + 8])
        header = 8
        if size == 1:
            if index + 16 > end:
                return
            size = struct.unpack(">Q", data[index + 8 : index + 16])[0]
            header = 16
        elif size == 0:
            size = end - index
        if size < header or index + size > end:
            # A truncated box (typically mdat past the probe window) ends the walk.
            yield kind, index + header, end, True
            return
        yield kind, index + header, index + size, False
        index += size


def _mp4(data: bytes) -> tuple[int | None, int | None, int | None]:
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    stack = [(0, len(data))]
    while stack:
        start, end = stack.pop()
        for kind, body, box_end, truncated in _boxes(data, start, end):
            if truncated and kind != b"moov":
                continue
            if kind in _CONTAINER_BOXES:
                stack.append((body, box_end))
            elif kind == b"mvhd" and body + 4 <= box_end:
                version = data[body]
                if version == 1 and body + 32 <= box_end:
                    timescale, duration = struct.unpack(">IQ", data[body + 20 : body + 32])
                elif body + 20 <= box_end:
                    timescale, duration = struct.unpack(">II", data[body + 12 : body + 20])
                else:
                    continue
                if timescale > 0:
                    duration_ms = int(duration * 1000 / timescale)
            elif kind == b"tkhd" and body + 4 <= box_end:
                version = data[body]
                # tkhd ends with width and height (16.16 fixed point).
                offset = body + (96 if version == 1 else 84)
                if offset <= box_end:
                    track_width = struct.unpack(">I", data[offset - 8 : offset - 4])[0] >> 16
                    track_height = struct.unpack(">I", data[offset - 4 : offset])[0] >> 16
                    if track_width and track_height and width is None:
                        width, height = track_width, track_height
    return width, height, duration_ms


def probe(data: bytes, *, declared_type: str | None = None) -> MediaProbe:
    """Identify the media by its magic bytes (never by the declared type)."""

    detected = sniff_media_type(data[:16])
    if detected is None:
        raise MediaProbeError("unsupported-media-type")
    # The browser-declared type is never trusted; the sniffed type always wins.
    del declared_type
    if detected in IMAGE_TYPES:
        parser = {"image/jpeg": _jpeg, "image/png": _png, "image/webp": _webp, "image/gif": _gif}
        try:
            width, height = parser[detected](data)
        except (struct.error, IndexError) as exc:
            raise MediaProbeError("image-header-invalid") from exc
        if width <= 0 or height <= 0:
            raise MediaProbeError("image-dimensions-invalid")
        return MediaProbe(kind="image", media_type=detected, width=width, height=height)
    try:
        video_width, video_height, duration_ms = _mp4(data[:MAX_PROBE_BYTES])
    except (struct.error, IndexError) as exc:
        raise MediaProbeError("video-header-invalid") from exc
    return MediaProbe(
        kind="video",
        media_type=detected,
        width=video_width,
        height=video_height,
        duration_ms=duration_ms
    )
