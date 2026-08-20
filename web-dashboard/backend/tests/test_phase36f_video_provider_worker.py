from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.media_storage import LocalMediaObjectStore
from app.services.video_provider_worker import LoadedVideoExecution, VideoProviderWorker
from app.services.video_providers import (
    ProviderVideoContent,
    ProviderVideoFailure,
    ProviderVideoJob,
    ProviderVideoRequest,
)
from app.services.video_runtime import VideoClaim


class FakeAuthority:
    def __init__(self, claim: VideoClaim | None) -> None:
        self.claim_value = claim
        self.claim_calls = 0
        self.marked: list[VideoClaim] = []
        self.jobs: list[dict] = []
        self.job_failures: list[dict] = []
        self.pending: list[dict] = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        value, self.claim_value = self.claim_value, None
        return value

    async def mark_submission_started(self, claim):
        self.marked.append(claim)

    async def record_provider_job(self, claim, **kwargs):
        self.jobs.append({"claim": claim, **kwargs})

    async def record_provider_job_failure(self, claim, **kwargs):
        self.job_failures.append({"claim": claim, **kwargs})

    async def record_poll_pending(self, claim, **kwargs):
        self.pending.append({"claim": claim, **kwargs})

    async def complete_bytes(self, claim, **kwargs):
        self.completed.append({"claim": claim, **kwargs})
        return {"status": "completed"}

    async def fail(self, claim, **kwargs):
        self.failed.append({"claim": claim, **kwargs})


class FakeAdapter:
    def __init__(self) -> None:
        self.submit_result: ProviderVideoJob | None = None
        self.submit_failure: ProviderVideoFailure | None = None
        self.reconcile_result: ProviderVideoJob | None = None
        self.reconcile_failure: ProviderVideoFailure | None = None
        self.retrieve_result: ProviderVideoJob | None = None
        self.retrieve_failure: ProviderVideoFailure | None = None
        self.content = ProviderVideoContent(body=b"fake-mp4", content_type="video/mp4")
        self.submit_calls = 0
        self.reconcile_calls = 0
        self.retrieve_calls = 0
        self.download_calls = 0

    async def submit(self, request, *, credential: str, base_url: str):
        self.submit_calls += 1
        assert credential == "credential"
        assert base_url == "https://api.openai.com"
        if self.submit_failure:
            raise self.submit_failure
        assert self.submit_result is not None
        return self.submit_result

    async def reconcile(self, request, *, submitted_at, credential: str, base_url: str):
        self.reconcile_calls += 1
        assert submitted_at.tzinfo is not None
        if self.reconcile_failure:
            raise self.reconcile_failure
        assert self.reconcile_result is not None
        return self.reconcile_result

    async def retrieve(self, job_id: str, *, credential: str, base_url: str):
        self.retrieve_calls += 1
        if self.retrieve_failure:
            raise self.retrieve_failure
        assert self.retrieve_result is not None
        assert self.retrieve_result.job_id == job_id
        return self.retrieve_result

    async def download_content(self, job_id: str, *, credential: str, base_url: str):
        self.download_calls += 1
        return self.content


class FakeFFmpeg:
    def preflight(self):
        return {"version": "9.0", "engine": "ffmpeg"}

    def probe(self, path: Path):
        assert path.is_file() and path.read_bytes() == b"fake-mp4"
        return {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "4.000"},
        }


class StubWorker(VideoProviderWorker):
    def __init__(self, *, loaded: LoadedVideoExecution, **kwargs) -> None:
        super().__init__(**kwargs)
        self.loaded = loaded

    async def _load_execution(self, claim):
        return self.loaded


def request(model: str = "sora-2") -> ProviderVideoRequest:
    return ProviderVideoRequest(
        provider="openai",
        model=model,
        operation="text-to-video",
        prompt="A governed cinematic scene with continuity and truthful product staging.",
        seconds=4,
        size="1280x720",
    )


def loaded(model: str = "sora-2") -> LoadedVideoExecution:
    return LoadedVideoExecution(
        request=request(model),
        credential="credential",
        base_url="https://api.openai.com",
        submitted_at=datetime.now(UTC),
    )


def job(
    state: str = "queued", job_id: str = "video-job-1", progress: int | None = 0
) -> ProviderVideoJob:
    return ProviderVideoJob(
        job_id=job_id,
        state=state,
        progress=progress,
        created_at=int(datetime.now(UTC).timestamp()),
        model="sora-2",
        seconds=4,
        size="1280x720",
        prompt=request().prompt,
        metadata={"status": state},
    )


def worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: FakeAuthority,
    adapter: FakeAdapter,
    loaded_value: LoadedVideoExecution | None = None,
) -> StubWorker:
    monkeypatch.setattr(
        settings, "VIDEO_EXECUTION_WORKER_HEALTH_FILE", str(tmp_path / "health.json")
    )
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_TEMP_ROOT", str(tmp_path / "temp"))
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_POLL_SECONDS", 1)
    return StubWorker(
        loaded=loaded_value or loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapter=adapter,
        ffmpeg=FakeFFmpeg(),  # type: ignore[arg-type]
        worker_id="video-worker-test",
    )


@pytest.mark.asyncio
async def test_worker_is_fail_closed_when_live_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", False)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-1", 1, "submit", None))
    adapter = FakeAdapter()
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is False
    assert authority.claim_calls == 0
    assert adapter.submit_calls == 0
    health = json.loads((tmp_path / "health.json").read_text())
    assert health["status"] == "disabled" and health["live_enabled"] is False
    assert health["secret_returned"] is False


