from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.audio_music_providers import (
    ProviderMusicFailure,
    ProviderMusicRequest,
    ProviderMusicResult,
)
from app.services.audio_music_runtime import AudioMusicClaim
from app.services.audio_music_worker import AudioMusicWorker, LoadedMusicExecution
from app.services.media_storage import LocalMediaObjectStore


class FakeAuthority:
    def __init__(self, claim: AudioMusicClaim | None = None) -> None:
        self.next_claim = claim
        self.claim_calls = 0
        self.submission_started = 0
        self.completed: list[dict] = []
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        return self.next_claim

    async def mark_submission_started(self, claim):
        self.submission_started += 1
        assert claim.execution_id == "music-exec-1"

    async def complete_bytes(self, claim, **kwargs):
        self.completed.append({"claim": claim, **kwargs})

    async def fail(
        self,
        claim,
        *,
        code: str,
        message: str,
        ambiguous_submission: bool = False,
    ):
        self.failed.append(
            {
                "claim": claim,
                "code": code,
                "message": message,
                "ambiguous_submission": ambiguous_submission,
            }
        )


class FakeAdapter:
    def __init__(
        self,
        *,
        failure: ProviderMusicFailure | None = None,
    ) -> None:
        self.failure = failure
        self.calls = 0

    async def invoke(self, request, *, credential: str, base_url: str):
        self.calls += 1
        assert request.model == "lyria-3-clip-preview"
        assert credential == "gemini-secret"
        assert base_url == "https://generativelanguage.googleapis.com"
        if self.failure is not None:
            raise self.failure
        return ProviderMusicResult(
            body=b"ID3" + b"music" * 128,
            content_type="audio/mpeg",
            request_id="req-music-1",
            metadata={
                "model": request.model,
                "tier": request.tier,
                "preview_model": True,
                "raw_returned_text_returned": False,
            },
            usage={
                "official_fixed_request_usd": 0.04,
                "provider_usage_reported": False,
            },
            actual_cost_usd=0.04,
        )


class StubMusicWorker(AudioMusicWorker):
    async def _load_execution(self, claim):
        assert claim.execution_id == "music-exec-1"
        return LoadedMusicExecution(
            request=ProviderMusicRequest(
                provider="gemini",
                model="lyria-3-clip-preview",
                operation="generate-music",
                tier="draft",
                prompt="Bright original instrumental music with a clean ending.",
                instrumental_only=True,
                lyrics="",
            ),
            credential="gemini-secret",
            base_url="https://generativelanguage.googleapis.com",
        )


@pytest.mark.asyncio
async def test_music_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "AUDIO_MUSIC_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(AudioMusicClaim("music-exec-1", "lease-1", 1))
    worker = StubMusicWorker(
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is False
    assert authority.claim_calls == 0
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "disabled"
    assert payload["live_enabled"] is False
    assert payload["cycles"] == 0
    assert payload["errors"] == 0
    assert payload["models"] == ["lyria-3-clip-preview", "lyria-3-pro-preview"]
    assert payload["default_tier"] == "draft"
    assert payload["draft_fixed_cost_usd"] == 0.04
    assert payload["final_fixed_cost_usd"] == 0.08
    assert payload["automatic_retry"] is False
    assert payload["full_song_requires_approval"] is True
    assert payload["preview_models"] is True
    assert payload["named_artist_imitation_enabled"] is False
    assert payload["voice_clone_enabled"] is False
    assert payload["dedicated_sfx_generation_enabled"] is False
    assert payload["raw_prompt_returned"] is False
    assert payload["raw_lyrics_returned"] is False
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_music_worker_completes_one_clip_request_at_fixed_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_MUSIC_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(AudioMusicClaim("music-exec-1", "lease-1", 1))
    adapter = FakeAdapter()
    worker = StubMusicWorker(
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"gemini": adapter},
    )
    assert await worker.run_once() is True
    assert authority.claim_calls == 1
    assert authority.submission_started == 1
    assert adapter.calls == 1
    assert authority.failed == []
    assert len(authority.completed) == 1
    completed = authority.completed[0]
    assert completed["actual_cost_usd"] == 0.04
    assert completed["cost_basis"] == "official_fixed_request"
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"
    assert payload["cycles"] == 1
    assert payload["errors"] == 0


@pytest.mark.asyncio
async def test_music_worker_marks_ambiguous_provider_failure_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_MUSIC_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(AudioMusicClaim("music-exec-1", "lease-1", 1))
    adapter = FakeAdapter(
        failure=ProviderMusicFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
        )
    )
    worker = StubMusicWorker(
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"gemini": adapter},
    )
    assert await worker.run_once() is True
    assert authority.submission_started == 1
    assert authority.completed == []
    assert len(authority.failed) == 1
    assert authority.failed[0]["ambiguous_submission"] is True
    assert "prompt" not in authority.failed[0]["message"].lower()
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "degraded"
    assert payload["errors"] == 1


def test_audio_music_worker_compose_is_fail_closed_nonroot_and_profiled() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-music-worker:")
        tail = source.index("\n  video-provider-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["audio-execution"]' in block
        assert "image: aionex-aios-backend:local" in block
        assert 'user: "1000:1000"' in block
        assert 'AUDIO_MUSIC_LIVE_ENABLED: "false"' in block
        assert 'cap_drop: ["ALL"]' in block
        assert "no-new-privileges:true" in block
        assert "app.services.audio_music_worker" in block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
