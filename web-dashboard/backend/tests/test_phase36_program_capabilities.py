from __future__ import annotations

import pytest

from app.api.v1.endpoints.capabilities import phase36_capabilities


@pytest.mark.asyncio
async def test_phase36_public_capability_snapshot_is_truthful_and_non_secret() -> None:
    payload = await phase36_capabilities()
    assert payload["authoritative"] is True
    assert payload["minimum_concurrent_users"] == 1000
    assert payload["current_batch"] == "36G"
    batch_statuses = {batch["batch_id"]: batch["status"] for batch in payload["batches"]}
    assert batch_statuses["36B"] == "complete"
    assert batch_statuses["36C"] == "complete"
    assert batch_statuses["36D"] == "complete"
    assert batch_statuses["36E"] == "complete"
    assert batch_statuses["36F"] == "complete"
    assert batch_statuses["36G"] == "in_progress"
    capabilities = {
        item["capability_id"]: item
        for batch in payload["batches"]
        for item in batch["capabilities"]
    }
    assert capabilities["audio-cleanup-master"]["maturity"] == "runtime_verified"
    assert "SFX" not in capabilities["audio-cleanup-master"]["title"]
    assert capabilities["stt-tts-dubbing"]["maturity"] == "source_built"
    assert capabilities["podcast-jingle-narration"]["maturity"] == "source_built"
    assert capabilities["song-production"]["maturity"] == "specified"
    assert capabilities["voice-transformation"]["maturity"] == "specified"
    assert payload["completion"] < 100
    assert payload["production_ready_capabilities"] < payload["total_capabilities"]
    rendered = repr(payload).lower()
    for forbidden in ("api_key", "password", "authorization", "credential_value"):
        assert forbidden not in rendered
