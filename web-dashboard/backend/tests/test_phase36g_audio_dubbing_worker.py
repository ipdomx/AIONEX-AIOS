from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.audio_dubbing_providers import (
    ProviderDubbingTranslationFailure,
)
from app.services.audio_dubbing_runtime import AudioDubbingClaim
from app.services.audio_dubbing_worker import AudioDubbingWorker
from app.services.media_storage import LocalMediaObjectStore


class FakeAuthority:
    def __init__(self, claim: AudioDubbingClaim | None = None) -> None:
        self.next_claim = claim
        self.claim_calls = 0
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        return self.next_claim

    async def fail(
        self,
        claim,
        *,
        code: str,
        message: str,
        ambiguous: bool = False,
        safe_to_resubmit: bool = False,
    ):
        self.failed.append(
            {
                "claim": claim,
                "code": code,
                "message": message,
                "ambiguous": ambiguous,
                "safe_to_resubmit": safe_to_resubmit,
            }
        )


class StubDubbingWorker(AudioDubbingWorker):
    def __init__(
        self,
        *,
        translation_failure: ProviderDubbingTranslationFailure | None = None,
        advance_result: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.translation_failure = translation_failure
        self.advance_result = advance_result
        self.translation_calls = 0
        self.advance_calls = 0

    async def _translate_claim(self, claim):
        self.translation_calls += 1
        assert claim.execution_id == "dubbing-exec-1"
        if self.translation_failure is not None:
            raise self.translation_failure

    async def _advance_one(self) -> bool:
        self.advance_calls += 1
        return self.advance_result


@pytest.mark.asyncio
async def test_dubbing_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_DUBBING_LIVE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "AUDIO_DUBBING_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(AudioDubbingClaim("dubbing-exec-1", "lease-1", 1))
    worker = StubDubbingWorker(
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is False
    assert authority.claim_calls == 0
    assert worker.translation_calls == 0
    assert worker.advance_calls == 0
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "disabled"
    assert payload["live_enabled"] is False
    assert payload["cycles"] == 0
    assert payload["errors"] == 0
    assert payload["stock_voice_only"] is True
    assert payload["custom_voice_enabled"] is False
    assert payload["known_speaker_identification_enabled"] is False
    assert payload["voice_clone_enabled"] is False
    assert payload["voice_transformation_enabled"] is False
    assert payload["raw_translation_returned"] is False
    assert payload["raw_transcript_returned"] is False
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_dubbing_worker_processes_exactly_one_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_DUBBING_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_DUBBING_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    claim = AudioDubbingClaim("dubbing-exec-1", "lease-1", 1)
    authority = FakeAuthority(claim)
    worker = StubDubbingWorker(
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is True
    assert authority.claim_calls == 1
    assert worker.translation_calls == 1
    assert authority.failed == []
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"
    assert payload["cycles"] == 1
    assert payload["errors"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "health_status", "ambiguous", "safe"),
    [
        (
            ProviderDubbingTranslationFailure("provider_auth", retryable=False),
            "degraded",
            False,
            False,
        ),
        (
            ProviderDubbingTranslationFailure(
                "provider_rate_limited",
                retryable=True,
                safe_to_resubmit=True,
            ),
            "degraded",
            False,
            True,
        ),
        (
            ProviderDubbingTranslationFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ),
            "needs_review",
            True,
            False,
        ),
    ],
)
async def test_dubbing_worker_maps_provider_failure_without_raw_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: ProviderDubbingTranslationFailure,
    health_status: str,
    ambiguous: bool,
    safe: bool,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_DUBBING_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_DUBBING_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(AudioDubbingClaim("dubbing-exec-1", "lease-1", 1))
    worker = StubDubbingWorker(
        translation_failure=failure,
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is True
    assert len(authority.failed) == 1
    recorded = authority.failed[0]
    assert recorded["code"] == failure.code
    assert recorded["ambiguous"] is ambiguous
    assert recorded["safe_to_resubmit"] is safe
    assert "translation text" not in recorded["message"].lower()
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == health_status
    assert payload["errors"] == 1


@pytest.mark.asyncio
async def test_dubbing_worker_advances_orchestration_when_no_translation_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_DUBBING_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_DUBBING_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority(None)
    worker = StubDubbingWorker(
        advance_result=True,
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is True
    assert authority.claim_calls == 1
    assert worker.translation_calls == 0
    assert worker.advance_calls == 1
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"


def test_audio_dubbing_worker_compose_is_fail_closed_nonroot_and_profiled() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-dubbing-worker:")
        tail = source.index("\n  video-provider-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["audio-execution"]' in block
        assert "image: aionex-aios-backend:local" in block
        assert 'user: "1000:1000"' in block
        assert 'AUDIO_DUBBING_LIVE_ENABLED: "false"' in block
        assert 'cap_drop: ["ALL"]' in block
        assert "no-new-privileges:true" in block
        assert "app.services.audio_dubbing_worker" in block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
