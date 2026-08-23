"""Fail-closed hard-disabled-by-default governed Lyria 3 worker."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AIProvider, AudioMusicExecution, MediaAssetNode
from app.services.ai_runtime_service import (
    provider_credential,
    provider_enabled,
    validate_provider_base_url,
)
from app.services.audio_music_providers import (
    ProviderMusicAdapter,
    ProviderMusicFailure,
    ProviderMusicRequest,
    default_music_adapters,
)
from app.services.audio_music_runtime import (
    AudioMusicClaim,
    AudioMusicExecutionAuthority,
    AudioMusicExecutionError,
)
from app.services.media_storage import MediaObjectStore, media_object_store

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedMusicExecution:
    request: ProviderMusicRequest
    credential: str
    base_url: str
    provider_state: str
    provider_request_id: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _read_private_secret(path_value: str) -> str:
    path = Path(path_value)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderMusicFailure("provider_unconfigured", retryable=False) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ProviderMusicFailure("provider_secret_file", retryable=False)
    if metadata.st_size <= 0 or metadata.st_size > 4_096:
        raise ProviderMusicFailure("provider_secret_file", retryable=False)
    if metadata.st_mode & 0o077:
        raise ProviderMusicFailure("provider_secret_permissions", retryable=False)
    if metadata.st_uid not in {0, os.geteuid()}:
        raise ProviderMusicFailure("provider_secret_owner", retryable=False)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProviderMusicFailure("provider_unconfigured", retryable=False) from exc
    if not 20 <= len(value) <= 512 or any(character.isspace() for character in value):
        raise ProviderMusicFailure("provider_unconfigured", retryable=False)
    return value


def _replicate_base_url() -> str:
    raw = str(settings.AUDIO_MUSIC_REPLICATE_BASE_URL or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if (
        raw != "https://api.replicate.com"
        or parsed.scheme != "https"
        or parsed.hostname != "api.replicate.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ProviderMusicFailure("provider_base_url", retryable=False)
    return raw


class AudioMusicWorker:
    def __init__(
        self,
        *,
        authority: AudioMusicExecutionAuthority | None = None,
        store: MediaObjectStore | None = None,
        adapters: dict[str, ProviderMusicAdapter] | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.AUDIO_MUSIC_WORKER_ID).strip()
        self.worker_id = configured or f"audio-music:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.authority = authority or AudioMusicExecutionAuthority(
            store=self.store,
            worker_id=self.worker_id,
            lease_seconds=int(settings.AUDIO_MUSIC_LEASE_SECONDS),
            max_content_bytes=int(settings.AUDIO_MUSIC_MAX_PROVIDER_BYTES),
        )
        self.adapters = adapters or default_music_adapters(
            timeout_seconds=float(settings.AUDIO_MUSIC_PROVIDER_TIMEOUT_SECONDS),
            max_content_bytes=int(settings.AUDIO_MUSIC_MAX_PROVIDER_BYTES),
            replicate_poll_seconds=float(settings.AUDIO_MUSIC_REPLICATE_POLL_SECONDS),
            replicate_max_polls=int(settings.AUDIO_MUSIC_REPLICATE_MAX_POLLS),
        )
        self.health_path = Path(settings.AUDIO_MUSIC_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": bool(settings.AUDIO_MUSIC_LIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "providers": sorted(self.adapters),
            "models": [
                "google/lyria-3",
                "google/lyria-3-pro",
                "lyria-3-clip-preview",
                "lyria-3-pro-preview",
            ],
            "default_provider": "replicate",
            "gemini_fallback": True,
            "draft_first": True,
            "default_tier": "draft",
            "draft_fixed_cost_usd": 0.04,
            "final_fixed_cost_usd": 0.08,
            "max_attempts": 1,
            "automatic_retry": False,
            "full_song_requires_approval": True,
            "preview_models": True,
            "named_artist_imitation_enabled": False,
            "voice_clone_enabled": False,
            "voice_transformation_enabled": False,
            "dedicated_sfx_generation_enabled": False,
            "raw_prompt_returned": False,
            "raw_lyrics_returned": False,
            "raw_provider_text_returned": False,
            "durable_prediction_resume": True,
            "provider_job_id_returned": False,
            "provider_output_url_returned": False,
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
            await session.execute(select(AudioMusicExecution.id).limit(1))

    async def _load_execution(self, claim: AudioMusicClaim) -> LoadedMusicExecution:
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, claim.execution_id)
            if (
                row is None
                or row.status != "running"
                or row.provider_state not in {"not_started", "submitted"}
            ):
                raise ProviderMusicFailure("execution_unavailable", retryable=False)
            target = await session.get(MediaAssetNode, row.target_node_id)
            if (
                target is None
                or target.graph_id != row.graph_id
                or target.organization_id != row.organization_id
            ):
                raise ProviderMusicFailure("execution_scope", retryable=False)
            music = (target.prompt_metadata or {}).get("audio_music")
            if not isinstance(music, dict):
                raise ProviderMusicFailure("execution_input", retryable=False)
            prompt = str(music.get("prompt") or "")
            lyrics = str(music.get("lyrics") or "")
            if not prompt or str(music.get("prompt_sha256") or "") != row.prompt_sha256:
                raise ProviderMusicFailure("execution_input", retryable=False)
            if row.lyrics_sha256 and str(music.get("lyrics_sha256") or "") != row.lyrics_sha256:
                raise ProviderMusicFailure("execution_input", retryable=False)
            if row.provider == "replicate":
                credential = _read_private_secret(
                    settings.AUDIO_MUSIC_REPLICATE_TOKEN_FILE
                )
                base_url = _replicate_base_url()
            else:
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
                    raise ProviderMusicFailure("provider_authority", retryable=False)
                provider = providers[0]
                stored_credential = provider_credential(provider)
                validated_base_url = validate_provider_base_url(
                    provider.type, provider.base_url
                )
                if not stored_credential or not validated_base_url:
                    raise ProviderMusicFailure("provider_unconfigured", retryable=False)
                credential = stored_credential
                base_url = validated_base_url
            request = ProviderMusicRequest(
                provider=row.provider,
                model=row.model,
                operation=row.operation,
                tier=row.tier,
                prompt=prompt,
                instrumental_only=bool(row.instrumental_only),
                lyrics=lyrics,
                output_format=row.output_format,
            )
            provider_state = row.provider_state
            provider_request_id = row.provider_request_id
        return LoadedMusicExecution(
            request=request,
            credential=credential,
            base_url=base_url,
            provider_state=provider_state,
            provider_request_id=provider_request_id,
        )

    async def _run_replicate(
        self,
        claim: AudioMusicClaim,
        loaded: LoadedMusicExecution,
        adapter: Any,
    ) -> bool:
        if loaded.provider_state == "not_started":
            await self.authority.mark_submission_started(claim)
            submission = await adapter.submit(
                loaded.request,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
            await self.authority.mark_submitted(
                claim,
                provider_request_id=submission.prediction_id,
                provider_response_metadata=submission.metadata,
            )
            return True

        job_id = str(loaded.provider_request_id or "").strip()
        if not job_id:
            raise ProviderMusicFailure("provider_job_invalid", retryable=False)
        poll = await adapter.poll(
            job_id,
            credential=loaded.credential,
            base_url=loaded.base_url,
        )
        if poll.status in {"starting", "processing"}:
            await self.authority.mark_poll_pending(
                claim,
                provider_response_metadata=poll.metadata,
                delay_seconds=int(settings.AUDIO_MUSIC_REPLICATE_POLL_SECONDS),
                max_polls=int(settings.AUDIO_MUSIC_REPLICATE_MAX_POLLS),
            )
            return True
        if poll.status in {"failed", "canceled", "aborted"}:
            await self.authority.fail(
                claim,
                code=f"provider_prediction_{poll.status}",
                message="Replicate Lyria prediction reached a terminal failure",
                ambiguous_submission=False,
            )
            return True
        if poll.status != "succeeded" or not poll.output_url:
            raise ProviderMusicFailure(
                "provider_poll_response",
                retryable=True,
                safe_to_resubmit=False,
            )
        result = await adapter.download(
            loaded.request,
            prediction_id=job_id,
            output_url=poll.output_url,
        )
        await self.authority.complete_bytes(
            claim,
            body=result.body,
            content_type=result.content_type,
            provider_request_id=job_id,
            provider_response_metadata={**result.metadata, **poll.metadata},
            usage_metadata=result.usage,
            actual_cost_usd=result.actual_cost_usd,
            cost_basis=result.cost_basis,
        )
        return True

    async def run_once(self) -> bool:
        if not settings.AUDIO_MUSIC_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        loaded: LoadedMusicExecution | None = None
        submission_started = False
        try:
            loaded = await self._load_execution(claim)
            adapter = self.adapters.get(loaded.request.provider)
            if adapter is None:
                raise ProviderMusicFailure(
                    "provider_adapter_unavailable", retryable=False
                )
            if loaded.request.provider == "replicate":
                submission_started = loaded.provider_state == "not_started"
                worked = await self._run_replicate(claim, loaded, adapter)
                self.write_health("healthy")
                return worked

            await self.authority.mark_submission_started(claim)
            submission_started = True
            result = await adapter.invoke(
                loaded.request,
                credential=loaded.credential,
                base_url=loaded.base_url,
            )
            await self.authority.complete_bytes(
                claim,
                body=result.body,
                content_type=result.content_type,
                provider_request_id=result.request_id,
                provider_response_metadata=result.metadata,
                usage_metadata=result.usage,
                actual_cost_usd=result.actual_cost_usd,
                cost_basis=result.cost_basis,
            )
            self.write_health("healthy")
            return True
        except ProviderMusicFailure as exc:
            self.errors += 1
            if (
                loaded is not None
                and loaded.request.provider == "replicate"
                and loaded.provider_state == "submitted"
                and loaded.provider_request_id
                and exc.retryable
                and not exc.ambiguous_submission
            ):
                try:
                    await self.authority.mark_poll_pending(
                        claim,
                        provider_response_metadata={
                            "poll_error_code": exc.code,
                            "poll_error_retryable": True,
                        },
                        delay_seconds=int(settings.AUDIO_MUSIC_REPLICATE_POLL_SECONDS),
                        max_polls=int(settings.AUDIO_MUSIC_REPLICATE_MAX_POLLS),
                    )
                    self.write_health("degraded")
                    return True
                except AudioMusicExecutionError:
                    await self.authority.fail(
                        claim,
                        code="provider_poll_exhausted",
                        message="Replicate Lyria polling exceeded its bounded limit",
                        ambiguous_submission=False,
                    )
                    self.write_health("degraded")
                    return True
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Governed music provider execution failed",
                ambiguous_submission=bool(
                    exc.ambiguous_submission
                    or (submission_started and loaded is None)
                ),
            )
            self.write_health(
                "needs_review" if exc.ambiguous_submission else "degraded"
            )
            return True
        except AudioMusicExecutionError:
            self.errors += 1
            await self.authority.fail(
                claim,
                code="music_result_rejected",
                message="Music result failed the governed completion contract",
                ambiguous_submission=False,
            )
            self.write_health("degraded")
            return True
        except Exception:
            self.errors += 1
            logger.exception(
                "audio music worker cycle failed",
                extra={"execution_id": claim.execution_id},
            )
            ambiguous = bool(
                submission_started
                and (loaded is None or loaded.provider_state == "not_started")
            )
            await self.authority.fail(
                claim,
                code="audio_music_worker_error",
                message="Music worker execution failed",
                ambiguous_submission=ambiguous,
            )
            self.write_health("needs_review" if ambiguous else "degraded")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.AUDIO_MUSIC_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.AUDIO_MUSIC_WORKER_HEALTH_FILE)
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


async def _main() -> None:
    setup_logging()
    worker = AudioMusicWorker()
    worker.write_health("starting")
    await worker.run_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
