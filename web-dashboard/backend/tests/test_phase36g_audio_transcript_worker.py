from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.audio_transcript_providers import (
    ProviderDiarizedSegmentResult,
    ProviderTranscriptFailure,
    ProviderTranscriptRequest,
    ProviderTranscriptResult,
)
from app.services.audio_transcript_runtime import AudioTranscriptClaim
from app.services.audio_transcript_worker import (
    AudioTranscriptWorker,
    LoadedTranscriptExecution,
)
from app.services.media_storage import LocalMediaObjectStore


class FakeAuthority:
    def __init__(self) -> None:
        self.claim_calls = 0
        self.marked: list[AudioTranscriptClaim] = []
        self.completed: list[dict] = []
        self.diarized: list[dict] = []
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        return AudioTranscriptClaim("exec-1", "lease-1", 1)

    async def mark_submission_started(self, claim):
        self.marked.append(claim)

    async def complete_text(self, claim, **kwargs):
        self.completed.append({"claim": claim, **kwargs})
        return {"status": "completed"}

    async def complete_diarization(self, claim, **kwargs):
        self.diarized.append({"claim": claim, **kwargs})
        return {"status": "completed"}

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


class FakeAdapter:
    def __init__(
        self,
        result: ProviderTranscriptResult | None = None,
        failure: ProviderTranscriptFailure | None = None,
    ) -> None:
        self.result = result
        self.failure = failure
        self.calls = 0

    async def invoke(self, request, *, credential: str, base_url: str):
        self.calls += 1
        assert credential == "credential"
        assert base_url == "https://api.openai.com"
        assert request.model in {
            "gpt-4o-mini-transcribe-2025-12-15",
            "gpt-4o-transcribe-diarize",
        }
        if self.failure is not None:
            raise self.failure
        assert self.result is not None
        return self.result


class StubWorker(AudioTranscriptWorker):
    def __init__(self, *, loaded: LoadedTranscriptExecution, **kwargs) -> None:
        super().__init__(**kwargs)
        self.loaded = loaded

    async def _load_execution(self, claim):
        assert claim.execution_id == "exec-1"
        return self.loaded


def loaded(*, operation: str = "transcribe") -> LoadedTranscriptExecution:
    diarize = operation == "diarize"
    return LoadedTranscriptExecution(
        request=ProviderTranscriptRequest(
            provider="openai",
            model=(
                "gpt-4o-transcribe-diarize"
                if diarize
                else "gpt-4o-mini-transcribe-2025-12-15"
            ),
            audio=b"RIFF" + b"\x00" * 128,
            media_type="audio/wav",
            source_sha256="a" * 64,
            duration_ms=5_000,
            language="en-US",
            operation=operation,
            response_format="diarized_json" if diarize else "json",
            chunking_strategy="auto" if diarize else None,
        ),
        credential="credential",
        base_url="https://api.openai.com",
    )


@pytest.mark.asyncio
async def test_transcript_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_TRANSCRIPT_LIVE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE",
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
    assert payload["cycles"] == 0
    assert payload["errors"] == 0
    assert payload["raw_transcript_returned"] is False
    assert payload["raw_speaker_labels_returned"] is False
    assert payload["known_speaker_references_enabled"] is False
    assert payload["operations"] == ["diarize", "transcribe"]
    assert payload["diarization_model"] == "gpt-4o-transcribe-diarize"
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_transcript_worker_completes_one_fake_provider_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_TRANSCRIPT_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    adapter = FakeAdapter(
        ProviderTranscriptResult(
            text="Governed private transcript.",
            language="en-US",
            request_id="req-1",
            metadata={"duration_ms": 5_000},
            usage={"estimated_cost_usd": 0.00025},
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )
    )
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},  # type: ignore[dict-item]
    )
    assert await worker.run_once() is True
    assert authority.claim_calls == 1
    assert authority.marked == [AudioTranscriptClaim("exec-1", "lease-1", 1)]
    assert adapter.calls == 1
    assert authority.failed == []
    assert len(authority.completed) == 1
    assert authority.completed[0]["text"] == "Governed private transcript."
    assert authority.completed[0]["provider_request_id"] == "req-1"
    assert authority.completed[0]["actual_cost_usd"] is None
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"
    assert payload["cycles"] == 1
    assert payload["errors"] == 0


@pytest.mark.asyncio
async def test_transcript_worker_completes_one_fake_diarization_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_TRANSCRIPT_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    segments = (
        ProviderDiarizedSegmentResult(
            provider_segment_id="seg-a",
            speaker_label="provider-alpha",
            start_seconds=0.0,
            end_seconds=2.0,
            text="First speaker.",
        ),
        ProviderDiarizedSegmentResult(
            provider_segment_id="seg-b",
            speaker_label="provider-beta",
            start_seconds=2.0,
            end_seconds=5.0,
            text="Second speaker.",
        ),
    )
    adapter = FakeAdapter(
        ProviderTranscriptResult(
            text="First speaker. Second speaker.",
            language="en-US",
            request_id="req-diarize-1",
            metadata={
                "operation": "diarize",
                "segment_count": 2,
                "speaker_count": 2,
                "raw_speaker_labels_returned": False,
            },
            usage={
                "estimated_cost_usd": 0.0005,
                "actual_cost_known": False,
            },
            segments=segments,
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )
    )
    worker = StubWorker(
        loaded=loaded(operation="diarize"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},  # type: ignore[dict-item]
    )
    assert await worker.run_once() is True
    assert authority.marked == [AudioTranscriptClaim("exec-1", "lease-1", 1)]
    assert authority.completed == []
    assert len(authority.diarized) == 1
    assert authority.diarized[0]["segments"] == segments
    assert authority.diarized[0]["provider_request_id"] == "req-diarize-1"
    assert authority.failed == []
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "healthy"
    assert payload["cycles"] == 1 and payload["errors"] == 0
    assert payload["raw_speaker_labels_returned"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status", "ambiguous", "safe"),
    [
        (
            ProviderTranscriptFailure("provider_auth", retryable=False),
            "degraded",
            False,
            False,
        ),
        (
            ProviderTranscriptFailure(
                "provider_rate_limited",
                retryable=True,
                safe_to_resubmit=True,
            ),
            "degraded",
            False,
            True,
        ),
        (
            ProviderTranscriptFailure(
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
async def test_transcript_worker_maps_failure_boundary_without_raw_provider_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: ProviderTranscriptFailure,
    status: str,
    ambiguous: bool,
    safe: bool,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_TRANSCRIPT_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE",
        str(tmp_path / "health.json"),
    )
    authority = FakeAuthority()
    adapter = FakeAdapter(failure=failure)
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},  # type: ignore[dict-item]
    )
    assert await worker.run_once() is True
    assert authority.completed == []
    assert authority.diarized == []
    assert authority.failed[0]["code"] == failure.code
    assert authority.failed[0]["ambiguous"] is ambiguous
    assert authority.failed[0]["safe_to_resubmit"] is safe
    assert "credential" not in authority.failed[0]["message"]
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == status
    assert payload["errors"] == 1


def test_audio_transcript_worker_compose_is_governed_live_nonroot_and_profiled() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-transcript-worker:")
        tail = source.index("\n  video-provider-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["audio-execution"]' in block
        assert "image: aionex-aios-backend:local" in block
        assert 'user: "1000:1000"' in block
        assert 'AUDIO_TRANSCRIPT_LIVE_ENABLED: "true"' in block
        assert 'cap_drop: ["ALL"]' in block
        assert "no-new-privileges:true" in block
        assert "app.services.audio_transcript_worker" in block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
