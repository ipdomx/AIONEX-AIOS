from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aios.audio_factory import (
    AUDIO_OUTPUT_PROFILES,
    AUDIO_PROVIDER_CAPABILITIES,
    AudioFactoryError,
    AudioRequest,
    AudioRuntimeEvidence,
    VoiceRightsEvidence,
    build_audio_plan,
    cue_sheet_payload,
    mix_plan_markdown,
    runtime_ready_provider,
    ssml_template,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def request(**overrides) -> AudioRequest:
    payload = {
        "title": "AIONEX governed narration",
        "brief": "Create a clear multilingual narration plan without claiming provider execution.",
        "operation": "narration",
        "use_case": "education",
        "language": "ar-EG",
        "purpose": "course-narration",
        "script": "مرحبًا بكم في منصة AIONEX.",
        "speaker_count": 1,
        "voice_mode": "stock",
        "source_count": 0,
        "output_profile_id": "wav-pcm-48k-stereo",
    }
    payload.update(overrides)
    return AudioRequest(**payload)


def rights(**overrides) -> VoiceRightsEvidence:
    payload = {
        "subject_ref_hash": HASH_A,
        "consent_evidence_sha256": HASH_B,
        "rights_basis": "licensed-performer",
        "allowed_operations": frozenset({"voice-transform"}),
        "allowed_purposes": ("localized-advertisement",),
        "issued_at": "2026-08-20T00:00:00+00:00",
        "expires_at": "2026-09-20T00:00:00+00:00",
        "revocable": True,
    }
    payload.update(overrides)
    return VoiceRightsEvidence(**payload)


def test_narration_plan_is_deterministic_provider_neutral_and_never_claims_rendered_audio() -> None:
    first = build_audio_plan(request())
    second = build_audio_plan(request())
    assert first.checksum == second.checksum
    assert first.plan_status == "planned"
    assert first.render_status == "not_started"
    assert [item.operation for item in first.tasks] == [
        "script",
        "synthesize-speech",
        "cleanup",
        "master",
        "qa",
        "package",
    ]
    snapshot = first.public_snapshot()
    assert snapshot["schema"] == "36G.audio-plan.v1"
    assert snapshot["external_requests"] == 0
    assert snapshot["external_cost_usd"] == 0.0
    assert snapshot["estimated_external_cost_usd"] is None
    assert snapshot["render_status"] == "not_started"
    assert snapshot["request"]["script_length"] > 0
    assert "مرحبًا" not in repr(snapshot)
    rendered = repr(snapshot).lower()
    for forbidden in ("credential", "api_key", "authorization", "signed_url"):
        assert forbidden not in rendered


def test_provider_inventory_is_official_visibility_only_and_invents_no_music_or_clone_route() -> None:
    models = {(item.provider, item.model) for item in AUDIO_PROVIDER_CAPABILITIES}
    assert ("openai", "gpt-4o-mini-tts-2025-12-15") in models
    assert ("openai", "gpt-4o-mini-transcribe-2025-12-15") in models
    assert ("openai", "gpt-4o-transcribe-diarize") in models
    assert ("openai", "gpt-audio") in models
    assert ("openai", "gpt-realtime-1.5") in models
    assert ("gemini", "gemini-3.7-flash") in models
    assert ("gemini", "gemini-2.5-flash-preview-tts") in models
    assert ("gemini", "gemini-2.5-pro-preview-tts") in models
    assert all(item.official_source.startswith("https://") for item in AUDIO_PROVIDER_CAPABILITIES)
    assert not any("compose-music" in item.operations for item in AUDIO_PROVIDER_CAPABILITIES)
    assert not any("generate-vocals" in item.operations for item in AUDIO_PROVIDER_CAPABILITIES)
    assert not any("voice-clone" in item.operations for item in AUDIO_PROVIDER_CAPABILITIES)
    plan = build_audio_plan(request())
    snapshot = plan.public_snapshot()
    inventory = snapshot["provider_inventory"]
    assert len(inventory) == 8
    assert {item["inventory_state"] for item in inventory} == {"inventory_visible"}
    realtime = next(item for item in inventory if item["model"] == "gpt-realtime-1.5")
    assert realtime["execution_modes"] == ["realtime"]
    speech_candidates = {
        (item.provider, item.model)
        for item in dict(plan.task_provider_candidates)["speech"]
    }
    assert ("openai", "gpt-4o-mini-tts-2025-12-15") in speech_candidates
    assert ("openai", "gpt-audio") in speech_candidates
    assert ("openai", "gpt-realtime-1.5") not in speech_candidates
    transcript_plan = build_audio_plan(
        request(
            operation="transcription",
            script="",
            voice_mode="none",
            source_count=1,
            speaker_count=1,
        )
    )
    transcript_candidates = {
        (item.provider, item.model)
        for item in dict(transcript_plan.task_provider_candidates)["transcript"]
    }
    assert (
        "openai",
        "gpt-4o-mini-transcribe-2025-12-15",
    ) in transcript_candidates

    diarization_plan = build_audio_plan(
        request(
            operation="transcription",
            use_case="podcast",
            script="",
            voice_mode="none",
            source_count=1,
            speaker_count=2,
        )
    )
    diarization_candidates = {
        (item.provider, item.model)
        for item in dict(diarization_plan.task_provider_candidates)["diarization"]
    }
    assert ("openai", "gpt-4o-transcribe-diarize") in diarization_candidates


def test_multispeaker_transcription_has_ordered_analysis_transcript_diarization_and_no_fake_render() -> None:
    plan = build_audio_plan(
        request(
            operation="transcription",
            use_case="podcast",
            script="",
            voice_mode="none",
            source_count=1,
            speaker_count=3,
        )
    )
    assert [item.task_id for item in plan.tasks] == [
        "ingest",
        "analyze",
        "transcript",
        "diarization",
        "qa",
        "package",
    ]
    candidates = dict(plan.task_provider_candidates)
    assert {item.provider for item in candidates["transcript"]} == {"openai", "gemini"}
    assert [(item.provider, item.model) for item in candidates["diarization"]] == [
        ("openai", "gpt-4o-transcribe-diarize"),
        ("gemini", "gemini-3.7-flash"),
    ]
    assert plan.plan_status == "planned"
    assert plan.render_status == "not_started"


def test_dubbing_requires_source_and_target_language_and_builds_alignment_mix_master_graph() -> None:
    with pytest.raises(AudioFactoryError, match="at least one governed source"):
        request(operation="dubbing", source_count=0, target_language="en-US")
    with pytest.raises(AudioFactoryError, match="target language"):
        request(operation="dubbing", source_count=1, target_language=None)
    plan = build_audio_plan(
        request(
            operation="dubbing",
            use_case="localization",
            source_count=1,
            target_language="en-US",
            speaker_count=2,
        )
    )
    assert [item.operation for item in plan.tasks] == [
        "ingest-audio",
        "analyze-audio",
        "transcribe",
        "diarize",
        "translate",
        "synthesize-speech",
        "align",
        "mix",
        "master",
        "qa",
        "package",
    ]
    speech = next(item for item in plan.tasks if item.task_id == "speech")
    assert speech.native_multi_speaker_required is True
    assert {item.provider for item in dict(plan.task_provider_candidates)["speech"]} == {"gemini"}
    alignment = next(item for item in plan.tasks if item.task_id == "alignment")
    assert alignment.depends_on == ("speech", "ingest")


def test_song_and_jingle_remain_truthful_external_gates_without_generation_providers() -> None:
    for operation in ("song", "jingle"):
        plan = build_audio_plan(
            request(
                operation=operation,
                use_case="music",
                include_music=True,
                include_sfx=True,
            )
        )
        assert plan.plan_status == "external_gate"
        assert plan.render_status == "not_started"
        assert "provider-runtime:compose-music" in plan.external_gates
        assert "provider-runtime:generate-vocals" in plan.external_gates
        assert "provider-runtime:generate-sfx" in plan.external_gates
        snapshot = plan.public_snapshot()
        gated = {item["operation"] for item in snapshot["tasks"] if item["state"] == "external_gate"}
        assert {"compose-music", "generate-vocals", "generate-sfx"} <= gated


def test_voice_operation_requires_valid_scoped_rights_and_never_accepts_raw_permission_claims() -> None:
    voice_request = request(
        operation="voice-transform",
        use_case="advertisement",
        purpose="localized-advertisement",
        source_count=1,
        voice_mode="licensed",
    )
    with pytest.raises(AudioFactoryError, match="consent and rights evidence"):
        build_audio_plan(voice_request, at=NOW)
    with pytest.raises(AudioFactoryError, match="does not authorize"):
        build_audio_plan(
            voice_request,
            rights_evidence=rights(allowed_purposes=("audiobook",)),
            at=NOW,
        )
    with pytest.raises(AudioFactoryError, match="does not authorize"):
        build_audio_plan(
            voice_request,
            rights_evidence=rights(expires_at="2026-08-21T11:00:00+00:00"),
            at=NOW,
        )
    with pytest.raises(AudioFactoryError, match="does not authorize"):
        build_audio_plan(
            voice_request,
            rights_evidence=rights(revoked_at="2026-08-21T10:00:00+00:00"),
            at=NOW,
        )


def test_valid_voice_transform_rights_are_hash_only_and_provider_execution_stays_gated() -> None:
    plan = build_audio_plan(
        request(
            operation="voice-transform",
            use_case="advertisement",
            purpose="localized-advertisement",
            source_count=1,
            voice_mode="licensed",
        ),
        rights_evidence=rights(),
        at=NOW,
    )
    assert plan.plan_status == "external_gate"
    assert plan.external_gates == ("provider-runtime:voice-transform",)
    snapshot = plan.public_snapshot()
    evidence = snapshot["rights"]["evidence"]
    assert evidence["subject_ref_hash"] == HASH_A
    assert evidence["consent_evidence_sha256"] == HASH_B
    assert evidence["revoked"] is False
    assert snapshot["external_requests"] == 0
    assert "localized-advertisement" in evidence["allowed_purposes"]


def test_voice_clone_is_stricter_than_consent_and_requires_provider_identity_verification() -> None:
    clone_request = request(
        operation="voice-clone",
        use_case="audiobook",
        purpose="personal-audiobook",
        source_count=1,
        voice_mode="user-owned",
    )
    with pytest.raises(AudioFactoryError, match="self or verified-provider-share"):
        build_audio_plan(
            clone_request,
            rights_evidence=rights(
                allowed_operations=frozenset({"voice-clone"}),
                allowed_purposes=("personal-audiobook",),
            ),
            at=NOW,
        )
    own_rights = rights(
        rights_basis="self",
        allowed_operations=frozenset({"voice-clone"}),
        allowed_purposes=("personal-audiobook",),
    )
    plan = build_audio_plan(clone_request, rights_evidence=own_rights, at=NOW)
    assert plan.external_gates == (
        "voice-clone-provider-identity-verification",
        "provider-runtime:voice-clone",
    )
    verified = rights(
        rights_basis="verified-provider-share",
        provider_verification_ref_hash=HASH_C,
        allowed_operations=frozenset({"voice-clone"}),
        allowed_purposes=("personal-audiobook",),
    )
    verified_plan = build_audio_plan(clone_request, rights_evidence=verified, at=NOW)
    assert verified_plan.external_gates == ("provider-runtime:voice-clone",)
    assert verified_plan.public_snapshot()["rights"]["evidence"][
        "provider_verification_ref_hash"
    ] == HASH_C


def test_inventory_visibility_never_means_live_ready() -> None:
    plan = build_audio_plan(request())
    speech_task = next(item for item in plan.tasks if item.operation == "synthesize-speech")
    with pytest.raises(AudioFactoryError, match="no live-proven"):
        runtime_ready_provider(
            speech_task,
            evidence=(
                AudioRuntimeEvidence(
                    provider="openai",
                    model="gpt-audio",
                    state="inventory_visible",
                    reason="official model inventory only",
                ),
            ),
        )
    ready = runtime_ready_provider(
        speech_task,
        evidence=(
            AudioRuntimeEvidence(
                provider="openai",
                model="gpt-audio",
                state="ready",
                proven_operations=frozenset({"synthesize-speech"}),
                reason="future bounded live acceptance",
            ),
        ),
    )
    assert ready.provider == "openai"
    assert ready.model == "gpt-audio"
    pinned = runtime_ready_provider(
        speech_task,
        evidence=(
            AudioRuntimeEvidence(
                provider="openai",
                model="gpt-4o-mini-tts-2025-12-15",
                state="ready",
                proven_operations=frozenset({"synthesize-speech"}),
                reason="bounded stock-voice runtime acceptance candidate",
            ),
        ),
    )
    assert pinned.provider == "openai"
    assert pinned.model == "gpt-4o-mini-tts-2025-12-15"


def test_output_profiles_and_qa_truthfully_separate_runtime_verified_from_source_built() -> None:
    assert AUDIO_OUTPUT_PROFILES["wav-pcm-48k-stereo"].runtime_state == "runtime_verified"
    assert AUDIO_OUTPUT_PROFILES["wav-pcm-48k-mono"].runtime_state == "source_built"
    assert AUDIO_OUTPUT_PROFILES["m4a-aac-48k-stereo"].runtime_state == "source_built"
    assert AUDIO_OUTPUT_PROFILES["webm-opus-48k-stereo"].runtime_state == "source_built"
    narration = build_audio_plan(request())
    song = build_audio_plan(request(operation="song", use_case="music"))
    assert narration.qa_contract.target_integrated_lufs == -16.0
    assert narration.qa_contract.max_loudness_range_lu == 12.0
    assert song.qa_contract.target_integrated_lufs == -14.0
    assert song.qa_contract.max_loudness_range_lu == 20.0
    assert narration.qa_contract.require_ebur128_scan is True
    assert narration.qa_contract.require_clipping_scan is True


def test_ssml_cue_sheet_and_mix_plan_are_editable_source_artifacts_not_fake_audio() -> None:
    plan = build_audio_plan(request(script="AIONEX <safe> & governed"))
    ssml = ssml_template(plan)
    assert ssml.startswith('<speak xml:lang="ar-EG">')
    assert "&lt;safe&gt; &amp; governed" in ssml
    cue = cue_sheet_payload(plan)
    assert cue["schema"] == "36G.audio-cue-sheet.v1"
    assert cue["render_status"] == "not_started"
    assert cue["plan_checksum"] == plan.checksum
    assert "AIONEX <safe>" not in repr(cue)
    notes = mix_plan_markdown(plan)
    assert "no rendered audio is claimed" in notes
    assert "External provider requests: **0**" in notes
    assert "Estimated external cost: **unknown" in notes


def test_invalid_audio_contracts_fail_closed() -> None:
    with pytest.raises(AudioFactoryError, match="operation"):
        request(operation="fake-final")
    with pytest.raises(AudioFactoryError, match="output profile"):
        request(output_profile_id="mp3-invented")
    with pytest.raises(AudioFactoryError, match="exactly one governed source"):
        request(operation="voice-transform", source_count=2, voice_mode="licensed")
    with pytest.raises(AudioFactoryError, match="hash"):
        rights(subject_ref_hash="raw-person-name")
    with pytest.raises(AudioFactoryError, match="timezone-aware"):
        rights(issued_at="2026-08-20T00:00:00")
