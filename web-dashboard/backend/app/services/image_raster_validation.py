"""Dependency-free raster envelope validation shared by Phase 36E workers."""
from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_BODY_BYTES = 32 * 1024 * 1024
_MAX_PNG_PIXELS = 16_777_216
_MAX_PNG_CHUNKS = 1024


class ImageRasterValidationError(ValueError):
    """Raster bytes do not match the declared governed image format."""


@dataclass(frozen=True)
class PngAlphaCoverage:
    """Decoded alpha coverage for a bounded 8-bit RGBA PNG."""

    width: int
    height: int
    pixel_count: int
    transparent_pixels: int
    opaque_pixels: int
    partial_pixels: int

    @property
    def non_opaque_fraction(self) -> float:
        return (self.transparent_pixels + self.partial_pixels) / self.pixel_count


def inspect_raster(body: bytes, output_format: str) -> tuple[int, int]:
    """Validate PNG/JPEG/WebP envelopes and return bounded pixel dimensions."""
    if output_format == "png":
        if len(body) < 24 or body[:8] != _PNG_SIGNATURE or body[12:16] != b"IHDR":
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


def inspect_png_alpha_coverage(
    body: bytes,
    *,
    max_body_bytes: int = _MAX_PNG_BODY_BYTES,
    max_pixels: int = _MAX_PNG_PIXELS,
) -> PngAlphaCoverage:
    """Decode bounded RGBA PNG alpha and reject structurally meaningless output.

    This intentionally supports only 8-bit, non-interlaced RGBA PNGs. It verifies
    chunk CRCs, bounded compressed/decompressed sizes, scanline filters, and
    requires both some transparency and some non-transparency. It does not claim
    source-resolution preservation or semantic edge/mask quality.
    """
    if not isinstance(body, (bytes, bytearray)):
        raise ImageRasterValidationError("PNG output must be bytes")
    if len(body) > max_body_bytes:
        raise ImageRasterValidationError("PNG output exceeds the compressed size limit")
    if len(body) < 33 or body[:8] != _PNG_SIGNATURE:
        raise ImageRasterValidationError("image output is not a complete PNG")

    pos = 8
    chunk_count = 0
    width = height = 0
    seen_ihdr = False
    seen_idat = False
    idat_closed = False
    seen_iend = False
    compressed = bytearray()

    while pos < len(body):
        if chunk_count >= _MAX_PNG_CHUNKS:
            raise ImageRasterValidationError("PNG contains too many chunks")
        if pos + 12 > len(body):
            raise ImageRasterValidationError("PNG chunk is truncated")
        length = int.from_bytes(body[pos:pos + 4], "big")
        chunk_type = bytes(body[pos + 4:pos + 8])
        data_start = pos + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if data_end < data_start or crc_end > len(body):
            raise ImageRasterValidationError("PNG chunk is truncated")
        chunk_data = bytes(body[data_start:data_end])
        expected_crc = int.from_bytes(body[data_end:crc_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ImageRasterValidationError("PNG chunk CRC mismatch")
        chunk_count += 1

        if chunk_count == 1 and chunk_type != b"IHDR":
            raise ImageRasterValidationError("PNG IHDR must be the first chunk")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise ImageRasterValidationError("PNG IHDR is invalid")
            seen_ihdr = True
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if not width or not height or width > 16384 or height > 16384:
                raise ImageRasterValidationError("PNG dimensions are outside the allowed range")
            if width * height > max_pixels:
                raise ImageRasterValidationError("PNG pixel count exceeds the decode limit")
            if bit_depth != 8 or color_type != 6:
                raise ImageRasterValidationError("PNG alpha validation requires 8-bit RGBA")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise ImageRasterValidationError("PNG encoding mode is unsupported for alpha validation")
        elif chunk_type == b"IDAT":
            if not seen_ihdr or idat_closed:
                raise ImageRasterValidationError("PNG IDAT ordering is invalid")
            seen_idat = True
            if len(compressed) + length > max_body_bytes:
                raise ImageRasterValidationError("PNG compressed image data exceeds the limit")
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0 or not seen_idat:
                raise ImageRasterValidationError("PNG IEND is invalid")
            seen_iend = True
            pos = crc_end
            if pos != len(body):
                raise ImageRasterValidationError("PNG contains trailing data after IEND")
            break
        else:
            if seen_idat:
                idat_closed = True
            if chunk_type[:1].isupper() and chunk_type != b"PLTE":
                raise ImageRasterValidationError("PNG contains an unsupported critical chunk")
        pos = crc_end

    if not (seen_ihdr and seen_idat and seen_iend):
        raise ImageRasterValidationError("PNG is missing required chunks")

    row_bytes = width * 4
    expected_decoded = height * (row_bytes + 1)
    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(bytes(compressed), expected_decoded + 1)
    except zlib.error as exc:
        raise ImageRasterValidationError("PNG IDAT decompression failed") from exc
    if len(raw) > expected_decoded or decompressor.unconsumed_tail:
        raise ImageRasterValidationError("PNG decoded data exceeds the expected size")
    if not decompressor.eof or decompressor.unused_data:
        raise ImageRasterValidationError("PNG IDAT stream is incomplete or contains trailing data")
    if len(raw) != expected_decoded:
        raise ImageRasterValidationError("PNG decoded data length is invalid")

    previous = bytearray(row_bytes)
    offset = 0
    transparent = opaque = partial = 0

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        encoded = raw[offset:offset + row_bytes]
        offset += row_bytes
        decoded = bytearray(row_bytes)
        for i, value in enumerate(encoded):
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
                raise ImageRasterValidationError("PNG scanline filter is unsupported")
            decoded[i] = (value + predictor) & 0xFF
        for alpha in decoded[3::4]:
            if alpha == 0:
                transparent += 1
            elif alpha == 255:
                opaque += 1
            else:
                partial += 1
        previous = decoded

    pixels = width * height
    if opaque == pixels:
        raise ImageRasterValidationError("PNG alpha is fully opaque")
    if transparent == pixels:
        raise ImageRasterValidationError("PNG alpha is fully transparent")

    return PngAlphaCoverage(
        width=width,
        height=height,
        pixel_count=pixels,
        transparent_pixels=transparent,
        opaque_pixels=opaque,
        partial_pixels=partial,
    )
