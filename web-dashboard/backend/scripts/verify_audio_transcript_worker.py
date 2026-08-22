from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.core.config import settings
from app.db.base import Base
import app.db.models  # noqa: F401
from app.services.audio_transcript_providers import (
    ProviderTranscriptRequest,
    estimate_openai_transcription_cost,
)
from app.services.audio_transcript_worker import AudioTranscriptWorker
from app.services.media_storage import LocalMediaObjectStore


class NoClaimAuthority:
    claim_calls = 0

    async def claim(self):
        self.claim_calls += 1
        raise AssertionError("disabled transcript worker must not call claim")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="phase36g-transcript-smoke-") as root:
        root_path = Path(root)
        settings.AUDIO_TRANSCRIPT_LIVE_ENABLED = False
        settings.AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE = str(root_path / "health.json")
        authority = NoClaimAuthority()
        worker = AudioTranscriptWorker(
            authority=authority,  # type: ignore[arg-type]
            store=LocalMediaObjectStore(root_path / "objects"),
            worker_id="phase36g-transcript-offline-smoke",
        )
        worked = await worker.run_once()
        health = json.loads((root_path / "health.json").read_text(encoding="utf-8"))
        columns = set(Base.metadata.tables["audio_transcript_executions"].c.keys())
        required = {
            "status",
            "armed_at",
            "provider_state",
            "provider_submitted_at",
            "attempts",
            "max_attempts",
            "lease_token",
            "lease_owner",
            "lease_expires_at",
            "fencing_token",
            "source_storage_key",
            "source_checksum",
            "source_size_bytes",
            "source_duration_ms",
            "estimated_cost_usd",
            "max_cost_usd",
            "actual_cost_usd",
            "transcript_checksum",
            "transcript_text_sha256",
            "output_storage_key",
            "output_checksum",
        }
        assert worked is False
        assert authority.claim_calls == 0
        assert health["status"] == "disabled"
        assert health["live_enabled"] is False
        assert health["cycles"] == 0
        assert health["errors"] == 0
        assert health["secret_returned"] is False
        assert health["raw_transcript_returned"] is False
        assert required <= columns
        estimate, pricing = estimate_openai_transcription_cost(5_000)
        request = ProviderTranscriptRequest(
            provider="openai",
            model="gpt-4o-mini-transcribe-2025-12-15",
            audio=b"RIFF-governed-placeholder",
            media_type="audio/wav",
            source_sha256="a" * 64,
            duration_ms=5_000,
            language="en-US",
        )
        assert request.response_format == "json"
        assert estimate == 0.00025
        assert pricing["estimated_price_per_minute_usd"] == 0.003
        print(
            json.dumps(
                {
                    "schema": "36G.stage4b.audio-transcript-worker-offline.v1",
                    "status": "pass",
                    "worker_health": health,
                    "model": request.model,
                    "response_format": request.response_format,
                    "estimated_cost_usd_for_5s": estimate,
                    "required_schema_columns": sorted(required),
                    "provider_transcription_requests": 0,
                    "provider_spend_usd": 0.0,
                    "credential_read": False,
                    "secret_returned": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
