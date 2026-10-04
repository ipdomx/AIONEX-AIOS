from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import zlib

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "image_raster_validation.py"
)
SPEC = importlib.util.spec_from_file_location("fr14_image_raster_validation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ImageRasterValidationError = MODULE.ImageRasterValidationError
inspect_png_alpha_coverage = MODULE.inspect_png_alpha_coverage


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _rgba_png(rows: list[list[tuple[int, int, int, int]]], *, filter_type: int = 0) -> bytes:
    height = len(rows)
    width = len(rows[0])
    raw = bytearray()
    previous = bytearray(width * 4)
    for row in rows:
        decoded = bytearray(channel for pixel in row for channel in pixel)
        encoded = bytearray(len(decoded))
        for i, value in enumerate(decoded):
            left = decoded[i - 4] if i >= 4 else 0
            up = previous[i]
            up_left = previous[i - 4] if i >= 4 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                p = left + up - up_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - up_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
            else:
                raise AssertionError("unsupported test filter")
            encoded[i] = (value - predictor) & 0xFF
        raw.append(filter_type)
        raw.extend(encoded)
        previous = decoded
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_accepts_real_rgba_png_and_measures_alpha_coverage(filter_type: int) -> None:
    body = _rgba_png(
        [
            [(10, 20, 30, 0), (40, 50, 60, 255)],
            [(70, 80, 90, 128), (100, 110, 120, 255)],
        ],
        filter_type=filter_type,
    )

    result = inspect_png_alpha_coverage(body)

    assert (result.width, result.height, result.pixel_count) == (2, 2, 4)
    assert result.transparent_pixels == 1
    assert result.opaque_pixels == 2
    assert result.partial_pixels == 1
    assert result.non_opaque_fraction == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("alpha", "message"),
    [(255, "fully opaque"), (0, "fully transparent")],
)
def test_rejects_meaningless_uniform_alpha(alpha: int, message: str) -> None:
    body = _rgba_png([[(1, 2, 3, alpha), (4, 5, 6, alpha)]])

    with pytest.raises(ImageRasterValidationError, match=message):
        inspect_png_alpha_coverage(body)


def test_rejects_non_rgba_png() -> None:
    raw = b"\x00" + bytes((1, 2, 3))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    body = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )

    with pytest.raises(ImageRasterValidationError, match="requires 8-bit RGBA"):
        inspect_png_alpha_coverage(body)


def test_rejects_crc_corruption_and_truncation() -> None:
    body = bytearray(_rgba_png([[(1, 2, 3, 0), (4, 5, 6, 255)]]))
    body[29] ^= 0x01

    with pytest.raises(ImageRasterValidationError, match="CRC mismatch"):
        inspect_png_alpha_coverage(bytes(body))

    valid = _rgba_png([[(1, 2, 3, 0), (4, 5, 6, 255)]])
    with pytest.raises(ImageRasterValidationError):
        inspect_png_alpha_coverage(valid[:-5])


def test_rejects_pixel_and_compressed_size_limits() -> None:
    body = _rgba_png([[(1, 2, 3, 0), (4, 5, 6, 255)]])

    with pytest.raises(ImageRasterValidationError, match="pixel count"):
        inspect_png_alpha_coverage(body, max_pixels=1)

    with pytest.raises(ImageRasterValidationError, match="compressed size"):
        inspect_png_alpha_coverage(body, max_body_bytes=len(body) - 1)
