from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.services.audio_music_providers import (
    ProviderMusicFailure,
    ProviderMusicPoll,
    ProviderMusicRequest,
    ProviderMusicResult,
    ProviderMusicSubmission,
)
from app.services.audio_music_runtime import AudioMusicClaim
from app.services.audio_music_worker import (
    AudioMusicWorker,
    LoadedMusicExecution,
    _read_private_secret,
)
from app.services.media_storage import LocalMediaObjectStore


REQUEST = ProviderMusicRequest(
    provider="replicate",
    model="google/lyria-3",
    operation="generate-music",
    tier="draft",
    prompt="Original bright instrumental music with a clear ending.",
    instrumental_only=True,
    lyrics="",
)
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x15" + b"music" * 512


class FakeAuthority:
    def __init__(self, claim: AudioMusicClaim | None = None) -> None:
        self.claim_value = claim
        self.claim_calls = 0
        self.submission_started: list[str] = []
        self.submitted: list[dict[str, Any]] = []
        self.poll_pending: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    async def claim(self) -> AudioMusicClaim | None:
        self.claim_calls += 1
        value = self.claim_value
        self.claim_value = None
        return value

    async def mark_submission_started(self, claim: AudioMusicClaim) -> None:
        self.submission_started.append(claim.execution_id)

    async def mark_submitted(
        self,
        claim: AudioMusicClaim,
        *,
        provider_request_id: str,
        provider_response_metadata: dict[str, Any],
    ) -> None:
        self.submitted.append(
            {
                "execution_id": claim.execution_id,
                "provider_request_id": provider_request_id,
                "metadata": provider_response_metadata,
            }
        )

    async def mark_poll_pending(
        self,
        claim: AudioMusicClaim,
        *,
        provider_response_metadata: dict[str, Any],
        delay_seconds: int,
        max_polls: int,
    ) -> int:
        self.poll_pending.append(
            {
                "execution_id": claim.execution_id,
                "metadata": provider_response_metadata,
                "delay_seconds": delay_seconds,
                "max_polls": max_polls,
            }
        )
        return len(self.poll_pending)

    async def complete_bytes(self, claim: AudioMusicClaim, **kwargs: Any) -> dict[str, Any]:
        self.completed.append({"execution_id": claim.execution_id, **kwargs})
        return {"status": "completed"}

    async def fail(
        self,
        claim: AudioMusicClaim,
        *,
        code: str,
        message: str,
        ambiguous_submission: bool = False,
    ) -> None:
        self.failed.append(
            {
                "execution_id": claim.execution_id,
                "code": code,
                "message": message,
                "ambiguous_submission": ambiguous_submission,
            }
        )


class FakeReplicateAdapter:
    def __init__(
        self,
        *,
        polls: list[ProviderMusicPoll] | None = None,
        submit_failure: ProviderMusicFailure | None = None,
        poll_failure: ProviderMusicFailure | None = None,
    ) -> None:
        self.polls = deque(polls or [])
        self.submit_failure = submit_failure
        self.poll_failure = poll_failure
        self.submit_calls = 0
        self.poll_calls = 0
        self.download_calls = 0
        self.prediction_ids: list[str] = []

    async def submit(self, request, *, credential: str, base_url: str):
        self.submit_calls += 1
        assert request == REQUEST
        assert credential == "replicate-token"
        assert base_url == "https://api.replicate.com"
        if self.submit_failure is not None:
            raise self.submit_failure
        return ProviderMusicSubmission(
            prediction_id="prediction-001",
            status="starting",
            output_url=None,
            metadata={
                "prediction_status": "starting",
                "raw_output_url_returned": False,
            },
        )

    async def poll(self, prediction_id: str, *, credential: str, base_url: str):
        self.poll_calls += 1
        self.prediction_ids.append(prediction_id)
        assert credential == "replicate-token"
        assert base_url == "https://api.replicate.com"
        if self.poll_failure is not None:
            raise self.poll_failure
        if not self.polls:
            raise AssertionError("unexpected poll")
        return self.polls.popleft()

    async def download(
        self,
        request,
        *,
        prediction_id: str,
        output_url: str,
    ) -> ProviderMusicResult:
        self.download_calls += 1
        assert request == REQUEST
        assert prediction_id == "prediction-001"
        assert output_url == "https://replicate.delivery/output.mp3"
        return ProviderMusicResult(
            body=MP3,
            content_type="audio/mpeg",
            request_id=prediction_id,
            metadata={
                "provider": "replicate",
                "model": request.model,
                "tier": request.tier,
                "nominal_duration_seconds": 30,
                "raw_output_url_returned": False,
            },
            usage={"official_fixed_request_usd": 0.04},
            actual_cost_usd=0.04,
        )


