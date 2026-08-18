from __future__ import annotations

import pytest

from aios.design_factory import (
    BrandKit,
    DesignFactoryError,
    DesignRequest,
    IMAGE_PROVIDER_CAPABILITIES,
    build_design_plan,
    editable_svg_template,
)


def request(**overrides) -> DesignRequest:
    payload = {
        "title": "AIONEX launch identity",
        "brief": "Create a premium visual identity that feels intelligent, precise and modern.",
        "use_case": "logo",
        "preset_id": "logo-square",
        "style": "minimal futuristic",
        "target_audience": "technology founders",
        "exact_text": ("AIONEX",),
        "negative_constraints": ("illegible text", "watermark", "visual clutter"),
        "transparent_background": True,
        "brand": BrandKit("AIONEX", primary="#1d4ed8", secondary="#020617", accent="#38bdf8"),
    }
    payload.update(overrides)
    return DesignRequest(**payload)


def test_design_plan_is_deterministic_and_never_claims_template_is_final() -> None:
    first = build_design_plan(request())
    second = build_design_plan(request())
    assert first.checksum == second.checksum
    assert first.render_status == "planned"
    assert first.editable_source == "svg"
    svg = editable_svg_template(first)
    assert 'data-aionex-status="template"' in svg
    assert 'data-layer="headline"' in svg
    assert "final" not in first.render_status


def test_launch_provider_matrix_uses_current_models_and_excludes_deprecated_imagen() -> None:
    plan = build_design_plan(request(transparent_background=False))
    models = {item.model for item in plan.provider_candidates}
    assert "gpt-image-2" in models
    assert "gemini-3.1-flash-image" in models
    assert "gemini-3-pro-image" in models
    assert "flux-kontext-pro" in models
    assert not any("imagen" in model for model in models)
    assert not any(model == "gpt-image-1" for model in models)


def test_transparent_logo_routes_only_to_capability_that_declares_transparency() -> None:
    plan = build_design_plan(request(transparent_background=True))
    assert [item.provider for item in plan.provider_candidates] == ["openai"]
    prompt = plan.compiled_prompts[0]
    assert prompt.model == "gpt-image-2"
    assert prompt.settings["background"] == "transparent"


def test_high_resolution_poster_keeps_current_4k_gemini_candidates() -> None:
    plan = build_design_plan(
        request(
            use_case="poster",
            preset_id="poster-portrait",
            transparent_background=False,
        )
    )
    four_k = {item.model for item in plan.provider_candidates if item.max_resolution >= 4096}
    assert {"gemini-3.1-flash-image", "gemini-3-pro-image"} <= four_k


def test_provider_prompt_compilation_retains_brand_text_and_constraints() -> None:
    plan = build_design_plan(request(transparent_background=False))
    for compiled in plan.compiled_prompts:
        assert "AIONEX" in compiled.prompt
        assert "#1d4ed8" in compiled.prompt
        assert "technology founders" in compiled.prompt
        assert compiled.settings["target_width"] == 1024
        assert compiled.settings["target_height"] == 1024


def test_invalid_brand_or_unknown_operation_fails_closed() -> None:
    with pytest.raises(DesignFactoryError, match="brand colors"):
        BrandKit("bad", primary="blue")
    with pytest.raises(DesignFactoryError, match="operation"):
        request(operation="fake-final")


def test_openai_image_adapter_default_tracks_live_gpt_image_2_inventory() -> None:
    import inspect

    from aios.providers.adapters.openai import OpenAIProvider

    assert inspect.signature(OpenAIProvider.image).parameters["model"].default == "gpt-image-2"


def test_gemini_flash_lite_declares_only_live_supported_jpeg_output() -> None:
    by_model = {item.model: item for item in IMAGE_PROVIDER_CAPABILITIES if item.provider == "gemini"}
    assert by_model["gemini-3.1-flash-lite-image"].output_formats == frozenset({"jpeg"})
    assert {"png", "jpeg"} <= by_model["gemini-3.1-flash-image"].output_formats
    assert {"png", "jpeg"} <= by_model["gemini-3-pro-image"].output_formats
