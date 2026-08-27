"""Hard-disabled-by-default Phase 36G open-song RunPod worker.

The worker submits at most once, persists the provider job identity before any
polling, and only resumes that same durable job.  It downloads a full 48 kHz
stereo WAV plus four Demucs stems from an explicit host allowlist, verifies all
bytes, and then publishes the bundle atomically into the Media DAG.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AudioSongExecution, MediaAssetNode
from app.services.audio_song_providers import (
    AudioSongProviderFailure,
    ProviderAudioArtifact,
    ProviderOpenSongJob,
    ProviderOpenSongRequest,
    ProviderOpenSongResult,
    RunPodOpenSongAdapter,
)
from app.services.audio_song_runtime import (
    AudioSongExecutionError,
    claim_audio_song_execution,
    complete_audio_song_provider_output,
    defer_audio_song_provider_poll,
    fail_audio_song_execution,
    hold_audio_song_execution_for_review,
    mark_audio_song_submitting,
    record_audio_song_provider_job,
    record_audio_song_provider_poll,
    recover_expired_audio_song_executions,
)
from app.services.audio_speech_providers import inspect_pcm_wav
from app.services.media_storage import (
    MediaObjectStore,
    MediaStorageError,
    StoredMediaObject,
    media_object_store,
)

logger = get_logger(__name__)
_HEALTH_MAX_AGE_SECONDS = 120
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9_-]{6,160}$")
_REPOSITORY_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{3,239}$")
_PENDING_STATES = frozenset({"IN_QUEUE", "IN_PROGRESS"})
_TERMINAL_FAILURE_STATES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})
_REQUIRED_STEMS = ("vocals", "drums", "bass", "other")


class AudioSongWorkerError(RuntimeError):
    """A worker configuration or durable transition is unsafe."""


@dataclass(frozen=True, slots=True)
class OpenSongWorkerSecrets:
    api_key: str
    endpoint_id: str
    artifact_hosts: frozenset[str]
    runtime_image_repository: str
    runtime_image_index_digest: str
    runtime_image_digest: str
    image_sbom_sha256: str
    handler_source_sha256: str

    @property
    def endpoint_id_sha256(self) -> str:
        return hashlib.sha256(self.endpoint_id.encode("utf-8")).hexdigest()

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> "OpenSongWorkerSecrets":
        api_key = str(values.get("RUNPOD_API_KEY") or "").strip()
        endpoint_id = str(
            values.get("AUDIO_SONG_RUNPOD_ENDPOINT_ID") or ""
        ).strip()
        hosts = frozenset(
            item.strip().lower().rstrip(".")
            for item in str(values.get("AUDIO_SONG_ARTIFACT_HOSTS") or "").split(",")
            if item.strip()
        )
        repository = str(
            values.get("AUDIO_SONG_RUNTIME_IMAGE_REPOSITORY") or ""
        ).strip().lower()
        index_digest = str(
            values.get("AUDIO_SONG_RUNTIME_IMAGE_INDEX_DIGEST") or ""
        ).strip().lower()
        digest = str(
            values.get("AUDIO_SONG_RUNTIME_IMAGE_DIGEST") or ""
        ).strip().lower()
        sbom = str(values.get("AUDIO_SONG_IMAGE_SBOM_SHA256") or "").strip().lower()
        source = str(
            values.get("AUDIO_SONG_HANDLER_SOURCE_SHA256") or ""
        ).strip().lower()
        if not 16 <= len(api_key) <= 512 or any(char.isspace() for char in api_key):
            raise AudioSongWorkerError("open-song RunPod credential is incomplete")
        if not _ENDPOINT_RE.fullmatch(endpoint_id):
            raise AudioSongWorkerError("open-song RunPod endpoint is incomplete")
        if not hosts or any(
            "/" in host or ":" in host or " " in host for host in hosts
        ):
            raise AudioSongWorkerError("open-song artifact host allowlist is invalid")
        if not _REPOSITORY_RE.fullmatch(repository) or ".." in repository:
            raise AudioSongWorkerError("open-song runtime image repository is invalid")
        if not _IMAGE_DIGEST_RE.fullmatch(index_digest):
            raise AudioSongWorkerError("open-song runtime image index is invalid")
        if not _IMAGE_DIGEST_RE.fullmatch(digest):
            raise AudioSongWorkerError("open-song runtime image digest is invalid")
        if not _SHA256_RE.fullmatch(sbom):
            raise AudioSongWorkerError("open-song runtime SBOM evidence is invalid")
        if not _SHA256_RE.fullmatch(source):
            raise AudioSongWorkerError("open-song handler source evidence is invalid")
        return cls(
            api_key=api_key,
            endpoint_id=endpoint_id,
            artifact_hosts=hosts,
            runtime_image_repository=repository,
            runtime_image_index_digest=index_digest,
            runtime_image_digest=digest,
            image_sbom_sha256=sbom,
            handler_source_sha256=source,
        )

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "endpoint_id_sha256": self.endpoint_id_sha256,
            "artifact_hosts_count": len(self.artifact_hosts),
            "runtime_image_repository": self.runtime_image_repository,
            "runtime_image_index_digest": self.runtime_image_index_digest,
            "runtime_image_digest": self.runtime_image_digest,
            "image_sbom_sha256": self.image_sbom_sha256,
            "handler_source_sha256": self.handler_source_sha256,
            "credential_returned": False,
            "endpoint_id_returned": False,
            "artifact_hosts_returned": False,
        }


@dataclass(frozen=True, slots=True)
class AudioSongClaim:
    execution_id: str
    organization_id: str
    lease_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class LoadedAudioSong:
    claim: AudioSongClaim
    request: ProviderOpenSongRequest
    provider_state: str
    provider_job_id: str | None
    polls: int
    rate_usd_per_second: float
    max_cost_usd: float
    max_billed_seconds: int
    graph_id: str


def _read_secret_file(path: str) -> dict[str, str]:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise AudioSongWorkerError("open-song provider secret file is unavailable")
    try:
        stat = source.stat()
    except OSError as exc:
        raise AudioSongWorkerError("open-song provider secret file is unavailable") from exc
    if stat.st_size <= 0 or stat.st_size > 32_768 or stat.st_mode & 0o077:
        raise AudioSongWorkerError("open-song provider secret file is not private")
    values: dict[str, str] = {}
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AudioSongWorkerError("open-song provider secret file is unreadable") from exc
    if len(lines) > 256:
        raise AudioSongWorkerError("open-song provider secret file is oversized")
    for raw in lines:
        if len(raw) > 4_096:
            raise AudioSongWorkerError("open-song provider secret line is oversized")
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise AudioSongWorkerError("open-song provider secret line is invalid")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", key) or key in values:
            raise AudioSongWorkerError("open-song provider secret key is invalid")
        normalized = value.strip().strip('"').strip("'")
        if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
            raise AudioSongWorkerError("open-song provider secret value is invalid")
        values[key] = normalized
    return values


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _private_text(value: object, *, label: str, minimum: int, maximum: int) -> str:
    text = str(value or "").strip()
    if not minimum <= len(text) <= maximum or "\x00" in text:
        raise AudioSongWorkerError(f"open-song private {label} is invalid")
    return text


class AudioSongWorker:
    def __init__(
        self,
        *,
        adapter: RunPodOpenSongAdapter | None = None,
        store: MediaObjectStore | None = None,
        secrets: OpenSongWorkerSecrets | None = None,
        live_enabled: bool | None = None,
        worker_id: str | None = None,
        poll_seconds: int | None = None,
        lease_seconds: int | None = None,
        max_polls: int | None = None,
        health_path: str | Path | None = None,
    ) -> None:
        configured_id = str(worker_id or settings.AUDIO_SONG_WORKER_ID or "").strip()
        self.worker_id = configured_id or f"audio-song:{socket.gethostname()}"
        self.live_enabled = (
            bool(settings.AUDIO_SONG_LIVE_ENABLED)
            if live_enabled is None
            else bool(live_enabled)
        )
        self.poll_seconds = max(
            1,
            min(
                60,
                int(
                    settings.AUDIO_SONG_POLL_SECONDS
                    if poll_seconds is None
                    else poll_seconds
                ),
            ),
        )
        self.lease_seconds = max(
            30,
            min(
                3_600,
                int(
                    settings.AUDIO_SONG_LEASE_SECONDS
                    if lease_seconds is None
                    else lease_seconds
                ),
            ),
        )
        self.max_polls = max(
            1,
            min(
                2_000,
                int(settings.AUDIO_SONG_MAX_POLLS if max_polls is None else max_polls),
            ),
        )
        self.health_path = Path(
            health_path or settings.AUDIO_SONG_WORKER_HEALTH_FILE
        )
        self.store = store or media_object_store()
        self._secrets = secrets
        self._adapter = adapter
        self.cycles = 0
        self.errors = 0
        self.last_success_at: str | None = None
        self.last_error_code: str | None = None

    def _runtime_secrets(self) -> OpenSongWorkerSecrets:
        if self._secrets is None:
            self._secrets = OpenSongWorkerSecrets.from_values(
                _read_secret_file(settings.AUDIO_SONG_RUNPOD_SECRET_FILE)
            )
        return self._secrets

    def _runtime_adapter(self) -> RunPodOpenSongAdapter:
        if self._adapter is None:
            secrets = self._runtime_secrets()
            self._adapter = RunPodOpenSongAdapter(
                timeout_seconds=float(settings.AUDIO_SONG_PROVIDER_TIMEOUT_SECONDS),
                poll_timeout_seconds=float(
                    settings.AUDIO_SONG_PROVIDER_POLL_TIMEOUT_SECONDS
                ),
                download_timeout_seconds=float(
                    settings.AUDIO_SONG_DOWNLOAD_TIMEOUT_SECONDS
                ),
                max_content_bytes=int(settings.AUDIO_SONG_MAX_PROVIDER_BYTES),
                allowed_artifact_hosts=secrets.artifact_hosts,
                artifact_bridge_origin=settings.PORTAL_PUBLIC_API_ORIGIN,
                artifact_bridge_secret=settings.SECRET_KEY,
                artifact_bridge_ttl_seconds=int(
                    settings.AUDIO_SONG_ARTIFACT_TOKEN_TTL_SECONDS
                ),
            )
        return self._adapter

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": self.live_enabled,
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "last_success_at": self.last_success_at,
            "last_error_code": self.last_error_code,
            "route_allowlist": ["runpod-flex-a40"],
            "max_attempts": 1,
            "max_polls": self.max_polls,
            "automatic_retry": False,
            "automatic_resubmit": False,
            "automatic_cross_provider_fallback": False,
            "durable_provider_job_resume": True,
            "required_stems": list(_REQUIRED_STEMS),
            "raw_title_returned": False,
            "raw_concept_returned": False,
            "raw_lyrics_returned": False,
            "secret_returned": False,
            "runtime_binding_loaded": self._secrets is not None,
            "runtime_binding_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(
            f".{self.health_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.health_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.debug(
                    "audio song worker health temporary cleanup failed",
                    extra={"error_type": type(cleanup_error).__name__},
                )

    async def preflight(self) -> None:
        await asyncio.to_thread(self.store.preflight)
        async with SessionLocal() as session:
            await session.execute(select(AudioSongExecution.id).limit(1))
        if self.live_enabled:
            self._runtime_secrets()
            self._runtime_adapter()

    async def _claim(self) -> AudioSongClaim | None:
        secrets = self._runtime_secrets()
        async with SessionLocal() as session:
            await recover_expired_audio_song_executions(session)
            row = await claim_audio_song_execution(
                session,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                allowed_route_ids={"runpod-flex-a40"},
                endpoint_id_sha256=secrets.endpoint_id_sha256,
            )
            if row is None:
                await session.commit()
                return None
            if not row.lease_token:
                raise AudioSongWorkerError("open-song claim lost its lease token")
            claim = AudioSongClaim(
                execution_id=row.id,
                organization_id=row.organization_id,
                lease_token=row.lease_token,
                fencing_token=int(row.fencing_token),
            )
            await session.commit()
            return claim

    async def _load(self, claim: AudioSongClaim) -> LoadedAudioSong:
        secrets = self._runtime_secrets()
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, claim.execution_id)
            if (
                row is None
                or row.status != "running"
                or row.lease_owner != self.worker_id
                or row.lease_token != claim.lease_token
                or int(row.fencing_token) != claim.fencing_token
            ):
                raise AudioSongWorkerError("open-song worker lease was lost")
            if row.route_id != "runpod-flex-a40" or row.provider != "runpod":
                raise AudioSongWorkerError("open-song worker route is unsupported")
            expected_binding = {
                "endpoint_id_sha256": secrets.endpoint_id_sha256,
                "container_image_repository": secrets.runtime_image_repository,
                "container_image_index_digest": secrets.runtime_image_index_digest,
                "container_image_digest": secrets.runtime_image_digest,
                "image_sbom_sha256": secrets.image_sbom_sha256,
                "handler_source_sha256": secrets.handler_source_sha256,
            }
            for field, expected in expected_binding.items():
                if getattr(row, field) != expected:
                    raise AudioSongWorkerError(
                        f"open-song runtime binding mismatch: {field}"
                    )
            target = await session.get(MediaAssetNode, row.target_node_id)
            if (
                target is None
                or target.graph_id != row.graph_id
                or target.organization_id != row.organization_id
            ):
                raise AudioSongWorkerError("open-song private provider node is unavailable")
            private = (target.prompt_metadata or {}).get("audio_open_song")
            if not isinstance(private, dict):
                raise AudioSongWorkerError("open-song private provider input is unavailable")
            title = _private_text(
                private.get("title"), label="title", minimum=3, maximum=160
            )
            concept = _private_text(
                private.get("concept"), label="concept", minimum=20, maximum=1_000
            )
            lyrics = _private_text(
                private.get("lyrics"), label="lyrics", minimum=40, maximum=8_000
            )
            for value, expected, label in (
                (_hash_text(title), row.title_sha256, "title"),
                (_hash_text(concept), row.concept_sha256, "concept"),
                (_hash_text(lyrics), row.lyrics_sha256, "lyrics"),
            ):
                if value != expected:
                    raise AudioSongWorkerError(
                        f"open-song private {label} checksum changed"
                    )
            expected_private = {
                "route_id": row.route_id,
                "provider": row.provider,
                "model": row.model,
                "model_revision": row.model_revision,
                "language_model": row.language_model,
                "language_model_revision": row.language_model_revision,
                "language": row.language,
                "duration_seconds": row.duration_seconds,
                "bpm": row.bpm,
                "musical_key": row.musical_key,
                "time_signature": row.time_signature,
                "seed": row.seed,
            }
            for key, expected_value in expected_private.items():
                if private.get(key) != expected_value:
                    raise AudioSongWorkerError(
                        f"open-song private input mismatch: {key}"
                    )
            if not row.container_image_digest:
                raise AudioSongWorkerError("open-song handler image is not pinned")
            request = ProviderOpenSongRequest(
                route_id=row.route_id,
                model=row.model,
                model_revision=row.model_revision,
                language_model=row.language_model,
                language_model_revision=row.language_model_revision,
                source_commit=row.source_commit,
                container_image_digest=row.container_image_digest,
                separation_model=row.separation_model,
                separation_source_commit=row.separation_source_commit,
                separation_checkpoint_sha256=row.separation_checkpoint_sha256,
                title=title,
                concept=concept,
                lyrics=lyrics,
                language=row.language,
                duration_seconds=int(row.duration_seconds),
                bpm=int(row.bpm),
                musical_key=row.musical_key,
                time_signature=int(row.time_signature),
                seed=int(row.seed),
            )
            return LoadedAudioSong(
                claim=claim,
                request=request,
                provider_state=row.provider_state,
                provider_job_id=row.provider_job_id,
                polls=int(row.polls),
                rate_usd_per_second=float(row.rate_usd_per_second),
                max_cost_usd=float(row.max_cost_usd),
                max_billed_seconds=int(row.max_billed_seconds),
                graph_id=row.graph_id,
            )

    async def _mark_submitting(self, loaded: LoadedAudioSong) -> None:
        async with SessionLocal() as session:
            await mark_audio_song_submitting(
                session,
                execution_id=loaded.claim.execution_id,
                worker_id=self.worker_id,
                lease_token=loaded.claim.lease_token,
                fencing_token=loaded.claim.fencing_token,
            )
            await session.commit()

    async def _record_job(
        self, loaded: LoadedAudioSong, job: ProviderOpenSongJob
    ) -> None:
        async with SessionLocal() as session:
            await record_audio_song_provider_job(
                session,
                execution_id=loaded.claim.execution_id,
                worker_id=self.worker_id,
                lease_token=loaded.claim.lease_token,
                fencing_token=loaded.claim.fencing_token,
                provider_job_id=job.job_id,
                provider_metadata=job.metadata,
            )
            await session.commit()

    async def _defer(
        self,
        loaded: LoadedAudioSong,
        *,
        state: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if loaded.polls >= self.max_polls:
            await self._review(
                loaded.claim,
                code="open_song_poll_limit_exhausted",
                metadata={"polls": loaded.polls, "max_polls": self.max_polls},
            )
            return
        async with SessionLocal() as session:
            await record_audio_song_provider_poll(
                session,
                execution_id=loaded.claim.execution_id,
                worker_id=self.worker_id,
                lease_token=loaded.claim.lease_token,
                fencing_token=loaded.claim.fencing_token,
                state=state,
                provider_metadata=metadata,
            )
            await defer_audio_song_provider_poll(
                session,
                execution_id=loaded.claim.execution_id,
                worker_id=self.worker_id,
                lease_token=loaded.claim.lease_token,
                fencing_token=loaded.claim.fencing_token,
                delay_seconds=self.poll_seconds,
            )
            await session.commit()

    async def _fail(
        self,
        claim: AudioSongClaim,
        *,
        code: str,
        metadata: dict[str, Any] | None = None,
        ambiguous_submission: bool,
    ) -> None:
        async with SessionLocal() as session:
            await fail_audio_song_execution(
                session,
                execution_id=claim.execution_id,
                worker_id=self.worker_id,
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                error_code=code,
                error_metadata=metadata,
                ambiguous_submission=ambiguous_submission,
            )
            await session.commit()

    async def _review(
        self,
        claim: AudioSongClaim,
        *,
        code: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with SessionLocal() as session:
            await hold_audio_song_execution_for_review(
                session,
                execution_id=claim.execution_id,
                worker_id=self.worker_id,
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                error_code=code,
                error_metadata=metadata,
            )
            await session.commit()

    @staticmethod
    def _inspect_download(
        artifact: ProviderAudioArtifact,
        body: bytes,
    ) -> dict[str, Any]:
        inspected = inspect_pcm_wav(body, max_duration_seconds=190.0)
        if (
            inspected["sample_rate_hz"] != 48_000
            or inspected["channels"] != 2
            or abs(float(inspected["duration_seconds"]) - artifact.duration_seconds)
            > 0.05
        ):
            raise AudioSongWorkerError("open-song WAV evidence is inconsistent")
        return inspected

    async def _store_artifact(
        self,
        loaded: LoadedAudioSong,
        *,
        logical_key: str,
        artifact: ProviderAudioArtifact,
    ) -> tuple[StoredMediaObject, dict[str, Any]]:
        downloaded = await self._runtime_adapter().download(artifact)
        inspected = self._inspect_download(artifact, downloaded.body)
        storage_key = (
            f"media/{loaded.claim.organization_id}/songs/{loaded.graph_id}/"
            f"{logical_key}/f{loaded.claim.fencing_token}.wav"
        )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            storage_key,
            downloaded.body,
            "audio/wav",
            metadata={
                "execution-id": loaded.claim.execution_id,
                "fencing-token": str(loaded.claim.fencing_token),
                "logical-key": logical_key,
            },
        )
        if (
            stored.sha256 != artifact.sha256
            or stored.size_bytes != artifact.size_bytes
            or stored.content_type != "audio/wav"
        ):
            await asyncio.to_thread(self.store.delete, stored.key)
            raise AudioSongWorkerError("open-song stored artifact evidence changed")
        record = {
            "storage_backend": stored.backend,
            "storage_key": stored.key,
            "checksum": stored.sha256,
            "size_bytes": stored.size_bytes,
            "media_type": stored.content_type,
            "duration_seconds": float(inspected["duration_seconds"]),
            "sample_rate_hz": int(inspected["sample_rate_hz"]),
            "channels": int(inspected["channels"]),
        }
        return stored, record

    async def _complete(
        self,
        loaded: LoadedAudioSong,
        job: ProviderOpenSongJob,
        result: ProviderOpenSongResult,
    ) -> None:
        billed_seconds = job.billed_seconds
        if billed_seconds is None:
            await self._review(
                loaded.claim,
                code="open_song_provider_cost_unavailable",
                metadata=job.metadata,
            )
            return
        if billed_seconds > loaded.max_billed_seconds:
            await self._review(
                loaded.claim,
                code="open_song_provider_runtime_cap_exceeded",
                metadata={
                    **job.metadata,
                    "billed_seconds": billed_seconds,
                    "max_billed_seconds": loaded.max_billed_seconds,
                },
            )
            return
        actual_cost = round(loaded.rate_usd_per_second * billed_seconds, 6)
        if actual_cost > loaded.max_cost_usd + 1e-9:
            await self._review(
                loaded.claim,
                code="open_song_provider_cost_cap_exceeded",
                metadata={
                    **job.metadata,
                    "actual_cost_usd": actual_cost,
                    "max_cost_usd": loaded.max_cost_usd,
                },
            )
            return
        stored: list[StoredMediaObject] = []
        try:
            song_stored, song_record = await self._store_artifact(
                loaded, logical_key="song", artifact=result.full_song
            )
            stored.append(song_stored)
            stem_records: dict[str, dict[str, Any]] = {}
            for stem in _REQUIRED_STEMS:
                stem_stored, stem_record = await self._store_artifact(
                    loaded,
                    logical_key=f"stem-{stem}",
                    artifact=result.stems[stem],
                )
                stored.append(stem_stored)
                stem_records[stem] = stem_record
            async with SessionLocal() as session:
                await complete_audio_song_provider_output(
                    session,
                    execution_id=loaded.claim.execution_id,
                    worker_id=self.worker_id,
                    lease_token=loaded.claim.lease_token,
                    fencing_token=loaded.claim.fencing_token,
                    full_song=song_record,
                    stems=stem_records,
                    actual_billed_seconds=billed_seconds,
                    actual_cost_usd=actual_cost,
                    provider_metadata={
                        **result.evidence_snapshot(),
                        **job.metadata,
                    },
                )
                await session.commit()
            cleanup = getattr(self._runtime_adapter(), "cleanup", None)
            if callable(cleanup):
                artifacts = [result.full_song, *(result.stems[stem] for stem in _REQUIRED_STEMS)]
                cleanup_results = await asyncio.gather(
                    *(cleanup(artifact) for artifact in artifacts),
                    return_exceptions=True,
                )
                if not all(item is True for item in cleanup_results):
                    logger.warning(
                        "Open-song artifact ingress cleanup deferred to TTL purge",
                        extra={"execution_id": loaded.claim.execution_id},
                    )
        except Exception:
            for item in stored:
                await asyncio.to_thread(self.store.delete, item.key)
            raise

    async def _handle_job(
        self,
        loaded: LoadedAudioSong,
        job: ProviderOpenSongJob,
    ) -> None:
        if job.state in _PENDING_STATES:
            await self._defer(
                loaded,
                state="running" if job.state == "IN_PROGRESS" else "submitted",
                metadata=job.metadata,
            )
            return
        if job.state in _TERMINAL_FAILURE_STATES:
            await self._fail(
                loaded.claim,
                code=f"open_song_provider_{job.state.lower()}",
                metadata=job.metadata,
                ambiguous_submission=False,
            )
            return
        if job.state != "COMPLETED" or job.result is None:
            await self._review(
                loaded.claim,
                code="open_song_provider_result_unresolved",
                metadata=job.metadata,
            )
            return
        await self._complete(loaded, job, job.result)

    async def run_once(self) -> bool:
        if not self.live_enabled:
            self.write_health("disabled")
            return False
        claim = await self._claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        loaded: LoadedAudioSong | None = None
        try:
            loaded = await self._load(claim)
            secrets = self._runtime_secrets()
            adapter = self._runtime_adapter()
            if loaded.provider_state == "not_started":
                await self._mark_submitting(loaded)
                job = await adapter.submit(
                    loaded.request,
                    credential=secrets.api_key,
                    endpoint_id=secrets.endpoint_id,
                )
                await self._record_job(loaded, job)
                loaded = replace(
                    loaded,
                    provider_state="submitted",
                    provider_job_id=job.job_id,
                )
            elif loaded.provider_state in {"submitted", "running"}:
                if not loaded.provider_job_id:
                    raise AudioSongWorkerError(
                        "open-song durable provider job identity is missing"
                    )
                job = await adapter.retrieve(
                    loaded.provider_job_id,
                    credential=secrets.api_key,
                    endpoint_id=secrets.endpoint_id,
                )
            else:
                raise AudioSongWorkerError(
                    "open-song provider state cannot be processed"
                )
            await self._handle_job(loaded, job)
            self.last_success_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.last_error_code = None
            self.write_health("healthy")
            return True
        except AudioSongProviderFailure as exc:
            self.errors += 1
            self.last_error_code = exc.code
            if (
                loaded is not None
                and loaded.provider_job_id
                and exc.retryable
                and not exc.ambiguous_submission
            ):
                await self._defer(
                    loaded,
                    state=(
                        "running"
                        if loaded.provider_state == "running"
                        else "submitted"
                    ),
                    metadata={
                        "error_code": exc.code,
                        "http_status": exc.http_status,
                    },
                )
                self.write_health("degraded")
                return True
            await self._fail(
                claim,
                code=exc.code,
                metadata={
                    **exc.metadata,
                    "http_status": exc.http_status,
                },
                ambiguous_submission=exc.ambiguous_submission,
            )
            self.write_health(
                "needs_review" if exc.ambiguous_submission else "degraded"
            )
            return True
        except (AudioSongWorkerError, AudioSongExecutionError) as exc:
            self.errors += 1
            self.last_error_code = type(exc).__name__
            try:
                await self._review(
                    claim,
                    code="open_song_worker_contract_failure",
                    metadata={"error_type": type(exc).__name__},
                )
            except AudioSongExecutionError:
                logger.exception(
                    "open-song worker could not persist review state",
                    execution_id=claim.execution_id,
                )
            self.write_health("needs_review")
            return True
        except MediaStorageError as exc:
            self.errors += 1
            self.last_error_code = "media_storage"
            if loaded is not None and loaded.provider_job_id:
                await self._defer(
                    loaded,
                    state=(
                        "running"
                        if loaded.provider_state == "running"
                        else "submitted"
                    ),
                    metadata={"error_type": type(exc).__name__},
                )
                self.write_health("degraded")
                return True
            await self._review(
                claim,
                code="open_song_storage_failure",
                metadata={"error_type": type(exc).__name__},
            )
            self.write_health("needs_review")
            return True
        except Exception as exc:
            self.errors += 1
            self.last_error_code = type(exc).__name__
            logger.exception(
                "open-song worker cycle failed",
                execution_id=claim.execution_id,
            )
            try:
                await self._review(
                    claim,
                    code="open_song_worker_unexpected_failure",
                    metadata={"error_type": type(exc).__name__},
                )
            except AudioSongExecutionError:
                logger.exception(
                    "open-song worker could not persist unexpected review state",
                    execution_id=claim.execution_id,
                )
            self.write_health("needs_review")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.poll_seconds)


def healthcheck() -> int:
    path = Path(settings.AUDIO_SONG_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        status = str(payload.get("status") or "")
        return (
            0
            if status
            in {"healthy", "disabled", "degraded", "needs_review", "starting"}
            and age <= _HEALTH_MAX_AGE_SECONDS
            else 1
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


async def _main() -> None:
    setup_logging()
    worker = AudioSongWorker()
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