class StubMusicWorker(AudioMusicWorker):
    def __init__(self, *, loaded: LoadedMusicExecution, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.loaded = loaded

    async def _load_execution(self, claim: AudioMusicClaim) -> LoadedMusicExecution:
        assert claim.execution_id == "exec-1"
        return self.loaded


def loaded(state: str, prediction_id: str | None = None) -> LoadedMusicExecution:
    return LoadedMusicExecution(
        request=REQUEST,
        credential="replicate-token",
        base_url="https://api.replicate.com",
        provider_state=state,
        provider_request_id=prediction_id,
    )


@pytest.mark.asyncio
async def test_music_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", False)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-1", 1))
    worker = StubMusicWorker(
        loaded=loaded("not_started"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"replicate": FakeReplicateAdapter()},
        worker_id="music-disabled",
    )
    assert await worker.run_once() is False
    assert authority.claim_calls == 0
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "disabled"
    assert payload["live_enabled"] is False
    assert payload["durable_prediction_resume"] is True
    assert payload["provider_job_id_returned"] is False
    assert payload["provider_output_url_returned"] is False
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_replicate_submit_is_persisted_before_any_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-1", 1))
    adapter = FakeReplicateAdapter()
    worker = StubMusicWorker(
        loaded=loaded("not_started"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"replicate": adapter},
        worker_id="music-submit",
    )
    assert await worker.run_once() is True
    assert adapter.submit_calls == 1
    assert adapter.poll_calls == 0
    assert authority.submission_started == ["exec-1"]
    assert authority.submitted[0]["provider_request_id"] == "prediction-001"
    assert authority.completed == []


@pytest.mark.asyncio
async def test_replicate_recovery_polls_same_prediction_without_second_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIO_MUSIC_REPLICATE_POLL_SECONDS", 1)
    monkeypatch.setattr(settings, "AUDIO_MUSIC_REPLICATE_MAX_POLLS", 20)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    pending = ProviderMusicPoll(
        prediction_id="prediction-001",
        status="processing",
        output_url=None,
        metadata={
            "prediction_status": "processing",
            "raw_output_url_returned": False,
        },
    )
    succeeded = ProviderMusicPoll(
        prediction_id="prediction-001",
        status="succeeded",
        output_url="https://replicate.delivery/output.mp3",
        metadata={
            "prediction_status": "succeeded",
            "raw_output_url_returned": False,
        },
    )
    adapter = FakeReplicateAdapter(polls=[pending, succeeded])

    first_authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-2", 2))
    first_worker = StubMusicWorker(
        loaded=loaded("submitted", "prediction-001"),
        authority=first_authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects-a"),
        adapters={"replicate": adapter},
        worker_id="music-poll-a",
    )
    assert await first_worker.run_once() is True
    assert adapter.submit_calls == 0
    assert adapter.prediction_ids == ["prediction-001"]
    assert len(first_authority.poll_pending) == 1
    assert first_authority.completed == []

    second_authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-3", 3))
    second_worker = StubMusicWorker(
        loaded=loaded("submitted", "prediction-001"),
        authority=second_authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects-b"),
        adapters={"replicate": adapter},
        worker_id="music-poll-b",
    )
    assert await second_worker.run_once() is True
    assert adapter.submit_calls == 0
    assert adapter.prediction_ids == ["prediction-001", "prediction-001"]
    assert adapter.download_calls == 1
    assert second_authority.completed[0]["provider_request_id"] == "prediction-001"
    assert second_authority.completed[0]["actual_cost_usd"] == 0.04


