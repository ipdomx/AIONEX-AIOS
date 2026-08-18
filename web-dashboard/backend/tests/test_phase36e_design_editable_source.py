from __future__ import annotations

import base64
import hashlib

import pytest

from app.services.design_editable_source import (
    DesignEditableSourceError,
    build_rendered_editable_svg,
)


def contract() -> dict:
    return {
        "schema": "36E.editable.v1",
        "title": "AIONEX editable visual",
        "use_case": "social-post",
        "preset_id": "social-square",
        "width": 1080,
        "height": 1080,
        "brand": {
            "name": "AIONEX",
            "palette": ["#1d4ed8", "#020617", "#38bdf8", "#ffffff", "#0f172a"],
            "fonts": ["Inter", "Arial"],
        },
        "exact_text": ["AIONEX", "Build with confidence"],
    }


def test_rendered_editable_svg_is_deterministic_backed_by_verified_raster_and_prompt_free() -> None:
    raster = b"verified-raster-bytes"
    checksum = hashlib.sha256(raster).hexdigest()
    first = build_rendered_editable_svg(
        contract=contract(),
        raster_body=raster,
        raster_media_type="image/png",
        raster_checksum=checksum,
    )
    second = build_rendered_editable_svg(
        contract=contract(),
        raster_body=raster,
        raster_media_type="image/png",
        raster_checksum=checksum,
    )
    assert first == second
    assert first.checksum == hashlib.sha256(first.body).hexdigest()
    text = first.body.decode("utf-8")
    assert 'data-aionex-status="rendered-editable"' in text
    assert f'data-aionex-base-sha256="{checksum}"' in text
    assert base64.b64encode(raster).decode("ascii") in text
    assert 'data-layer="generated-raster"' in text
    assert 'data-layer="editable-copy" display="none"' in text
    assert "prompt" not in text.lower()


def test_rendered_editable_svg_rejects_bad_checksum_media_and_contract() -> None:
    raster = b"verified-raster-bytes"
    checksum = hashlib.sha256(raster).hexdigest()
    with pytest.raises(DesignEditableSourceError, match="checksum"):
        build_rendered_editable_svg(
            contract=contract(), raster_body=raster, raster_media_type="image/png", raster_checksum="0" * 64
        )
    with pytest.raises(DesignEditableSourceError, match="media type"):
        build_rendered_editable_svg(
            contract=contract(), raster_body=raster, raster_media_type="image/gif", raster_checksum=checksum
        )
    bad = contract()
    bad["brand"] = {"name": "AIONEX", "palette": ["blue"], "fonts": ["Inter"]}
    with pytest.raises(DesignEditableSourceError, match="palette"):
        build_rendered_editable_svg(
            contract=bad, raster_body=raster, raster_media_type="image/png", raster_checksum=checksum
        )
