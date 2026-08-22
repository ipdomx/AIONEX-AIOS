from __future__ import annotations

import pytest

from aios.phase36_audio_transcript import (
    DubbingPlan,
    GovernedAudioSource,
    StockVoiceBinding,
    TranscriptContractError,
    TranscriptDocument,
    TranscriptSegment,
    build_dubbing_plan,
    caption_manifest,
    render_srt,
    render_webvtt,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def source(**overrides) -> GovernedAudioSource:
    payload = {
        "source_sha256": HASH_A,
        "locator_sha256": HASH_B,
        "size_bytes": 480_044,
        "media_type": "audio/wav",
        "duration_ms": 10_000,
        "sample_rate_hz": 48_000,
        "channels": 2,
    }
    payload.update(overrides)
    return GovernedAudioSource(**payload)


def segments() -> tuple[TranscriptSegment, ...]:
    return (
        TranscriptSegment(
            segment_id="segment-001",
            speaker_key="speaker-001",
            start_ms=0,
            end_ms=3_000,
            text="Welcome to AIONEX <safe> & governed.",
            language="en-US",
            confidence=0.98,
        ),
        TranscriptSegment(
            segment_id="segment-002",
            speaker_key="speaker-002",
            start_ms=3_250,
            end_ms=7_500,
            text="Every output keeps its evidence boundary.",
            language="en-US",
            confidence=0.96,
        ),
    )


def transcript(**overrides) -> TranscriptDocument:
    payload = {
        "source": source(),
        "language": "en-US",
        "segments": segments(),
        "diarization_enabled": True,
    }
    payload.update(overrides)
    return TranscriptDocument(**payload)


def voices() -> dict[str, StockVoiceBinding]:
    return {
        "speaker-001": StockVoiceBinding(
            speaker_key="speaker-001",
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            voice="marin",
            runtime_evidence_sha256=HASH_C,
        ),
        "speaker-002": StockVoiceBinding(
            speaker_key="speaker-002",
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            voice="marin",
            runtime_evidence_sha256=HASH_C,
        ),
    }


def test_transcript_public_snapshot_is_deterministic_hash_only_and_pseudonymous() -> (
    None
):
    first = transcript()
    second = transcript()
    assert first.checksum == second.checksum
    snapshot = first.public_snapshot()
    assert snapshot["schema"] == "36G.transcript.public.v1"
    assert snapshot["segment_count"] == 2
    assert snapshot["speaker_keys"] == ["speaker-001", "speaker-002"]
    assert snapshot["raw_transcript_returned"] is False
    assert snapshot["real_speaker_identity_returned"] is False
    assert snapshot["source"]["storage_locator_returned"] is False
    rendered = repr(snapshot)
    assert "Welcome to AIONEX" not in rendered
    assert "Every output keeps" not in rendered
    assert "s3://" not in rendered
    assert "signed_url" not in rendered
    assert snapshot["segments"][0]["text_sha256"]
    assert snapshot["segments"][0]["text_characters"] > 0


def test_private_transcript_contains_text_but_never_a_raw_storage_locator() -> None:
    document = transcript()
    private = document.private_payload()
    assert private["segments"][0]["text"].startswith("Welcome")
    assert private["source"]["locator_sha256"] == HASH_B
    assert "storage_key" not in repr(private)
    assert "signed_url" not in repr(private)


def test_transcript_rejects_real_names_bad_hashes_overlap_and_unproven_multispeaker() -> (
    None
):
    with pytest.raises(TranscriptContractError, match="pseudonymous"):
        TranscriptSegment(
            segment_id="segment-001",
            speaker_key="Ahmed-Tolba",
            start_ms=0,
            end_ms=1_000,
            text="Private identity must not become a speaker key.",
            language="en-US",
        )
    with pytest.raises(TranscriptContractError, match="SHA-256"):
        source(source_sha256="not-a-hash")
    with pytest.raises(TranscriptContractError, match="must not overlap"):
        transcript(
            segments=(
                segments()[0],
                TranscriptSegment(
                    segment_id="segment-overlap",
                    speaker_key="speaker-002",
                    start_ms=2_900,
                    end_ms=4_000,
                    text="This overlaps the first caption cue.",
                    language="en-US",
                ),
            )
        )
    with pytest.raises(TranscriptContractError, match="requires diarization"):
        transcript(diarization_enabled=False)
    with pytest.raises(TranscriptContractError, match="at least two"):
        TranscriptDocument(
            source=source(),
            language="en-US",
            segments=(
                TranscriptSegment(
                    segment_id="segment-001",
                    speaker_key="speaker-001",
                    start_ms=0,
                    end_ms=1_000,
                    text="A single speaker cannot prove diarization.",
                    language="en-US",
                ),
            ),
            diarization_enabled=True,
        )


def test_transcript_rejects_segments_past_source_duration() -> None:
    with pytest.raises(TranscriptContractError, match="source duration"):
        transcript(
            source=source(duration_ms=4_000),
            segments=(
                TranscriptSegment(
                    segment_id="segment-001",
                    speaker_key="speaker-001",
                    start_ms=0,
                    end_ms=4_500,
                    text="This segment exceeds the governed source.",
                    language="en-US",
                ),
            ),
            diarization_enabled=False,
        )


def test_webvtt_and_srt_are_deterministic_timed_and_escape_markup() -> None:
    document = transcript()
    webvtt = render_webvtt(document)
    srt = render_srt(document)
    assert webvtt == render_webvtt(document)
    assert srt == render_srt(document)
    assert webvtt.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.000" in webvtt
    assert "00:00:03,250 --> 00:00:07,500" in srt
    assert "[speaker-001]" in webvtt
    assert "&lt;safe&gt; &amp; governed" in webvtt
    assert "<safe>" not in webvtt


def test_caption_manifest_returns_only_hashes_sizes_and_counts() -> None:
    manifest = caption_manifest(transcript())
    assert manifest["schema"] == "36G.caption-manifest.v1"
    assert manifest["segment_count"] == 2
    assert manifest["speaker_count"] == 2
    assert manifest["diarization_enabled"] is True
    assert manifest["raw_speaker_labels_returned"] is False
    assert len(manifest["webvtt_sha256"]) == 64
    assert len(manifest["srt_sha256"]) == 64
    assert manifest["webvtt_size_bytes"] > 0
    assert manifest["srt_size_bytes"] > 0
    assert manifest["raw_caption_text_returned"] is False
    assert "Welcome" not in repr(manifest)


def test_dubbing_plan_preserves_timing_speaker_scope_and_stock_voice_evidence() -> None:
    document = transcript()
    plan = build_dubbing_plan(
        document,
        target_language="ar-EG",
        translations={
            "segment-001": "مرحبًا بكم في أيونيكس.",
            "segment-002": "كل مخرج يحتفظ بحدود أدلته.",
        },
        voice_bindings=voices(),
        output_profile_id="wav-pcm-48k-stereo",
    )
    assert isinstance(plan, DubbingPlan)
    assert plan.transcript_checksum == document.checksum
    assert [(row.start_ms, row.end_ms) for row in plan.segments] == [
        (0, 3_000),
        (3_250, 7_500),
    ]
    snapshot = plan.public_snapshot()
    assert snapshot["schema"] == "36G.dubbing-plan.public.v1"
    assert snapshot["plan_status"] == "external_gate"
    assert snapshot["render_status"] == "not_started"
    assert snapshot["provider_requests"] == 0
    assert snapshot["provider_spend_usd"] == 0.0
    assert snapshot["voice_clone"] is False
    assert snapshot["voice_transformation"] is False
    assert snapshot["custom_voice"] is False
    assert snapshot["segments"][0]["voice"]["voice_mode"] == "stock"
    assert (
        snapshot["segments"][0]["voice"]["synthetic_voice_disclosure_required"] is True
    )
    rendered = repr(snapshot)
    assert "مرحبًا" not in rendered
    assert "كل مخرج" not in rendered


def test_dubbing_plan_requires_exact_translation_and_voice_coverage() -> None:
    document = transcript()
    with pytest.raises(TranscriptContractError, match="exactly cover"):
        build_dubbing_plan(
            document,
            target_language="ar-EG",
            translations={"segment-001": "ترجمة واحدة فقط."},
            voice_bindings=voices(),
        )
    with pytest.raises(
        TranscriptContractError, match="exactly cover transcript speakers"
    ):
        build_dubbing_plan(
            document,
            target_language="ar-EG",
            translations={
                "segment-001": "الجزء الأول.",
                "segment-002": "الجزء الثاني.",
            },
            voice_bindings={"speaker-001": voices()["speaker-001"]},
        )


def test_stock_voice_binding_rejects_custom_identity_and_missing_disclosure() -> None:
    with pytest.raises(TranscriptContractError, match="speaker key"):
        StockVoiceBinding(
            speaker_key="real-person-name",
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            voice="marin",
            runtime_evidence_sha256=HASH_C,
        )
    with pytest.raises(TranscriptContractError, match="disclosure"):
        StockVoiceBinding(
            speaker_key="speaker-001",
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            voice="marin",
            runtime_evidence_sha256=HASH_C,
            synthetic_voice_disclosure_required=False,
        )


def test_dubbing_plan_is_deterministic_and_requires_all_external_execution_gates() -> (
    None
):
    document = transcript()
    translations = {
        "segment-001": "الجزء الأول المحكوم.",
        "segment-002": "الجزء الثاني المحكوم.",
    }
    voice_bindings = voices()
    first = build_dubbing_plan(
        document,
        target_language="ar-EG",
        translations=translations,
        voice_bindings=voice_bindings,
        output_profile_id="m4a-aac-48k-stereo",
    )
    second = build_dubbing_plan(
        document,
        target_language="ar-EG",
        translations=translations,
        voice_bindings=voice_bindings,
        output_profile_id="m4a-aac-48k-stereo",
    )
    assert first.checksum == second.checksum
    assert set(first.external_gates) == {
        "translation-runtime-evidence",
        "segment-stock-tts-execution",
        "timing-fit-and-alignment",
        "final-local-master",
    }
    assert first.public_snapshot()["output_profile_id"] == "m4a-aac-48k-stereo"
