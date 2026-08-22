"""Fail-closed Phase 36G stock-voice dubbing orchestrator."""
from __future__ import annotations

import argparse
import asyncio
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
from app.db.models import AIProvider, AudioDubbingExecution
from app.services.ai_runtime_service import (
    provider_credential,
    provider_enabled,
    validate_provider_base_url,
)
from app.services.audio_dubbing_pipeline import (
    AudioDubbingPipelineError,
    create_dubbing_final_pipeline,
    create_dubbing_speech_pipelines_from_private,
    finalize_dubbing_execution,
    load_private_transcript_document,
    load_private_translation,
    refresh_dubbing_speech_status,
)
from app.services.audio_dubbing_providers import (
    DubbingTranslationSourceSegment,
    OpenAIDubbingTranslationAdapter,
    ProviderDubbingTranslationFailure,
    ProviderDubbingTranslationRequest,
    default_dubbing_translation_adapters,
)
from aios.phase36_audio_transcript import TranscriptDocument
from app.services.audio_dubbing_runtime import (
    AudioDubbingClaim,
    AudioDubbingExecutionAuthority,
)
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import select

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedDubbingTranslation:
    request: ProviderDubbingTranslationRequest
    document: TranscriptDocument
    credential: str
    base_url: str


def _now() -> datetime:
    return datetime.now(UTC)


