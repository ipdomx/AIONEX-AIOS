"""Offline no-network verification for the Phase 36G stock-speech worker."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from aios.audio_factory import AUDIO_PROVIDER_CAPABILITIES
from app.core.config import settings
from app.db.base import Base
from app.db import models as _models  # noqa: F401
from app.services.audio_speech_providers import default_speech_adapters
from app.services.audio_speech_worker import AudioSpeechWorker
from app.services.media_storage import LocalMediaObjectStore


class NoClaimAuthority:
    async def claim(self):
        raise AssertionError("disabled stock-speech worker must not call claim")


async def main() -> int:
    if settings.AUDIO_SPEECH_LIVE_ENABLED:
        raise RuntimeError("offline stock-speech verification requires live=false")
    with tempfile.TemporaryDirectory(prefix="aionex-p36g-speech-") as temporary:
        root = Path(temporary)
        settings.AUDIO_SPEECH_WORKER_HEALTH_FILE = str(root / "health.json")
        worker = AudioSpeechWorker(
            authority=NoClaimAuthority(),  # type: ignore[arg-type]
            store=LocalMediaObjectStore(root / "objects"),
            adapters=default_speech_adapters(),
            worker_id="phase36g-stock-speech-offline-smoke",
        )
        worked = await worker.run_once()
        if worked:
            raise RuntimeError("disabled stock-speech worker unexpectedly performed work")
        health = json.loads((root / "health.json").read_text(encoding="utf-8"))
        columns = set(Base.metadata.tables["audio_speech_executions"].c.keys())
        required_columns = {
            "status",
            "provider_state",
            "armed_at",
            "provider_submitted_at",
            "fencing_token",
            "estimated_cost_usd",
            "max_cost_usd",
            "actual_cost_usd",
            "output_checksum",
        }
        if not required_columns <= columns:
            raise RuntimeError("stock-speech durable schema contract is incomplete")
        inventory = [
            item
            for item in AUDIO_PROVIDER_CAPABILITIES
            if item.provider == "openai"
            and item.model == "gpt-4o-mini-tts-2025-12-15"
        ]
        if len(inventory) != 1 or inventory[0].operations != frozenset(
            {"synthesize-speech"}
        ):
            raise RuntimeError("pinned stock-speech provider inventory is unavailable")
        payload = {
            "schema": "36G.stage3.stock-speech-worker-offline.v1",
            "status": "pass",
            "health": health,
            "model": inventory[0].model,
            "operation": "synthesize-speech",
            "output_format": "wav",
            "worker_live_enabled": False,
            "provider_requests": 0,
            "billable_generation_requests": 0,
            "provider_spend_usd": 0.0,
            "credential_read": False,
            "secret_returned": False,
            "durable_schema_columns_verified": sorted(required_columns),
        }
        if health.get("status") != "disabled":
            raise RuntimeError("stock-speech worker did not report disabled")
        if health.get("cycles") != 0 or health.get("errors") != 0:
            raise RuntimeError("disabled stock-speech worker changed counters")
        if health.get("custom_voice_enabled") or health.get("voice_clone_enabled"):
            raise RuntimeError("stock-speech worker exposed an unapproved voice mode")
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
