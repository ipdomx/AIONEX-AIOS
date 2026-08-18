from __future__ import annotations

import pytest

from aios.design_factory import (
    BrandKit,
    DesignFactoryError,
    DesignRequest,
    IMAGE_PROVIDER_CAPABILITIES,
    ProviderRuntimeEvidence,
    build_design_plan,
    editable_svg_template,
    responsive_raster_exports,
    route_live_provider,
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
        "transparent_background": False,
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


def test_gpt_image_2_does_not_claim_transparency_or_background_remove() -> None:
    openai = next(
        item
        for item in IMAGE_PROVIDER_CAPABILITIES
        if item.provider == "openai" and item.model == "gpt-image-2"
    )
    assert openai.supports_transparency is False
    assert "background-remove" not in openai.operations
    with pytest.raises(DesignFactoryError, match="no launch image provider"):
        build_design_plan(request(transparent_background=True))
    with pytest.raises(DesignFactoryError, match="no live-proven"):
        route_live_provider(
            request(operation="background-remove", reference_count=1),
            output_format="png",
            evidence=(
                ProviderRuntimeEvidence(
                    provider="openai",
                    model="gpt-image-2",
                    state="ready",
                    proven_operations=frozenset({"generate", "edit", "inpaint"}),
                    verified_output_formats=frozenset({"png"}),
                    reason="bounded production evidence",
                ),
            ),
        )


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


def stage3_runtime_evidence() -> tuple[ProviderRuntimeEvidence, ...]:
    return (
        ProviderRuntimeEvidence(
            provider="openai",
            model="gpt-image-2",
            state="ready",
            proven_operations=frozenset({"generate", "edit"}),
            verified_output_formats=frozenset({"png"}),
            reason="bounded production generation and reference edit accepted",
        ),
        ProviderRuntimeEvidence(
            provider="gemini",
            model="gemini-3.1-flash-lite-image",
            state="external_gate",
            reason="provider quota gate",
        ),
        ProviderRuntimeEvidence(
            provider="fireworks",
            model="flux-1-schnell-fp8",
            state="external_gate",
            reason="configured model unavailable for current credential",
        ),
    )



def stage4c_runtime_evidence() -> tuple[ProviderRuntimeEvidence, ...]:
    return (
        ProviderRuntimeEvidence(
            provider="openai",
            model="gpt-image-2",
            state="ready",
            proven_operations=frozenset({"generate", "edit", "inpaint"}),
            verified_output_formats=frozenset({"png"}),
            reason="bounded production generation, reference edit and mask edit accepted",
        ),
        *stage3_runtime_evidence()[1:],
    )


def test_stage4c_inpaint_route_is_live_proven_without_promoting_background_remove() -> None:
    decision = route_live_provider(
        request(operation="inpaint", reference_count=1),
        output_format="png",
        evidence=stage4c_runtime_evidence(),
    )
    assert decision.provider == "openai"
    assert decision.model == "gpt-image-2"
    assert decision.operation == "inpaint"
    with pytest.raises(DesignFactoryError, match="no live-proven"):
        route_live_provider(
            request(operation="background-remove", reference_count=1),
            output_format="png",
            evidence=stage4c_runtime_evidence(),
        )


def test_stage4_live_route_requires_explicit_runtime_evidence() -> None:
    decision = route_live_provider(
        request(transparent_background=False),
        output_format="png",
        evidence=stage3_runtime_evidence(),
    )
    assert decision.provider == "openai"
    assert decision.model == "gpt-image-2"
    assert decision.evidence_state == "ready"


def test_stage4_live_route_does_not_promote_unproven_operations_or_formats() -> None:
    with pytest.raises(DesignFactoryError, match="no live-proven"):
        route_live_provider(
            request(operation="inpaint", reference_count=1, transparent_background=False),
            output_format="png",
            evidence=stage3_runtime_evidence(),
        )
    with pytest.raises(DesignFactoryError, match="no live-proven"):
        route_live_provider(
            request(transparent_background=False),
            output_format="jpeg",
            evidence=stage3_runtime_evidence(),
        )


def test_stage4_high_resolution_export_can_route_through_bounded_source_raster() -> None:
    decision = route_live_provider(
        request(
            use_case="infographic",
            preset_id="infographic-portrait",
            transparent_background=False,
        ),
        output_format="png",
        evidence=stage3_runtime_evidence(),
    )
    assert decision.provider == "openai"
    assert decision.requires_resampling is True
    assert decision.target_preset_id == "infographic-portrait"


def test_stage4_responsive_derivative_plan_is_governed_and_alpha_safe() -> None:
    exports = responsive_raster_exports(
        request(transparent_background=True),
        derivative_preset_ids=("social-square", "social-portrait", "story-vertical"),
    )
    assert exports
    assert all(item.output_format != "jpeg" for item in exports)
    assert len({item.filename for item in exports}) == len(exports)
    assert {item.preset_id for item in exports} == {
        "logo-square",
        "social-square",
        "social-portrait",
        "story-vertical",
    }


def test_provider_prompt_pack_declares_provider_native_output_format() -> None:
    plan = build_design_plan(request(transparent_background=False))
    by_model = {item.model: item for item in plan.compiled_prompts}
    assert by_model["gemini-3.1-flash-lite-image"].settings["output_format"] == "jpeg"
    assert by_model["gemini-3.1-flash-image"].settings["output_format"] == "png"
    assert by_model["flux-kontext-pro"].settings["output_format"] == "png"


def test_ready_runtime_evidence_cannot_be_empty_or_duplicated() -> None:
    with pytest.raises(DesignFactoryError, match="requires proven"):
        ProviderRuntimeEvidence(provider="openai", model="gpt-image-2", state="ready")
    duplicate = stage3_runtime_evidence()[0]
    with pytest.raises(DesignFactoryError, match="duplicate"):
        route_live_provider(
            request(transparent_background=False),
            output_format="png",
            evidence=(duplicate, duplicate),
        )
