"""Request validation shared by the AIONEX RunPod 3D handlers (FR-16D).

Pure Pillow/stdlib so it is unit-tested in the repository without a GPU stack.
The Hunyuan3D and TripoSR images each carry a byte-identical copy; a repository
test enforces that the two copies never drift.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import warnings

from PIL import Image

MAX_IMAGE_BASE64_CHARS = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 4096 * 4096
MIN_IMAGE_EDGE = 64
ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
SEED_MAX = 2**31 - 1

# Decompression-bomb guard: Pillow raises DecompressionBombError above twice
# this limit; the warning band in between is promoted to an error as well.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
warnings.simplefilter("error", Image.DecompressionBombWarning)


class InputError(ValueError):
    """The request was rejected before any model work."""


def reject_unknown_fields(payload: dict, allowed: frozenset[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise InputError("unsupported input fields: " + ", ".join(sorted(map(str, unknown))))


def bounded_int(payload: dict, key: str, default: int, low: int, high: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InputError(f"{key} must be an integer between {low} and {high}")
    return value


def decode_image(raw: object) -> Image.Image:
    """Decode a base64 PNG/JPEG/WebP with size, type and pixel-count limits."""
    if not isinstance(raw, str) or not raw:
        raise InputError("input.image required")
    if len(raw) > MAX_IMAGE_BASE64_CHARS:
        raise InputError("input.image exceeds the size limit")
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InputError("input.image is not valid base64") from exc
    if not blob or len(blob) > MAX_IMAGE_BYTES:
        raise InputError("input.image exceeds the size limit")
    try:
        image = Image.open(BytesIO(blob))
        if image.format not in ALLOWED_IMAGE_FORMATS:
            raise InputError("input.image must be PNG, JPEG or WebP")
        width, height = image.size
        if width * height > MAX_IMAGE_PIXELS or min(width, height) < MIN_IMAGE_EDGE:
            raise InputError("input.image dimensions are outside the allowed range")
        if getattr(image, "n_frames", 1) != 1:
            raise InputError("input.image must be a single frame")
        image.load()
        return image.convert("RGBA")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InputError("input.image dimensions are outside the allowed range") from exc
    except (OSError, SyntaxError) as exc:
        raise InputError("input.image could not be decoded") from exc
