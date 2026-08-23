from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import app.db.models  # noqa: F401
from aios.music_factory import (
    LOW_COST_MUSIC_POLICY,
    MusicRequest,
    MusicRightsEvidence,
    build_music_plan,
)
from app.core.config import settings
from app.db.base import Base
from app.services.audio_music_worker import AudioMusicWorker
from app.services.media_storage import LocalMediaObjectStore


class NoClaimAuthority:
    claim_calls = 0

    async def claim(self):
        self.claim_calls += 1
        raise AssertionError("disabled music worker must not call claim")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="phase36g-music-smoke-") as root:
        root_path = Path(root)
        settings.AUDIO_MUSIC_LIVE_ENABLED = False
        settings.AUDIO_MUSIC_WORKER_HEALTH_FILE = str(root_path / "health.json")
        authority = NoClaimAuthority()
        worker = AudioMusicWorker(
            authority=authority,  # type: ignore[arg-type]
            store=LocalMediaObjectStore(root_path / "objects"),
            adapters={},
            worker_id="phase36g-music-offline-smoke",
        )
        worked = await worker.run_once()
        health = json.loads((root_path / "health.json").read_text(encoding="utf-8"))
        columns = set(Base.metadata.tables["audio_music_executions"].c.keys())
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
            "tier",
            "plan_checksum",
            "runtime_evidence_sha256",
            "pricing_evidence_sha256",
            "prompt_sha256",
            "lyrics_sha256",
            "rights_basis",
            "rights_evidence_sha256",
            "final_generation_approved",
            "final_approval_evidence_sha256",
            "prior_draft_checksum",
            "estimated_cost_usd",
            "max_cost_usd",
            "actual_cost_usd",
            "output_storage_key",
            "output_checksum",
            "returned_text_sha256",
            "synthid_disclosure_required",
        }
        rights = MusicRightsEvidence(
            basis="instrumental",
            evidence_sha256=None,
            commercial_use_authorized=True,
            user_accepts_provider_terms=True,
        )
        plan = build_music_plan(
            MusicRequest(
                title="Stage 7 cheapest governed draft",
                prompt="Bright original instrumental music with a clear intro and clean ending.",
                language="en",
                rights=rights,
            )
        )
        assert worked is False
        assert authority.claim_calls == 0
        assert health["status"] == "disabled"
        assert health["live_enabled"] is False
        assert health["cycles"] == 0
        assert health["errors"] == 0
        assert health["models"] == [
            "lyria-3-clip-preview",
            "lyria-3-pro-preview",
        ]
        assert health["default_tier"] == "draft"
        assert health["draft_fixed_cost_usd"] == 0.04
        assert health["final_fixed_cost_usd"] == 0.08
        assert health["max_attempts"] == 1
        assert health["automatic_retry"] is False
        assert health["full_song_requires_approval"] is True
        assert health["named_artist_imitation_enabled"] is False
        assert health["voice_clone_enabled"] is False
        assert health["voice_transformation_enabled"] is False
        assert health["dedicated_sfx_generation_enabled"] is False
        assert health["raw_prompt_returned"] is False
        assert health["raw_lyrics_returned"] is False
        assert health["raw_provider_text_returned"] is False
        assert health["secret_returned"] is False
        assert required <= columns
        assert plan.route.model == "lyria-3-clip-preview"
        assert plan.max_cost_usd == 0.04
        assert LOW_COST_MUSIC_POLICY.automatic_retry is False
        print(
            json.dumps(
                {
                    "schema": "36G.stage7.audio-music-worker-offline.v1",
                    "status": "pass",
                    "worker_health": health,
                    "default_model": plan.route.model,
                    "final_model": "lyria-3-pro-preview",
                    "default_user_cap_usd": 0.04,
                    "final_user_cap_usd": 0.08,
                    "required_schema_columns": sorted(required),
                    "music_generation_requests": 0,
                    "provider_spend_usd": 0.0,
                    "credential_read": False,
                    "raw_prompt_returned": False,
                    "raw_lyrics_returned": False,
                    "secret_returned": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
