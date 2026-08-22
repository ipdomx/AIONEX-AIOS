from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.audio_speech_providers import (
    ProviderSpeechFailure,
    ProviderSpeechRequest,
    ProviderSpeechResult,
)
from app.services.audio_speech_runtime import AudioSpeechClaim
from app.services.audio_speech_worker import (
    AudioSpeechWorker,
    LoadedSpeechExecution,
)
from app.services.media_storage import LocalMediaObjectStore


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        writer.writeframes(b"\x00\x00" * 24_000)
    return output.getvalue()


class FakeAuthority:
    def __init__(self) -> None:
        self.claim_calls = 0
        self.marked: list[AudioSpeechClaim] = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        return AudioSpeechClaim("speech-exec-1", "lease-1", 1)

    async def mark_submission_started(self, claim):
        self.marked.append(claim)

    async def complete_bytes(self, claim, **kwargs):
        self.completed.append({"claim": claim, **kwargs})
        return {"status": "completed"}

    async def fail(
        self,
        claim,
        *,
        code: str,
        message: str,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
    ):
        self.failed.append(
            {
                "claim": claim,
                "code": code,
                "message": message,
                "safe_to_resubmit": safe_to_resubmit,
                "ambiguous_submission": ambiguous_submission,
            }
        )


class FakeAdapter:
    def __init__(
        self,
        authority: FakeAuthority,
        *,
        result: ProviderSpeechResult | None = None,
        failure: ProviderSpeechFailure | None = None,
        unexpected: Exception | None = None,
    ) -> None:
        self.authority = authority
        self.result = result
        self.failure = failure
        self.unexpected = unexpected
        self.calls = 0

    async def invoke(self, request, *, credential: str, base_url: str):
        self.calls += 1
        assert self.authority.marked, "submission marker must be durable before HTTP"
        assert request.model == "gpt-4o-mini-tts-2025-12-15"
        assert request.voice == "marin"
        assert credential == "credential"
        assert base_url == "https://api.openai.com"
        if self.failure is not None:
            raise self.failure
        if self.unexpected is not None:
            raise self.unexpected
        assert self.result is not None
        return self.result


class StubWorker(AudioSpeechWorker):
    def __init__(self, *, loaded: LoadedSpeechExecution, **kwargs) -> None:
        super().__init__(**kwargs)
        self.loaded = loaded

    async def _load_execution(self, claim):
        assert claim.execution_id == "speech-exec-1"
        return self.loaded


def loaded() -> LoadedSpeechExecution:
    return LoadedSpeechExecution(
        request=ProviderSpeechRequest(
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            operation="synthesize-speech",
            input_text="Welcome to AIONEX.",
            voice="marin",
            instructions="Speak clearly.",
            response_format="wav",
            max_duration_seconds=20.0,
        ),
        credential="credential",
        base_url="https://api.openai.com",
    )


@pytest.mark.asyncio
async def test_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_SPEECH_LIVE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "AUDIO_SPEECH_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is False
    assert authority.claim_calls == 0
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "disabled"
    assert payload["live_enabled"] is False
    assert payload["stock_voice_only"] is True
    assert payload["custom_voice_enabled"] is False
    assert payload["voice_clone_enabled"] is False
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_worker_marks_submission_then_completes_one_provider_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_SPEECH_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_SPEECH_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    adapter = FakeAdapter(
        authority,
        result=ProviderSpeechResult(
            body=wav_bytes(),
            content_type="audio/wav",
            request_id="req-stock-tts",
            metadata={"duration_seconds": 1.0},
            usage={
                "provider_usage_reported": False,
                "cost_basis": "official_rate_cap",
            },
            actual_cost_usd=None,
            cost_basis="official_rate_cap",
        ),
    )
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},
    )
    assert await worker.run_once() is True
    assert authority.claim_calls == 1
    assert len(authority.marked) == 1
    assert adapter.calls == 1
    assert len(authority.completed) == 1
    assert authority.completed[0]["provider_request_id"] == "req-stock-tts"
    assert authority.completed[0]["actual_cost_usd"] is None
    assert authority.completed[0]["cost_basis"] == "official_rate_cap"
    assert authority.failed == []
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"
    assert payload["cycles"] == 1 and payload["errors"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "safe_to_resubmit", "ambiguous"),
    [
        (
            ProviderSpeechFailure(
                "provider_rate_limited",
                retryable=True,
                safe_to_resubmit=True,
            ),
            True,
            False,
        ),
        (
            ProviderSpeechFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ),
            False,
            True,
        ),
        (
            ProviderSpeechFailure("provider_auth", retryable=False),
            False,
            False,
        ),
    ],
)
async def test_worker_preserves_definitive_retry_and_ambiguous_submission_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: ProviderSpeechFailure,
    safe_to_resubmit: bool,
    ambiguous: bool,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_SPEECH_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_SPEECH_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    adapter = FakeAdapter(authority, failure=failure)
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},
    )
    assert await worker.run_once() is True
    assert len(authority.marked) == 1
    assert authority.completed == []
    assert authority.failed[0]["code"] == failure.code
    assert authority.failed[0]["safe_to_resubmit"] is safe_to_resubmit
    assert authority.failed[0]["ambiguous_submission"] is ambiguous
    assert "credential" not in authority.failed[0]["message"]


@pytest.mark.asyncio
async def test_unexpected_failure_after_submission_is_ambiguous_and_never_auto_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_SPEECH_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_SPEECH_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    adapter = FakeAdapter(authority, unexpected=RuntimeError("unexpected"))
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},
    )
    assert await worker.run_once() is True
    assert authority.failed[0]["code"] == "audio_speech_worker_error"
    assert authority.failed[0]["safe_to_resubmit"] is False
    assert authority.failed[0]["ambiguous_submission"] is True


def test_audio_speech_worker_compose_is_fail_closed_nonroot_and_profile_gated() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-speech-worker:")
        tail = source.index("\n  video-provider-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["audio-execution"]' in block
        assert 'user: "1000:1000"' in block
        assert 'AUDIO_SPEECH_LIVE_ENABLED: "false"' in block
        assert 'cap_drop: ["ALL"]' in block
        assert 'no-new-privileges:true' in block
        assert 'app.services.audio_speech_worker' in block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
