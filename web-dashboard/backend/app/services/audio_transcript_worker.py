"""Fail-closed Phase 36G persistent speech-to-text worker."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AIProvider, AudioTranscriptExecution, MediaAssetNode
from app.services.ai_runtime_service import (
    provider_credential,
    provider_enabled,
    validate_provider_base_url,
)
from app.services.audio_transcript_providers import (
    OpenAITranscriptAdapter,
    ProviderTranscriptFailure,
    ProviderTranscriptRequest,
    default_transcript_adapters,
    inspect_governed_wav,
)
from app.services.audio_transcript_runtime import (
    AudioTranscriptClaim,
    AudioTranscriptExecutionAuthority,
)
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import select

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedTranscriptExecution:
    request: ProviderTranscriptRequest
    credential: str
    base_url: str


def _now() -> datetime:
    return datetime.now(UTC)


class AudioTranscriptWorker:
    def __init__(
        self,
        *,
        authority: AudioTranscriptExecutionAuthority | None = None,
        store: MediaObjectStore | None = None,
        adapters: dict[str, OpenAITranscriptAdapter] | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.AUDIO_TRANSCRIPT_WORKER_ID).strip()
        self.worker_id = configured or f"audio-transcript:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.authority = authority or AudioTranscriptExecutionAuthority(
            store=self.store,
            worker_id=self.worker_id,
            lease_seconds=int(settings.AUDIO_TRANSCRIPT_LEASE_SECONDS),
        )
        self.adapters = adapters or default_transcript_adapters(
            timeout_seconds=float(settings.AUDIO_TRANSCRIPT_PROVIDER_TIMEOUT_SECONDS)
        )
        self.health_path = Path(settings.AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": bool(settings.AUDIO_TRANSCRIPT_LIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "providers": sorted(self.adapters),
            "model": "gpt-4o-mini-transcribe-2025-12-15",
            "max_attempts": 1,
            "raw_transcript_returned": False,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> None:
        await asyncio.to_thread(self.store.preflight)
        async with SessionLocal() as session:
            await session.execute(select(AudioTranscriptExecution.id).limit(1))

    async def _load_execution(
        self,
        claim: AudioTranscriptClaim,
    ) -> LoadedTranscriptExecution:
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, claim.execution_id)
            if (
                row is None
                or row.status != "running"
                or row.operation != "transcribe"
                or row.provider != "openai"
                or row.model != "gpt-4o-mini-transcribe-2025-12-15"
            ):
                raise ProviderTranscriptFailure(
                    "execution_unavailable", retryable=False
                )
            target = await session.get(MediaAssetNode, row.target_node_id)
            if (
                target is None
                or target.graph_id != row.graph_id
                or target.organization_id != row.organization_id
                or target.node_type != "transcript-package"
            ):
                raise ProviderTranscriptFailure("execution_scope", retryable=False)
            provider_type = row.provider
            model = row.model
            source_key = row.source_storage_key
            source_checksum = row.source_checksum
            source_size = int(row.source_size_bytes)
            source_media_type = row.source_media_type
            duration_ms = int(row.source_duration_ms)
            sample_rate_hz = int(row.source_sample_rate_hz)
            channels = int(row.source_channels)
            language = row.language
            response_format = row.response_format

        body = await asyncio.to_thread(
            self.store.get_bytes,
            source_key,
            max_bytes=int(settings.AUDIO_TRANSCRIPT_MAX_SOURCE_BYTES),
        )
        if len(body) != source_size:
            raise ProviderTranscriptFailure("provider_input_integrity", retryable=False)
        if hashlib.sha256(body).hexdigest() != source_checksum:
            raise ProviderTranscriptFailure("provider_input_integrity", retryable=False)
        audio = inspect_governed_wav(
            body,
            max_duration_seconds=int(settings.AUDIO_TRANSCRIPT_MAX_DURATION_SECONDS),
        )
        if (
            abs(int(audio["duration_ms"]) - duration_ms) > 20
            or int(audio["sample_rate_hz"]) != sample_rate_hz
            or int(audio["channels"]) != channels
        ):
            raise ProviderTranscriptFailure("provider_input_integrity", retryable=False)

        async with SessionLocal() as session:
            providers = list(
                (
                    await session.scalars(
                        select(AIProvider)
                        .where(
                            AIProvider.organization_id
                            == settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
                            AIProvider.type == provider_type,
                            AIProvider.status == "connected",
                        )
                        .order_by(AIProvider.id)
                    )
                ).all()
            )
            if len(providers) != 1 or not provider_enabled(providers[0]):
                raise ProviderTranscriptFailure("provider_authority", retryable=False)
            credential = provider_credential(providers[0])
            base_url = validate_provider_base_url(
                providers[0].type,
                providers[0].base_url,
            )
            if not credential or not base_url:
                raise ProviderTranscriptFailure(
                    "provider_unconfigured", retryable=False
                )

        return LoadedTranscriptExecution(
            request=ProviderTranscriptRequest(
                provider=provider_type,
                model=model,
                audio=body,
                media_type=source_media_type,
                source_sha256=source_checksum,
                duration_ms=duration_ms,
                language=language,
                response_format=response_format,
                prompt=None,
                max_source_bytes=int(settings.AUDIO_TRANSCRIPT_MAX_SOURCE_BYTES),
                max_duration_seconds=int(
                    settings.AUDIO_TRANSCRIPT_MAX_DURATION_SECONDS
                ),
            ),
            credential=credential,
            base_url=base_url,
        )

    async def run_once(self) -> bool:
        if not settings.AUDIO_TRANSCRIPT_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        try:
            loaded = await self._load_execution(claim)
            adapter = self.adapters.get(loaded.request.provider)
            if adapter is None:
                raise ProviderTranscriptFailure(
                    "provider_adapter_unavailable", retryable=False
                )
            await self.authority.mark_submission_started(claim)
            result = await adapter.invoke(
                loaded.request,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
            await self.authority.complete_text(
                claim,
                text=result.text,
                provider_request_id=result.request_id,
                provider_response_metadata=result.metadata,
                usage_metadata=result.usage,
                actual_cost_usd=result.actual_cost_usd,
                cost_basis=result.cost_basis,
            )
            self.write_health("healthy")
            return True
        except ProviderTranscriptFailure as exc:
            self.errors += 1
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Transcript provider execution failed",
                ambiguous=exc.ambiguous_submission,
                safe_to_resubmit=exc.safe_to_resubmit,
            )
            self.write_health(
                "needs_review" if exc.ambiguous_submission else "degraded"
            )
            return True
        except Exception:
            self.errors += 1
            logger.exception(
                "audio transcript worker cycle failed",
                extra={"execution_id": claim.execution_id},
            )
            await self.authority.fail(
                claim,
                code="audio_transcript_worker_error",
                message="Audio transcript worker execution failed",
                ambiguous=True,
            )
            self.write_health("needs_review")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.AUDIO_TRANSCRIPT_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.AUDIO_TRANSCRIPT_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        status = str(payload.get("status") or "")
        return (
            0
            if status in {"healthy", "disabled", "degraded", "needs_review"}
            and age <= 120
            else 1
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


async def _run() -> None:
    setup_logging()
    worker = AudioTranscriptWorker()
    await worker.run_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