@pytest.mark.asyncio
async def test_retryable_poll_error_requeues_same_job_not_new_prediction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIO_MUSIC_REPLICATE_POLL_SECONDS", 1)
    monkeypatch.setattr(settings, "AUDIO_MUSIC_REPLICATE_MAX_POLLS", 20)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    adapter = FakeReplicateAdapter(
        poll_failure=ProviderMusicFailure(
            "provider_poll_network", retryable=True, safe_to_resubmit=False
        )
    )
    authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-2", 2))
    worker = StubMusicWorker(
        loaded=loaded("submitted", "prediction-001"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"replicate": adapter},
        worker_id="music-poll-error",
    )
    assert await worker.run_once() is True
    assert adapter.submit_calls == 0
    assert len(authority.poll_pending) == 1
    assert authority.failed == []


@pytest.mark.asyncio
async def test_terminal_prediction_failure_never_submits_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    adapter = FakeReplicateAdapter(
        polls=[
            ProviderMusicPoll(
                prediction_id="prediction-001",
                status="aborted",
                output_url=None,
                metadata={"prediction_status": "aborted"},
            )
        ]
    )
    authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-2", 2))
    worker = StubMusicWorker(
        loaded=loaded("submitted", "prediction-001"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"replicate": adapter},
        worker_id="music-terminal",
    )
    assert await worker.run_once() is True
    assert adapter.submit_calls == 0
    assert authority.failed[0]["code"] == "provider_prediction_aborted"
    assert authority.failed[0]["ambiguous_submission"] is False


@pytest.mark.asyncio
async def test_ambiguous_submit_stops_without_automatic_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIO_MUSIC_LIVE_ENABLED", True)
    monkeypatch.setattr(
        settings, "AUDIO_MUSIC_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    adapter = FakeReplicateAdapter(
        submit_failure=ProviderMusicFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
        )
    )
    authority = FakeAuthority(AudioMusicClaim("exec-1", "lease-1", 1))
    worker = StubMusicWorker(
        loaded=loaded("not_started"),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"replicate": adapter},
        worker_id="music-ambiguous",
    )
    assert await worker.run_once() is True
    assert adapter.submit_calls == 1
    assert authority.failed[0]["ambiguous_submission"] is True
    assert authority.submitted == []
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "needs_review"


def test_audio_music_worker_compose_is_fail_closed_nonroot_and_profiled() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-music-worker:")
        end = source.index("\n  video-provider-worker:", start)
        block = source[start:end]
        assert 'profiles: ["audio-execution"]' in block
        assert 'user: "1000:1000"' in block
        assert 'AUDIO_MUSIC_LIVE_ENABLED: "false"' in block
        assert 'app.services.audio_music_worker' in block
        assert 'security_opt: ["no-new-privileges:true"]' in block
        assert 'cap_drop: ["ALL"]' in block
        assert "AUDIO_MUSIC_REPLICATE_TOKEN_FILE: /run/operator-secrets/replicate-api-token" in block
        assert "AUDIO_MUSIC_REPLICATE_BASE_URL: https://api.replicate.com" in block
        assert "AUDIO_MUSIC_REPLICATE_TOKEN_HOST_FILE" in block
        assert "/run/operator-secrets/replicate-api-token:ro" in block


def test_replicate_secret_file_is_private_regular_and_whitespace_free(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replicate-token"
    path.write_text("replicate-secret-token-1234567890\n", encoding="utf-8")
    path.chmod(0o600)
    assert _read_private_secret(str(path)) == "replicate-secret-token-1234567890"

    path.chmod(0o644)
    with pytest.raises(ProviderMusicFailure) as permissions:
        _read_private_secret(str(path))
    assert permissions.value.code == "provider_secret_permissions"

    path.chmod(0o600)
    path.write_text("token with whitespace", encoding="utf-8")
    with pytest.raises(ProviderMusicFailure) as whitespace:
        _read_private_secret(str(path))
    assert whitespace.value.code == "provider_unconfigured"
