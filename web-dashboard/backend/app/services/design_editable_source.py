"""Deterministic editable SVG composition backed by a verified rendered raster."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any

_EDITABLE_SCHEMA = "36E.editable.v1"
_ALLOWED_RASTER_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_RASTER_BYTES = 32 * 1024 * 1024


class DesignEditableSourceError(RuntimeError):
    """A rendered editable source cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class EditableSourceResult:
    body: bytes
    checksum: str
    size_bytes: int
    media_type: str = "image/svg+xml"
    schema: str = _EDITABLE_SCHEMA


def _bounded_text(value: Any, *, name: str, minimum: int = 1, maximum: int) -> str:
    text = str(value or "").strip()
    if not minimum <= len(text) <= maximum:
        raise DesignEditableSourceError(f"editable source {name} is invalid")
    return text


def _contract(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != _EDITABLE_SCHEMA:
        raise DesignEditableSourceError("editable source contract is invalid")
    title = _bounded_text(payload.get("title"), name="title", minimum=2, maximum=200)
    use_case = _bounded_text(payload.get("use_case"), name="use case", maximum=40)
    preset_id = _bounded_text(payload.get("preset_id"), name="preset", maximum=80)
    raw_width = payload.get("width")
    raw_height = payload.get("height")
    if raw_width is None or raw_height is None or isinstance(raw_width, bool) or isinstance(raw_height, bool):
        raise DesignEditableSourceError("editable source dimensions are invalid")
    try:
        width = int(raw_width)
        height = int(raw_height)
    except (TypeError, ValueError) as exc:
        raise DesignEditableSourceError("editable source dimensions are invalid") from exc
    if not (1 <= width <= 8192 and 1 <= height <= 8192):
        raise DesignEditableSourceError("editable source dimensions are invalid")
    raw_brand = payload.get("brand")
    if not isinstance(raw_brand, dict):
        raise DesignEditableSourceError("editable source brand contract is invalid")
    brand_name = _bounded_text(raw_brand.get("name"), name="brand name", maximum=120)
    palette = raw_brand.get("palette")
    if (
        not isinstance(palette, list)
        or len(palette) != 5
        or any(not isinstance(item, str) or not _HEX.fullmatch(item) for item in palette)
    ):
        raise DesignEditableSourceError("editable source brand palette is invalid")
    fonts = raw_brand.get("fonts")
    if (
        not isinstance(fonts, list)
        or not 1 <= len(fonts) <= 6
        or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in fonts)
    ):
        raise DesignEditableSourceError("editable source brand fonts are invalid")
    exact = payload.get("exact_text") or []
    if (
        not isinstance(exact, list)
        or len(exact) > 20
        or any(not isinstance(item, str) or len(item) > 500 for item in exact)
    ):
        raise DesignEditableSourceError("editable source copy contract is invalid")
    return {
        "schema": _EDITABLE_SCHEMA,
        "title": title,
        "use_case": use_case,
        "preset_id": preset_id,
        "width": width,
        "height": height,
        "brand": {
            "name": brand_name,
            "palette": list(palette),
            "fonts": [item.strip() for item in fonts],
        },
        "exact_text": list(exact),
    }


def build_rendered_editable_svg(
    *,
    contract: dict[str, Any],
    raster_body: bytes,
    raster_media_type: str,
    raster_checksum: str,
) -> EditableSourceResult:
    """Embed the verified rendered raster as the visible base of an editable SVG composition."""
    safe = _contract(contract)
    if raster_media_type not in _ALLOWED_RASTER_MEDIA_TYPES:
        raise DesignEditableSourceError("editable source raster media type is unsupported")
    if not raster_body or len(raster_body) > _MAX_RASTER_BYTES:
        raise DesignEditableSourceError("editable source raster size is outside the governed range")
    digest = hashlib.sha256(raster_body).hexdigest()
    if digest != raster_checksum:
        raise DesignEditableSourceError("editable source raster checksum verification failed")

    width = int(safe["width"])
    height = int(safe["height"])
    brand = safe["brand"]
    palette: list[str] = brand["palette"]
    fonts: list[str] = brand["fonts"]
    encoded = base64.b64encode(raster_body).decode("ascii")
    metadata = html.escape(
        json.dumps(
            {
                "schema": safe["schema"],
                "title": safe["title"],
                "use_case": safe["use_case"],
                "preset_id": safe["preset_id"],
                "brand": brand,
                "exact_text": safe["exact_text"],
                "base_raster_sha256": digest,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    copy = safe["exact_text"] or [safe["title"]]
    copy_nodes: list[str] = []
    for index, item in enumerate(copy):
        y = min(height - 24, 72 + index * 56)
        copy_nodes.append(
            f'<text data-copy-index="{index}" x="48" y="{y}" fill="{palette[4]}" '
            f'font-family="{html.escape(fonts[0], quote=True)}" font-size="40">'
            f'{html.escape(item)}</text>'
        )
    swatches = "".join(
        f'<rect data-swatch-index="{index}" x="{32 + index * 52}" y="32" width="40" height="40" fill="{color}"/>'
        for index, color in enumerate(palette)
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" data-aionex-status="rendered-editable" '
        f'data-aionex-schema="{_EDITABLE_SCHEMA}" data-aionex-base-sha256="{digest}">'
        f'<metadata data-layer="aionex-contract">{metadata}</metadata>'
        f'<g data-layer="generated-raster"><image width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice" href="data:{raster_media_type};base64,{encoded}"/></g>'
        f'<g data-layer="brand-guides" display="none">{swatches}</g>'
        f'<g data-layer="editable-copy" display="none">{"".join(copy_nodes)}</g>'
        '</svg>'
    ).encode("utf-8")
    return EditableSourceResult(
        body=svg,
        checksum=hashlib.sha256(svg).hexdigest(),
        size_bytes=len(svg),
    )
