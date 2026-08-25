from __future__ import annotations

import pytest

from app.api.v1.endpoints.capabilities import phase36_capabilities


@pytest.mark.asyncio
async def test_phase36_public_capability_snapshot_is_truthful_and_non_secret() -> None:
    payload = await phase36_capabilities()
    assert payload["authoritative"] is True
    assert payload["minimum_concurrent_users"] == 1000
    assert payload["current_batch"] == "36K"
    batch_statuses = {batch["batch_id"]: batch["status"] for batch in payload["batches"]}
    assert batch_statuses["36B"] == "complete"
    assert batch_statuses["36C"] == "complete"
    assert batch_statuses["36D"] == "complete"
    assert batch_statuses["36E"] == "complete"
    assert batch_statuses["36F"] == "complete"
    assert batch_statuses["36G"] == "external_gate"
    assert batch_statuses["36H"] == "external_gate"
    assert batch_statuses["36I"] == "external_gate"
    assert batch_statuses["36J"] == "complete"
    capabilities = {
        item["capability_id"]: item
        for batch in payload["batches"]
        for item in batch["capabilities"]
    }
    assert capabilities["stock-voice-tts"]["maturity"] == "runtime_verified"
    assert capabilities["stock-voice-tts"]["external_gates"] == (
        "synthetic-voice-disclosure",
    )
    assert "stock-voice" in capabilities["stock-voice-tts"]["title"].lower()
    assert capabilities["governed-stt-transcript"]["maturity"] == "runtime_verified"
    assert capabilities["governed-stt-transcript"]["external_gates"] == ()
    assert capabilities["multi-speaker-diarization"]["maturity"] == "runtime_verified"
    assert capabilities["multi-speaker-diarization"]["external_gates"] == ()
    assert capabilities["audio-cleanup-master"]["maturity"] == "runtime_verified"
    assert "SFX" not in capabilities["audio-cleanup-master"]["title"]
    assert capabilities["complete-stock-voice-dubbing"]["maturity"] == "runtime_verified"
    assert capabilities["complete-stock-voice-dubbing"]["external_gates"] == ()
    assert capabilities["stt-tts-dubbing"]["maturity"] == "source_built"
    assert capabilities["podcast-jingle-narration"]["maturity"] == "source_built"
    assert capabilities["lyria-3-music-generation"]["maturity"] == "source_built"
    assert capabilities["lyria-3-music-generation"]["external_gates"] == (
        "valid-replicate-credential",
        "lyria-preview-runtime-evidence",
        "music-rights-and-synthid-disclosure",
    )
    assert capabilities["stable-audio-instrumental-generation"]["maturity"] == "runtime_verified"
    assert capabilities["stable-audio-instrumental-generation"]["external_gates"] == (
        "funded-stability-credential",
        "music-rights-and-ai-generated-disclosure",
    )
    assert capabilities["song-production"]["maturity"] == "source_built"
    assert capabilities["song-production"]["external_gates"] == (
        "ace-step-open-song-runtime-acceptance",
        "music-rights-and-ai-generated-disclosure",
    )
    assert capabilities["voice-transformation"]["maturity"] == "specified"
    assert payload["completion"] < 100
    assert payload["production_ready_capabilities"] < payload["total_capabilities"]
    rendered = repr(payload).lower()
    for forbidden in ("api_key", "password", "authorization", "credential_value"):
        assert forbidden not in rendered