class AudioDubbingWorker:
    def __init__(
        self,
        *,
        authority: AudioDubbingExecutionAuthority | None = None,
        store: MediaObjectStore | None = None,
        adapters: dict[str, OpenAIDubbingTranslationAdapter] | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.AUDIO_DUBBING_WORKER_ID).strip()
        self.worker_id = configured or f"audio-dubbing:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.authority = authority or AudioDubbingExecutionAuthority(
            store=self.store,
            worker_id=self.worker_id,
            lease_seconds=int(settings.AUDIO_DUBBING_LEASE_SECONDS),
        )
        self.adapters = adapters or default_dubbing_translation_adapters(
            timeout_seconds=float(settings.AUDIO_DUBBING_PROVIDER_TIMEOUT_SECONDS)
        )
        self.health_path = Path(settings.AUDIO_DUBBING_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": bool(settings.AUDIO_DUBBING_LIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "providers": sorted(self.adapters),
            "translation_model": "gpt-5.6-luna",
            "speech_model": "gpt-4o-mini-tts-2025-12-15",
            "operations": [
                "translate-private-segments",
                "spawn-stock-speech",
                "timing-fit-pad",
                "mix-master-final",
            ],
            "stock_voice_only": True,
            "custom_voice_enabled": False,
            "known_speaker_identification_enabled": False,
            "voice_clone_enabled": False,
            "voice_transformation_enabled": False,
            "raw_translation_returned": False,
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
            await session.execute(select(AudioDubbingExecution.id).limit(1))

    async def _load_translation(
        self,
        claim: AudioDubbingClaim,
    ) -> LoadedDubbingTranslation:
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, claim.execution_id)
            if (
                row is None
                or row.status != "running"
                or row.provider_state != "not_started"
                or row.provider != "openai"
                or row.model != "gpt-5.6-luna"
            ):
                raise ProviderDubbingTranslationFailure(
                    "execution_unavailable", retryable=False
                )
            source_key = row.source_transcript_storage_key
            source_checksum = row.source_transcript_object_checksum
            source_size = int(row.source_transcript_object_size_bytes)
            source_language = row.source_language
            target_language = row.target_language
            provider_type = row.provider
            model = row.model
            source_transcript_checksum = row.source_transcript_checksum

        document = await asyncio.to_thread(
            load_private_transcript_document,
            store=self.store,
            storage_key=source_key,
            object_checksum=source_checksum,
            object_size_bytes=source_size,
            max_bytes=int(settings.AUDIO_DUBBING_MAX_TRANSCRIPT_BYTES),
        )
        if document.checksum != source_transcript_checksum:
            raise ProviderDubbingTranslationFailure(
                "provider_input_integrity", retryable=False
            )
        segments = tuple(
            DubbingTranslationSourceSegment(
                segment_id=item.segment_id,
                speaker_key=item.speaker_key,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                text=item.text,
            )
            for item in document.segments
        )

        # Credential access occurs only after the complete private source has
        # passed checksum/schema/timeline validation.
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
                raise ProviderDubbingTranslationFailure(
                    "provider_authority", retryable=False
                )
            credential = provider_credential(providers[0])
            base_url = validate_provider_base_url(
                providers[0].type,
                providers[0].base_url,
            )
            if not credential or not base_url:
                raise ProviderDubbingTranslationFailure(
                    "provider_unconfigured", retryable=False
                )
        return LoadedDubbingTranslation(
            request=ProviderDubbingTranslationRequest(
                provider=provider_type,
                model=model,
                source_language=source_language,
                target_language=target_language,
                segments=segments,
            ),
            document=document,
            credential=credential,
            base_url=base_url,
        )

    async def _translate_claim(self, claim: AudioDubbingClaim) -> None:
        loaded = await self._load_translation(claim)
        adapter = self.adapters.get(loaded.request.provider)
        if adapter is None:
            raise ProviderDubbingTranslationFailure(
                "provider_adapter_unavailable", retryable=False
            )
        await self.authority.mark_submission_started(claim)
        result = await adapter.invoke(
            loaded.request,
            credential=loaded.credential,
            base_url=loaded.base_url,
        )
        completed = await self.authority.complete_translation(
            claim,
            document=loaded.document,
            translations=result.translations,
            provider_request_id=result.request_id,
            provider_response_metadata=result.metadata,
            usage_metadata=result.usage,
            actual_cost_usd=result.actual_cost_usd,
            cost_basis=result.cost_basis,
        )
        document, translations = await asyncio.to_thread(
            load_private_translation,
            store=self.store,
            storage_key=completed["translation_storage_key"],
            checksum=completed["translation_checksum"],
            size_bytes=(await self._translation_size(claim.execution_id)),
            max_bytes=int(settings.AUDIO_DUBBING_MAX_TRANSCRIPT_BYTES),
        )
        async with SessionLocal() as session:
            await create_dubbing_speech_pipelines_from_private(
                session,
                execution_id=claim.execution_id,
                organization_id=(await self._organization_id(claim.execution_id)),
                document=document,
                translations=translations,
            )
            await session.commit()

    async def _translation_size(self, execution_id: str) -> int:
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            if row is None or row.translation_size_bytes is None:
                raise AudioDubbingPipelineError(
                    "private translation size is unavailable"
                )
            return int(row.translation_size_bytes)

    async def _organization_id(self, execution_id: str) -> str:
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            if row is None:
                raise AudioDubbingPipelineError("dubbing execution disappeared")
            return row.organization_id

    async def _advance_one(self) -> bool:
        async with SessionLocal() as session:
            row = await session.scalar(
                select(AudioDubbingExecution)
                .where(
                    AudioDubbingExecution.status.in_(
                        ("speech_running", "speech_completed", "rendering")
                    )
                )
                .order_by(
                    AudioDubbingExecution.created_at,
                    AudioDubbingExecution.id,
                )
                .limit(1)
            )
            if row is None:
                return False
            execution_id = row.id
            organization_id = row.organization_id
            status = row.status
        if status == "speech_running":
            async with SessionLocal() as session:
                refreshed = await refresh_dubbing_speech_status(
                    session,
                    execution_id=execution_id,
                    organization_id=organization_id,
                )
                await session.commit()
            if refreshed == "speech_completed":
                async with SessionLocal() as session:
                    await create_dubbing_final_pipeline(
                        session,
                        execution_id=execution_id,
                        organization_id=organization_id,
                    )
                    await session.commit()
            return True
        if status == "speech_completed":
            async with SessionLocal() as session:
                await create_dubbing_final_pipeline(
                    session,
                    execution_id=execution_id,
                    organization_id=organization_id,
                )
                await session.commit()
            return True
        if status == "rendering":
            try:
                async with SessionLocal() as session:
                    await finalize_dubbing_execution(
                        session,
                        execution_id=execution_id,
                        organization_id=organization_id,
                    )
                    await session.commit()
                return True
            except AudioDubbingPipelineError as exc:
                if "not complete" in str(exc):
                    return False
                raise
        return False

    async def run_once(self) -> bool:
        if not settings.AUDIO_DUBBING_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is not None:
            self.cycles += 1
            try:
                await self._translate_claim(claim)
                self.write_health("healthy")
                return True
            except ProviderDubbingTranslationFailure as exc:
                self.errors += 1
                await self.authority.fail(
                    claim,
                    code=exc.code,
                    message="Dubbing translation provider execution failed",
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
                    "audio dubbing translation cycle failed",
                    extra={"execution_id": claim.execution_id},
                )
                await self.authority.fail(
                    claim,
                    code="audio_dubbing_worker_error",
                    message="Audio dubbing translation failed",
                    ambiguous=True,
                )
                self.write_health("needs_review")
                return True
        try:
            worked = await self._advance_one()
            self.write_health("healthy")
            return worked
        except Exception:
            self.errors += 1
            logger.exception("audio dubbing orchestration cycle failed")
            self.write_health("degraded")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.AUDIO_DUBBING_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.AUDIO_DUBBING_WORKER_HEALTH_FILE)
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
    worker = AudioDubbingWorker()
    worker.write_health("starting")
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
