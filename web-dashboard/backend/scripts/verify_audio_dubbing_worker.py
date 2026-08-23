from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import app.db.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.services.audio_dubbing_providers import (
    DubbingTranslationSourceSegment,
    ProviderDubbingTranslationRequest,
    estimate_openai_translation_cost,
)
from app.services.audio_dubbing_worker import AudioDubbingWorker
from app.services.media_storage import LocalMediaObjectStore


class NoClaimAuthority:
    claim_calls = 0

    async def claim(self):
        self.claim_calls += 1
        raise AssertionError("disabled dubbing worker must not call claim")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="phase36g-dubbing-smoke-") as root:
        root_path = Path(root)
        settings.AUDIO_DUBBING_LIVE_ENABLED = False
        settings.AUDIO_DUBBING_WORKER_HEALTH_FILE = str(root_path / "health.json")
        authority = NoClaimAuthority()
        worker = AudioDubbingWorker(
            authority=authority,  # type: ignore[arg-type]
            store=LocalMediaObjectStore(root_path / "objects"),
            adapters={},
            worker_id="phase36g-dubbing-offline-smoke",
        )
        worked = await worker.run_once()
        health = json.loads((root_path / "health.json").read_text(encoding="utf-8"))
        columns = set(Base.metadata.tables["audio_dubbing_executions"].c.keys())
        required = {
            "status",
            "provider_state",
            "armed_at",
            "provider_submitted_at",
            "attempts",
            "max_attempts",
            "lease_token",
            "lease_owner",
            "lease_expires_at",
            "fencing_token",
            "source_transcript_storage_key",
            "source_transcript_checksum",
            "voice_bindings",
            "estimated_translation_cost_usd",
            "max_translation_cost_usd",
            "speech_cost_upper_bound_usd",
            "max_total_cost_usd",
            "translation_storage_key",
            "translation_checksum",
            "speech_pipelines",
            "replacement_history",
            "final_graph_id",
            "final_output_checksum",
        }
        segments = (
            DubbingTranslationSourceSegment(
                segment_id="segment-001",
                speaker_key="speaker-001",
                start_ms=0,
                end_ms=2_000,
                text="A private governed source segment.",
            ),
        )
        request = ProviderDubbingTranslationRequest(
            provider="openai",
            model="gpt-5.6-luna",
            source_language="en",
            target_language="es",
            segments=segments,
        )
        estimate, pricing = estimate_openai_translation_cost(
            source_characters=len(segments[0].text),
            segment_count=1,
        )
        assert worked is False
        assert authority.claim_calls == 0
        assert health["status"] == "disabled"
        assert health["live_enabled"] is False
        assert health["cycles"] == 0
        assert health["errors"] == 0
        assert health["stock_voice_only"] is True
        assert health["custom_voice_enabled"] is False
        assert health["known_speaker_identification_enabled"] is False
        assert health["voice_clone_enabled"] is False
        assert health["voice_transformation_enabled"] is False
        assert health["raw_translation_returned"] is False
        assert health["raw_transcript_returned"] is False
        assert health["secret_returned"] is False
        assert required <= columns
        assert request.model == "gpt-5.6-luna"
        assert estimate > 0
        assert pricing["estimate_only"] is True
        print(
            json.dumps(
                {
                    "schema": "36G.stage6.audio-dubbing-worker-offline.v1",
                    "status": "pass",
                    "worker_health": health,
                    "translation_model": request.model,
                    "speech_model": "gpt-4o-mini-tts-2025-12-15",
                    "estimated_translation_cost_usd": estimate,
                    "required_schema_columns": sorted(required),
                    "provider_translation_requests": 0,
                    "provider_speech_requests": 0,
                    "provider_spend_usd": 0.0,
                    "credential_read": False,
                    "raw_translation_returned": False,
                    "secret_returned": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
