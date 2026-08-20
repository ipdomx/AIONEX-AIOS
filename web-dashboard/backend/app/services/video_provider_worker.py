"""Phase 36F live-disabled durable video provider worker.

Stage 2B accepts the exact OpenAI Sora text-to-video route only. Provider-visible
model inventory, reference operations and Gemini/Veo planning entries are not
claimable live paths until separately accepted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AIProvider, MediaAssetNode, VideoExecution
from app.services.ai_runtime_service import (
    provider_credential,
    provider_enabled,
    validate_provider_base_url,
)
from app.services.media_ffmpeg import FFmpegRuntime, MediaFFmpegError
from app.services.media_storage import MediaObjectStore, media_object_store
from app.services.video_providers import (
    OpenAIVideoAdapter,
    ProviderVideoFailure,
    ProviderVideoJob,
    ProviderVideoRequest,
    openai_sora_fixed_cost,
)
from app.services.video_runtime import VideoClaim, VideoExecutionAuthority

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedVideoExecution:
    request: ProviderVideoRequest
    credential: str
    base_url: str
    submitted_at: datetime | None


def _now() -> datetime:
    return datetime.now(UTC)


def _expected_dimensions(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = size.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (ValueError, AttributeError):
        raise ProviderVideoFailure("provider_video_size_invalid", retryable=False) from None
    if (width, height) not in {(1280, 720), (720, 1280)}:
        raise ProviderVideoFailure("provider_video_size_invalid", retryable=False)
    return width, height


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _qa_provider_video(probe: dict[str, Any], request: ProviderVideoRequest) -> dict[str, Any]:
    streams = probe.get("streams")
    fmt = probe.get("format")
    if not isinstance(streams, list) or not isinstance(fmt, dict):
        raise ProviderVideoFailure("provider_video_probe_invalid", retryable=False)
    videos = [row for row in streams if isinstance(row, dict) and row.get("codec_type") == "video"]
    if not videos:
        raise ProviderVideoFailure("provider_video_stream_missing", retryable=False)
    video = videos[0]
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    expected_width, expected_height = _expected_dimensions(request.size)
    if (width, height) != (expected_width, expected_height):
        raise ProviderVideoFailure("provider_video_dimensions", retryable=False)
    format_name = str(fmt.get("format_name") or "").lower()
    if "mp4" not in format_name and "mov" not in format_name:
        raise ProviderVideoFailure("provider_video_container", retryable=False)
    duration = _float_value(fmt.get("duration"))
    if duration is None:
        duration = _float_value(video.get("duration"))
    if duration is None or duration <= 0:
        raise ProviderVideoFailure("provider_video_duration", retryable=False)
    tolerance = max(1.0, min(2.0, float(request.seconds) * 0.25))
    if abs(duration - float(request.seconds)) > tolerance:
        raise ProviderVideoFailure("provider_video_duration", retryable=False)
    audio_present = any(
        isinstance(row, dict) and row.get("codec_type") == "audio" for row in streams
    )
    return {
        "format_name": format_name[:120],
        "duration_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "video_codec": str(video.get("codec_name") or "")[:80],
        "audio_present": audio_present,
    }


class VideoProviderWorker:
    def __init__(
        self,
        *,
        authority: VideoExecutionAuthority | None = None,
        store: MediaObjectStore | None = None,
        adapter: OpenAIVideoAdapter | None = None,
        ffmpeg: FFmpegRuntime | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.VIDEO_EXECUTION_WORKER_ID).strip()
        self.worker_id = configured or f"video-provider:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.authority = authority or VideoExecutionAuthority(
            store=self.store,
            worker_id=self.worker_id,
            lease_seconds=int(settings.VIDEO_EXECUTION_LEASE_SECONDS),
        )
        self.adapter = adapter or OpenAIVideoAdapter(
            timeout_seconds=float(settings.VIDEO_EXECUTION_PROVIDER_TIMEOUT_SECONDS),
            download_timeout_seconds=float(settings.VIDEO_EXECUTION_DOWNLOAD_TIMEOUT_SECONDS),
            max_content_bytes=int(settings.VIDEO_EXECUTION_MAX_PROVIDER_BYTES),
            reconcile_window_seconds=int(settings.VIDEO_EXECUTION_RECONCILE_WINDOW_SECONDS),
        )
        self.ffmpeg = ffmpeg or FFmpegRuntime(
            timeout_seconds=int(settings.VIDEO_EXECUTION_FFPROBE_TIMEOUT_SECONDS)
        )
        self.health_path = Path(settings.VIDEO_EXECUTION_WORKER_HEALTH_FILE)
        self.temp_root = Path(settings.VIDEO_EXECUTION_TEMP_ROOT)
        self.cycles = 0
        self.errors = 0
        self._ffmpeg_version: str | None = None

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": bool(settings.VIDEO_EXECUTION_LIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "provider": "openai",
            "ffmpeg_version": self._ffmpeg_version,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> dict[str, Any]:
        await asyncio.to_thread(self.store.preflight)
        async with SessionLocal() as session:
            await session.execute(select(VideoExecution.id).limit(1))
        self.temp_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.temp_root, 0o700)
        evidence = await asyncio.to_thread(self.ffmpeg.preflight)
        self._ffmpeg_version = str(evidence.get("version") or "") or None
        return evidence

    async def _load_execution(self, claim: VideoClaim) -> LoadedVideoExecution:
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, claim.execution_id)
            if row is None or row.status != "running":
                raise ProviderVideoFailure("execution_unavailable", retryable=False)
            target = await session.get(MediaAssetNode, row.target_node_id)
            if (
                target is None
                or target.graph_id != row.graph_id
                or target.organization_id != row.organization_id
                or target.status != "planned"
            ):
                raise ProviderVideoFailure("execution_scope", retryable=False)
            private = (target.prompt_metadata or {}).get("video_execution")
            if not isinstance(private, dict):
                raise ProviderVideoFailure("execution_prompt", retryable=False)
            prompt = str(private.get("compiled_prompt") or "").strip()
            if not prompt:
                raise ProviderVideoFailure("execution_prompt", retryable=False)
            if row.provider != "openai" or row.model not in {"sora-2", "sora-2-pro"}:
                raise ProviderVideoFailure("provider_adapter_unavailable", retryable=False)
            if row.operation != "text-to-video":
                raise ProviderVideoFailure("provider_operation_unsupported", retryable=False)
            options = dict(row.request_options or {})
            if int(options.get("reference_count") or 0) != 0:
                raise ProviderVideoFailure("provider_input_unsupported", retryable=False)
            seconds = int(options.get("seconds") or 0)
            size = str(options.get("size") or "").strip()
            request = ProviderVideoRequest(
                provider=row.provider,
                model=row.model,
                operation=row.operation,
                prompt=prompt,
                seconds=seconds,
                size=size,
                reference=None,
                options=options,
            )
            # Cost table is a launch-boundary check too; fail before provider HTTP if unknown.
            openai_sora_fixed_cost(request)
            providers = list(
                (
                    await session.scalars(
                        select(AIProvider)
                        .where(
                            AIProvider.organization_id
                            == settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
                            AIProvider.type == row.provider,
                            AIProvider.status == "connected",
                        )
                        .order_by(AIProvider.id)
                    )
                ).all()
            )
            if len(providers) != 1 or not provider_enabled(providers[0]):
                raise ProviderVideoFailure("provider_authority", retryable=False)
            provider = providers[0]
            credential = provider_credential(provider)
            base_url = validate_provider_base_url(provider.type, provider.base_url)
            if not credential or not base_url:
                raise ProviderVideoFailure("provider_unconfigured", retryable=False)
            submitted_at = row.provider_submitted_at
        return LoadedVideoExecution(
            request=request,
            credential=credential,
            base_url=base_url,
            submitted_at=submitted_at,
        )

    async def _record_job_or_terminal_failure(
        self,
        claim: VideoClaim,
        job: ProviderVideoJob,
    ) -> None:
        if job.state == "failed":
            await self.authority.record_provider_job_failure(
                claim,
                provider_job_id=job.job_id,
                code=str(job.metadata.get("error_code") or "provider_job_failed"),
                message="Video provider job failed",
                provider_response_metadata=job.metadata,
            )
            return
        await self.authority.record_provider_job(
            claim,
            provider_job_id=job.job_id,
            provider_state=job.state,
            progress=job.progress,
            provider_response_metadata=job.metadata,
            poll_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
        )

    async def _submit(self, claim: VideoClaim, loaded: LoadedVideoExecution) -> None:
        await self.authority.mark_submission_started(claim)
        try:
            job = await self.adapter.submit(
                loaded.request,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
        except ProviderVideoFailure as exc:
            if exc.ambiguous_submission:
                await self.authority.fail(
                    claim,
                    code=exc.code,
                    message="Video provider submission outcome is ambiguous; reconcile before any resubmit",
                    permanent=False,
                    retry_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
                )
                return
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Video provider submission was rejected",
                permanent=not exc.retryable,
                retry_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
                submission_safe_to_retry=exc.safe_to_resubmit,
            )
            return
        await self._record_job_or_terminal_failure(claim, job)

    async def _reconcile(self, claim: VideoClaim, loaded: LoadedVideoExecution) -> None:
        if loaded.submitted_at is None:
            await self.authority.fail(
                claim,
                code="provider_reconcile_timestamp_missing",
                message="Video submission reconciliation timestamp is missing",
                permanent=True,
            )
            return
        try:
            job = await self.adapter.reconcile(
                loaded.request,
                submitted_at=loaded.submitted_at,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
        except ProviderVideoFailure as exc:
            # Reconciliation must never cause a blind second paid submission.
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Video submission could not be reconciled uniquely",
                permanent=True,
            )
            return
        await self._record_job_or_terminal_failure(claim, job)

    async def _qa_content(
        self, body: bytes, request: ProviderVideoRequest
    ) -> dict[str, Any]:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.temp_root, 0o700)
        with tempfile.NamedTemporaryFile(
            dir=self.temp_root,
            prefix="p36f-provider-",
            suffix=".mp4",
            delete=False,
        ) as handle:
            handle.write(body)
            path = Path(handle.name)
        try:
            probe = await asyncio.to_thread(self.ffmpeg.probe, path)
            return _qa_provider_video(probe, request)
        except MediaFFmpegError as exc:
            raise ProviderVideoFailure("provider_video_probe", retryable=False) from exc
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("video provider temporary file cleanup failed")

    async def _poll(self, claim: VideoClaim, loaded: LoadedVideoExecution) -> None:
        job_id = claim.provider_job_id
        if not job_id:
            await self.authority.fail(
                claim,
                code="provider_job_missing",
                message="Video provider polling claim has no durable job identity",
                permanent=True,
            )
            return
        try:
            job = await self.adapter.retrieve(
                job_id,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
        except ProviderVideoFailure as exc:
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Video provider job polling failed",
                permanent=not exc.retryable,
                retry_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
            )
            return
        if job.state == "failed":
            await self.authority.record_provider_job_failure(
                claim,
                provider_job_id=job.job_id,
                code=str(job.metadata.get("error_code") or "provider_job_failed"),
                message="Video provider job failed",
                provider_response_metadata=job.metadata,
            )
            return
        if job.state in {"queued", "in_progress"}:
            await self.authority.record_poll_pending(
                claim,
                provider_state=job.state,
                progress=job.progress,
                provider_response_metadata=job.metadata,
                poll_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
            )
            return
        if job.state != "completed":
            await self.authority.fail(
                claim,
                code="provider_job_state_unknown",
                message="Video provider returned an unsupported terminal state",
                permanent=True,
            )
            return
        try:
            content = await self.adapter.download_content(
                job.job_id,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
            qa = await self._qa_content(content.body, loaded.request)
            actual_cost, pricing = openai_sora_fixed_cost(loaded.request)
            await self.authority.complete_bytes(
                claim,
                body=content.body,
                content_type=content.content_type,
                provider_response_metadata={**job.metadata, "qa": qa, "pricing": pricing},
                usage_metadata={
                    "seconds": loaded.request.seconds,
                    "size": loaded.request.size,
                    "pricing_revision": pricing["pricing_revision"],
                },
                actual_cost_usd=actual_cost,
                cost_basis="official_fixed_second",
            )
        except ProviderVideoFailure as exc:
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Completed video provider output failed governed download/QA",
                permanent=not exc.retryable,
                retry_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
            )

    async def run_once(self) -> bool:
        if not settings.VIDEO_EXECUTION_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        try:
            loaded = await self._load_execution(claim)
            if claim.mode == "submit":
                await self._submit(claim, loaded)
            elif claim.mode == "reconcile":
                await self._reconcile(claim, loaded)
            elif claim.mode == "poll":
                await self._poll(claim, loaded)
            else:
                await self.authority.fail(
                    claim,
                    code="video_claim_mode_invalid",
                    message="Video execution claim mode is invalid",
                    permanent=True,
                )
            self.write_health("healthy")
            return True
        except Exception:
            self.errors += 1
            logger.exception(
                "video provider worker cycle failed",
                extra={"execution_id": claim.execution_id, "claim_mode": claim.mode},
            )
            try:
                await self.authority.fail(
                    claim,
                    code="video_provider_worker_error",
                    message="Video provider worker cycle failed",
                    permanent=False,
                    retry_after_seconds=int(settings.VIDEO_EXECUTION_POLL_SECONDS),
                )
            except Exception:
                logger.exception(
                    "video provider worker failed to record cycle failure",
                    extra={"execution_id": claim.execution_id},
                )
            self.write_health("degraded")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        self.write_health("healthy" if settings.VIDEO_EXECUTION_LIVE_ENABLED else "disabled")
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.VIDEO_EXECUTION_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.VIDEO_EXECUTION_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        status = str(payload.get("status") or "")
        version_ok = payload.get("ffmpeg_version") in {
            None,
            settings.MEDIA_FFMPEG_TARGET_VERSION,
        }
        return 0 if status in {"healthy", "disabled", "degraded"} and version_ok and age <= 120 else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    setup_logging()
    asyncio.run(VideoProviderWorker().run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
