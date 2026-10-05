from __future__ import annotations

import hashlib

from app.services.design_editable_source import build_rendered_editable_svg


def _contract() -> dict:
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


def test_fr14c_rendered_editable_svg_is_explicitly_raster_backed() -> None:
    raster = b"fr14c-verified-raster"
    checksum = hashlib.sha256(raster).hexdigest()

    for media_type in ("image/png", "image/jpeg", "image/webp"):
        result = build_rendered_editable_svg(
            contract=_contract(),
            raster_body=raster,
            raster_media_type=media_type,
            raster_checksum=checksum,
        )

        assert result.media_type == "image/svg+xml"
        assert result.representation == "raster-backed-editable-svg"
        assert result.vector_native is False
        assert result.raster_backed is True
        assert result.editable_layers == ("brand-guides", "editable-copy")

        svg = result.body.decode("utf-8")
        assert 'data-aionex-representation="raster-backed-editable-svg"' in svg
        assert 'data-aionex-vector-native="false"' in svg
        assert 'data-aionex-raster-backed="true"' in svg
        assert 'data-layer="generated-raster"' in svg
        assert 'data-layer="brand-guides" display="none"' in svg
        assert 'data-layer="editable-copy" display="none"' in svg
        assert f"data:{media_type};base64," in svg
        assert f"&quot;base_raster_media_type&quot;:&quot;{media_type}&quot;" in svg


def test_fr14c_truthfulness_fields_are_deterministic() -> None:
    raster = b"fr14c-deterministic-raster"
    checksum = hashlib.sha256(raster).hexdigest()
    first = build_rendered_editable_svg(
        contract=_contract(),
        raster_body=raster,
        raster_media_type="image/png",
        raster_checksum=checksum,
    )
    second = build_rendered_editable_svg(
        contract=_contract(),
        raster_body=raster,
        raster_media_type="image/png",
        raster_checksum=checksum,
    )

    assert first == second
    assert first.checksum == hashlib.sha256(first.body).hexdigest()


if __name__ == "__main__":
    test_fr14c_rendered_editable_svg_is_explicitly_raster_backed()
    test_fr14c_truthfulness_fields_are_deterministic()