@pytest.mark.asyncio
async def test_submit_marks_durable_boundary_before_provider_and_records_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    claim = VideoClaim("exec-1", "lease-1", 1, "submit", None)
    authority = FakeAuthority(claim)
    adapter = FakeAdapter()
    adapter.submit_result = job()
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert authority.marked == [claim]
    assert adapter.submit_calls == 1
    assert authority.jobs[0]["provider_job_id"] == "video-job-1"
    assert authority.jobs[0]["provider_state"] == "queued"
    assert authority.failed == []


@pytest.mark.asyncio
async def test_completed_submit_records_job_identity_without_download_until_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    claim = VideoClaim("exec-1", "lease-1", 1, "submit", None)
    authority = FakeAuthority(claim)
    adapter = FakeAdapter()
    adapter.submit_result = job("completed", progress=100)
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert authority.jobs[0]["provider_state"] == "completed"
    assert adapter.download_calls == 0
    assert authority.completed == []


@pytest.mark.asyncio
async def test_ambiguous_submit_never_opens_safe_resubmit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-1", 1, "submit", None))
    adapter = FakeAdapter()
    adapter.submit_failure = ProviderVideoFailure(
        "provider_submission_ambiguous", retryable=False, ambiguous_submission=True
    )
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    failure = authority.failed[0]
    assert failure["permanent"] is False
    assert failure.get("submission_safe_to_retry") in {None, False}
    assert "credential" not in failure["message"]


@pytest.mark.asyncio
async def test_explicit_rate_rejection_is_the_only_worker_safe_resubmit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-1", 1, "submit", None))
    adapter = FakeAdapter()
    adapter.submit_failure = ProviderVideoFailure(
        "provider_rate_limited", retryable=True, safe_to_resubmit=True
    )
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert authority.failed[0]["submission_safe_to_retry"] is True
    assert authority.failed[0]["permanent"] is False


@pytest.mark.asyncio
async def test_reconcile_adopts_existing_job_and_never_calls_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-2", 2, "reconcile", None))
    adapter = FakeAdapter()
    adapter.reconcile_result = job("in_progress", progress=37)
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert adapter.reconcile_calls == 1 and adapter.submit_calls == 0
    assert authority.jobs[0]["provider_job_id"] == "video-job-1"
    assert authority.jobs[0]["provider_state"] == "in_progress"


@pytest.mark.asyncio
async def test_poll_pending_requeues_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-3", 3, "poll", "video-job-1"))
    adapter = FakeAdapter()
    adapter.retrieve_result = job("in_progress", progress=55)
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert authority.pending[0]["provider_state"] == "in_progress"
    assert authority.pending[0]["progress"] == 55
    assert adapter.download_calls == 0 and authority.completed == []


@pytest.mark.asyncio
async def test_poll_completed_downloads_qa_and_records_official_fixed_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-4", 4, "poll", "video-job-1"))
    adapter = FakeAdapter()
    adapter.retrieve_result = job("completed", progress=100)
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert adapter.download_calls == 1
    completed = authority.completed[0]
    assert completed["actual_cost_usd"] == pytest.approx(0.4)
    assert completed["cost_basis"] == "official_fixed_second"
    assert completed["provider_response_metadata"]["qa"] == {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration_seconds": 4.0,
        "width": 1280,
        "height": 720,
        "video_codec": "h264",
        "audio_present": True,
    }
    assert (
        completed["provider_response_metadata"]["pricing"]["price_per_second_usd"]
        == 0.10
    )


@pytest.mark.asyncio
async def test_failed_terminal_job_records_identity_and_sanitized_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VIDEO_EXECUTION_LIVE_ENABLED", True)
    authority = FakeAuthority(VideoClaim("exec-1", "lease-4", 4, "poll", "video-job-1"))
    adapter = FakeAdapter()
    adapter.retrieve_result = ProviderVideoJob(
        job_id="video-job-1",
        state="failed",
        progress=None,
        created_at=int(datetime.now(UTC).timestamp()),
        model="sora-2",
        seconds=4,
        size="1280x720",
        prompt=request().prompt,
        metadata={"status": "failed", "error_code": "content_policy"},
    )
    value = worker(tmp_path, monkeypatch, authority, adapter)
    assert await value.run_once() is True
    assert authority.job_failures[0]["provider_job_id"] == "video-job-1"
    assert authority.job_failures[0]["code"] == "content_policy"
    assert authority.completed == []


def test_video_provider_worker_compose_is_live_disabled_nonroot_and_ffmpeg_backed() -> (
    None
):
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  video-provider-worker:")
        tail = source.index("\n  design-image-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["video-execution"]' in block
        assert "image: aionex-aios-video-provider-worker:local" in block
        assert "target: media-worker" in block
        assert 'user: "1000:1000"' in block
        assert 'VIDEO_EXECUTION_LIVE_ENABLED: "false"' in block
        assert "MEDIA_FFMPEG_BINARY: /opt/ffmpeg/bin/ffmpeg" in block
        assert "MEDIA_FFPROBE_BINARY: /opt/ffmpeg/bin/ffprobe" in block
        assert "app.services.video_provider_worker" in block
        assert 'cap_drop: ["ALL"]' in block
        assert "no-new-privileges:true" in block
