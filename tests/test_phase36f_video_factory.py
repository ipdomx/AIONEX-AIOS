from __future__ import annotations

import pytest

from aios.video_factory import (
    VIDEO_PROVIDER_CAPABILITIES,
    VideoFactoryError,
    VideoRequest,
    VideoRuntimeEvidence,
    build_video_plan,
    build_video_plan_for_provider,
    runtime_ready_provider,
)


def request(**overrides) -> VideoRequest:
    payload = {
        "title": "AIONEX launch film",
        "brief": "Create a concise premium launch film that explains the product value without fabricating claims.",
        "operation": "text-to-video",
        "use_case": "advertisement",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "style": "premium cinematic",
        "target_audience": "technology founders",
        "brand_name": "AIONEX",
        "exact_text": ("AIONEX",),
        "negative_constraints": ("watermark", "fabricated claims"),
    }
    payload.update(overrides)
    return VideoRequest(**payload)


def test_video_plan_is_deterministic_multi_scene_and_never_claims_rendered_output() -> None:
    first = build_video_plan(request())
    second = build_video_plan(request())
    assert first.checksum == second.checksum
    assert first.continuity_id == second.continuity_id
    assert first.continuity_id.startswith("vid-")
    assert first.render_status == "planned"
    assert len(first.scenes) == 4
    assert [scene.scene_id for scene in first.scenes] == ["opening", "value", "proof", "close"]
    assert [scene.duration_seconds for scene in first.scenes] == [4, 8, 8, 4]
    assert len(first.compiled_scenes) == 4
    assert all(first.continuity_id in item.prompt for item in first.compiled_scenes)
    snapshot = first.public_snapshot()
    assert snapshot["schema"] == "36F.video-plan.v1"
    assert snapshot["render_status"] == "planned"
    assert "credential" not in repr(snapshot).lower()
    assert "api_key" not in repr(snapshot).lower()


def test_launch_matrix_uses_visible_current_video_models_and_does_not_invent_fireworks_generation() -> None:
    models = {(item.provider, item.model) for item in VIDEO_PROVIDER_CAPABILITIES}
    assert ("openai", "sora-2") in models
    assert ("openai", "sora-2-pro") in models
    assert ("gemini", "gemini-omni-flash-preview") in models
    assert ("gemini", "veo-3.1-generate-preview") in models
    assert ("gemini", "veo-3.1-fast-generate-preview") in models
    assert ("gemini", "veo-3.1-lite-generate-preview") in models
    assert not any(provider == "fireworks" for provider, _ in models)


def test_sora_compile_matches_exact_create_contract_and_does_not_claim_unverified_edit_or_extend() -> None:
    plan = build_video_plan(request())
    assert plan.provider_candidates[0].provider == "openai"
    assert plan.provider_candidates[0].model == "sora-2"
    assert "edit" not in plan.provider_candidates[0].operations
    assert "extend" not in plan.provider_candidates[0].operations
    opening = plan.compiled_scenes[0]
    assert opening.endpoint_kind == "openai-video-job"
    assert opening.settings == {
        "endpoint": "/v1/videos",
        "model": "sora-2",
        "seconds": 4,
        "size": "1280x720",
        "reference_required": False,
        "async_job": True,
    }


def test_high_resolution_contract_routes_away_from_sora_and_to_veo_only() -> None:
    plan = build_video_plan(request(resolution="4k"))
    assert plan.provider_candidates
    assert all(item.provider == "gemini" for item in plan.provider_candidates)
    assert all("veo-3.1" in item.model for item in plan.provider_candidates)
    assert all("4k" in item.resolutions for item in plan.provider_candidates)
    assert all(item.model != "veo-3.1-lite-generate-preview" for item in plan.provider_candidates)
    assert plan.compiled_scenes[0].endpoint_kind == "gemini-long-running-video"
    assert plan.compiled_scenes[0].settings["resolution"] == "4k"


def test_reference_operations_are_fail_closed_and_text_to_video_cannot_smuggle_reference() -> None:
    with pytest.raises(VideoFactoryError, match="exactly one governed reference"):
        request(operation="logo-to-video")
    logo = request(operation="logo-to-video", reference_count=1, use_case="logo-animation")
    plan = build_video_plan(logo)
    assert all(scene.reference_role == "logo" for scene in plan.scenes)
    assert all(item.settings["reference_required"] is True for item in plan.compiled_scenes)
    with pytest.raises(VideoFactoryError, match="cannot smuggle"):
        request(reference_count=1)
    with pytest.raises(VideoFactoryError, match="exactly one"):
        request(operation="image-to-video", reference_count=2)


def test_runtime_selected_provider_changes_plan_checksum_and_compiled_model() -> None:
    req = request()
    standard = build_video_plan_for_provider(req, provider="openai", model="sora-2")
    pro = build_video_plan_for_provider(req, provider="openai", model="sora-2-pro")
    assert standard.checksum != pro.checksum
    assert standard.continuity_id != pro.continuity_id
    assert {row.model for row in standard.compiled_scenes} == {"sora-2"}
    assert {row.model for row in pro.compiled_scenes} == {"sora-2-pro"}


def test_inventory_visibility_never_means_live_ready() -> None:
    req = request()
    with pytest.raises(VideoFactoryError, match="no live-proven"):
        runtime_ready_provider(
            req,
            evidence=(
                VideoRuntimeEvidence(
                    provider="openai",
                    model="sora-2",
                    state="inventory_visible",
                    reason="credential model inventory only",
                ),
            ),
        )
    ready = runtime_ready_provider(
        req,
        evidence=(
            VideoRuntimeEvidence(
                provider="openai",
                model="sora-2",
                state="ready",
                proven_operations=frozenset({"text-to-video"}),
                reason="future bounded provider acceptance",
            ),
        ),
    )
    assert ready.model == "sora-2"


def test_unknown_operation_resolution_and_scene_contracts_fail_closed() -> None:
    with pytest.raises(VideoFactoryError, match="operation"):
        request(operation="fake-final")
    with pytest.raises(VideoFactoryError, match="resolution"):
        request(resolution="8k")
    with pytest.raises(VideoFactoryError, match="no launch video provider"):
        build_video_plan(request(operation="remix", reference_count=1, resolution="4k"))
