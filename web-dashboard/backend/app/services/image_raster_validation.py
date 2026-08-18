"""Dependency-free raster envelope validation shared by Phase 36E workers."""
from __future__ import annotations

import struct


class ImageRasterValidationError(ValueError):
    """Raster bytes do not match the declared governed image format."""


def inspect_raster(body: bytes, output_format: str) -> tuple[int, int]:
    """Validate PNG/JPEG/WebP envelopes and return bounded pixel dimensions."""
    if output_format == "png":
        if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
            raise ImageRasterValidationError("image output is not a valid PNG envelope")
        width, height = struct.unpack(">II", body[16:24])
    elif output_format == "jpeg":
        if len(body) < 4 or body[:2] != b"\xff\xd8":
            raise ImageRasterValidationError("image output is not a valid JPEG envelope")
        pos = 2
        width = height = 0
        while pos + 4 <= len(body):
            if body[pos] != 0xFF:
                pos += 1
                continue
            while pos < len(body) and body[pos] == 0xFF:
                pos += 1
            if pos >= len(body):
                break
            marker = body[pos]
            pos += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if pos + 2 > len(body):
                break
            length = int.from_bytes(body[pos:pos + 2], "big")
            if length < 2 or pos + length > len(body):
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                if length < 7:
                    break
                height = int.from_bytes(body[pos + 3:pos + 5], "big")
                width = int.from_bytes(body[pos + 5:pos + 7], "big")
                break
            pos += length
        if not width or not height:
            raise ImageRasterValidationError("JPEG dimensions are unavailable")
    elif output_format == "webp":
        if len(body) < 30 or body[:4] != b"RIFF" or body[8:12] != b"WEBP":
            raise ImageRasterValidationError("image output is not a valid WebP envelope")
        chunk = body[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(body[24:27], "little")
            height = 1 + int.from_bytes(body[27:30], "little")
        elif chunk == b"VP8L" and len(body) >= 25 and body[20] == 0x2F:
            bits = int.from_bytes(body[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
        elif chunk == b"VP8 " and len(body) >= 30 and body[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(body[26:28], "little") & 0x3FFF
            height = int.from_bytes(body[28:30], "little") & 0x3FFF
        else:
            raise ImageRasterValidationError("WebP dimensions are unavailable")
    else:
        raise ImageRasterValidationError("image output format is unsupported")
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ImageRasterValidationError("image dimensions are outside the allowed range")
    return width, height
