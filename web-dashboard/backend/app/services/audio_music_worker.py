"""Fail-closed hard-disabled-by-default Gemini Lyria 3 worker."""
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


def _now() -> datetime:
    return datetime.now(UTC)


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
            "models": ["lyria-3-clip-preview", "lyria-3-pro-preview"],
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
            if row is None or row.status != "running" or row.provider_state != "not_started":
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
            credential = provider_credential(provider)
            base_url = validate_provider_base_url(provider.type, provider.base_url)
            if not credential or not base_url:
                raise ProviderMusicFailure("provider_unconfigured", retryable=False)
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
        return LoadedMusicExecution(
            request=request,
            credential=credential,
            base_url=base_url,
        )

    async def run_once(self) -> bool:
        if not settings.AUDIO_MUSIC_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        submission_started = False
        try:
            loaded = await self._load_execution(claim)
            adapter = self.adapters.get(loaded.request.provider)
            if adapter is None:
                raise ProviderMusicFailure(
                    "provider_adapter_unavailable", retryable=False
                )
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
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Lyria music provider execution failed",
                ambiguous_submission=bool(exc.ambiguous_submission),
            )
            self.write_health("degraded")
            return True
        except AudioMusicExecutionError:
            self.errors += 1
            await self.authority.fail(
                claim,
                code="music_result_rejected",
                message="Lyria result failed the governed completion contract",
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
            await self.authority.fail(
                claim,
                code="audio_music_worker_error",
                message="Music worker execution failed",
                ambiguous_submission=submission_started,
            )
            self.write_health("degraded")
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
        return 0 if status in {"healthy", "disabled", "degraded"} and age <= 120 else 1
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
