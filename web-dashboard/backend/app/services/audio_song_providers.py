"""Phase 36G Stage 8 exact open-song provider transports.

This module owns network shape validation only. Durable authority, tenant scope,
arm-before-spend, lease/fencing, storage, and final Media DAG transitions live in
``audio_song_runtime`` and ``audio_song_worker``. Submission is attempted once;
transport uncertainty after the boundary is always reported as ambiguous.
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

_RUNPOD_API_ROOT = "https://api.runpod.ai/v2"
_RUNPOD_STATES = frozenset(
    {"IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
)
_REQUIRED_STEMS = ("vocals", "drums", "bass", "other")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9_-]{6,160}$")
_JOB_RE = re.compile(r"^[A-Za-z0-9._:-]{4,240}$")
_ALLOWED_AUDIO_TYPES = frozenset({"audio/wav", "audio/x-wav", "application/octet-stream"})


class AudioSongProviderFailure(RuntimeError):
    """Sanitized provider failure with explicit retry/ambiguity semantics."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        message: str = "Open-song provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)
        self.ambiguous_submission = bool(ambiguous_submission)
        self.http_status = http_status
        self.metadata = _safe_metadata(metadata)


@dataclass(frozen=True, slots=True)
class ProviderOpenSongRequest:
    route_id: str
    model: str
    model_revision: str
    language_model: str
    language_model_revision: str
    source_commit: str
    container_image_digest: str
    separation_model: str
    separation_source_commit: str
    separation_checkpoint_sha256: str
    title: str
    concept: str
    lyrics: str
    language: str
    duration_seconds: int
    bpm: int
    musical_key: str
    time_signature: int
    seed: int

    def __post_init__(self) -> None:
        if self.route_id != "runpod-flex-a40":
            raise AudioSongProviderFailure(
                "provider_route_unsupported", retryable=False
            )
        for label, value in (
            ("model revision", self.model_revision),
            ("language model revision", self.language_model_revision),
            ("source revision", self.source_commit),
            ("separation source revision", self.separation_source_commit),
        ):
            if not _REVISION_RE.fullmatch(str(value).strip().lower()):
                raise AudioSongProviderFailure(
                    "provider_input_invalid",
                    retryable=False,
                    metadata={"field": label},
                )
        if not _IMAGE_DIGEST_RE.fullmatch(self.container_image_digest.strip().lower()):
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "container_image_digest"},
            )
        if not _SHA256_RE.fullmatch(self.separation_checkpoint_sha256.strip().lower()):
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "separation_checkpoint_sha256"},
            )
        for label, value, minimum, maximum in (
            ("model", self.model, 3, 160),
            ("language_model", self.language_model, 3, 160),
            ("separation_model", self.separation_model, 3, 80),
            ("title", self.title, 3, 160),
            ("concept", self.concept, 20, 1_000),
            ("lyrics", self.lyrics, 40, 8_000),
            ("language", self.language, 2, 24),
            ("musical_key", self.musical_key, 1, 16),
        ):
            text = str(value).strip()
            if not minimum <= len(text) <= maximum or "\x00" in text:
                raise AudioSongProviderFailure(
                    "provider_input_invalid",
                    retryable=False,
                    metadata={"field": label},
                )
        if not 15 <= int(self.duration_seconds) <= 180:
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "duration_seconds"},
            )
        if not 40 <= int(self.bpm) <= 220:
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "bpm"},
            )
        if int(self.time_signature) not in {2, 3, 4, 6}:
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "time_signature"},
            )
        if not 0 <= int(self.seed) <= 2_147_483_647:
            raise AudioSongProviderFailure(
                "provider_input_invalid",
                retryable=False,
                metadata={"field": "seed"},
            )

    def provider_payload(self) -> dict[str, Any]:
        return {
            "schema": "aionex.open-song-request.v1",
            "route_id": self.route_id,
            "model": self.model,
            "model_revision": self.model_revision,
            "language_model": self.language_model,
            "language_model_revision": self.language_model_revision,
            "source_commit": self.source_commit,
            "container_image_digest": self.container_image_digest,
            "separation": {
                "model": self.separation_model,
                "source_commit": self.separation_source_commit,
                "checkpoint_sha256": self.separation_checkpoint_sha256,
                "stems": list(_REQUIRED_STEMS),
            },
            "song": {
                "title": self.title,
                "concept": self.concept,
                "lyrics": self.lyrics,
                "language": self.language,
                "duration_seconds": int(self.duration_seconds),
                "bpm": int(self.bpm),
                "musical_key": self.musical_key,
                "time_signature": int(self.time_signature),
                "seed": int(self.seed),
            },
            "output": {
                "media_type": "audio/wav",
                "sample_rate_hz": 48_000,
                "channels": 2,
                "stems": list(_REQUIRED_STEMS),
            },
            "safety": {
                "max_attempts": 1,
                "automatic_retry": False,
                "automatic_cross_provider_fallback": False,
                "known_person_voice": False,
                "voice_clone": False,
                "voice_transformation": False,
                "ai_generated_disclosure_required": True,
            },
        }


@dataclass(frozen=True, slots=True)
class ProviderAudioArtifact:
    url: str
    sha256: str
    size_bytes: int
    media_type: str
    duration_seconds: float
    sample_rate_hz: int
    channels: int

    def __post_init__(self) -> None:
        if not _SHA256_RE.fullmatch(self.sha256):
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if not 1 <= int(self.size_bytes) <= 2_147_483_647:
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if self.media_type != "audio/wav":
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if not 0 < float(self.duration_seconds) <= 190:
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if int(self.sample_rate_hz) != 48_000 or int(self.channels) != 2:
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        _validate_artifact_url(self.url, allowed_hosts=None)

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "duration_seconds": self.duration_seconds,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "storage_locator_returned": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderOpenSongResult:
    schema: str
    source_commit: str
    model_revision: str
    language_model_revision: str
    container_image_digest: str
    separation_source_commit: str
    separation_checkpoint_sha256: str
    full_song: ProviderAudioArtifact
    stems: dict[str, ProviderAudioArtifact]

    def __post_init__(self) -> None:
        if self.schema != "aionex.open-song-provider-result.v1":
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if set(self.stems) != set(_REQUIRED_STEMS):
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        for revision in (
            self.source_commit,
            self.model_revision,
            self.language_model_revision,
            self.separation_source_commit,
        ):
            if not _REVISION_RE.fullmatch(revision):
                raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if not _IMAGE_DIGEST_RE.fullmatch(self.container_image_digest):
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        if not _SHA256_RE.fullmatch(self.separation_checkpoint_sha256):
            raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
        duration = self.full_song.duration_seconds
        for artifact in self.stems.values():
            if abs(artifact.duration_seconds - duration) > 0.05:
                raise AudioSongProviderFailure("provider_result_invalid", retryable=False)

    def evidence_snapshot(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_commit": self.source_commit,
            "model_revision": self.model_revision,
            "language_model_revision": self.language_model_revision,
            "container_image_digest": self.container_image_digest,
            "separation_source_commit": self.separation_source_commit,
            "separation_checkpoint_sha256": self.separation_checkpoint_sha256,
            "stems": list(_REQUIRED_STEMS),
            "raw_title_returned": False,
            "raw_concept_returned": False,
            "raw_lyrics_returned": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderOpenSongJob:
    job_id: str
    state: str
    execution_time_ms: int | None
    result: ProviderOpenSongResult | None
    metadata: dict[str, Any]

    @property
    def billed_seconds(self) -> float | None:
        if self.execution_time_ms is None:
            return None
        return float(math.ceil(self.execution_time_ms / 1_000))


@dataclass(frozen=True, slots=True)
class ProviderDownloadedArtifact:
    body: bytes
    media_type: str
    sha256: str


def _safe_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).strip().lower().replace("-", "_")
        if normalized in {
            "id",
            "status",
            "delaytime",
            "executiontime",
            "http_status",
            "error_code",
            "error_type",
            "field",
            "candidate_count",
        } and isinstance(item, (str, int, float, bool)):
            safe[normalized[:80]] = str(item)[:240] if isinstance(item, str) else item
    return safe


def _safe_error_metadata(response: httpx.Response) -> dict[str, Any]:
    metadata: dict[str, Any] = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return metadata
    if not isinstance(payload, dict):
        return metadata
    error = payload.get("error")
    if isinstance(error, str):
        metadata["error_type"] = error[:160]
    elif isinstance(error, dict):
        for key in ("code", "type"):
            value = error.get(key)
            if isinstance(value, (str, int, float, bool)):
                metadata[f"error_{key}"] = str(value)[:160]
    return metadata


def _failure_for_response(
    response: httpx.Response,
    *,
    submission: bool,
) -> AudioSongProviderFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {400, 401, 402, 403, 404, 409, 413, 415, 422}:
        code = (
            "provider_auth"
            if status in {401, 403}
            else "provider_billing"
            if status == 402
            else "provider_request"
        )
        return AudioSongProviderFailure(
            code,
            retryable=False,
            http_status=status,
            metadata=metadata,
        )
    if status == 429:
        return AudioSongProviderFailure(
            "provider_rate_limited",
            retryable=not submission,
            ambiguous_submission=submission,
            http_status=status,
            metadata=metadata,
        )
    if status >= 500:
        return AudioSongProviderFailure(
            "provider_submission_ambiguous" if submission else "provider_unavailable",
            retryable=not submission,
            ambiguous_submission=submission,
            http_status=status,
            metadata=metadata,
        )
    return AudioSongProviderFailure(
        "provider_response",
        retryable=False,
        ambiguous_submission=submission,
        http_status=status,
        metadata=metadata,
    )


def _credential(value: str) -> str:
    token = value.strip()
    if not 16 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise AudioSongProviderFailure("provider_unconfigured", retryable=False)
    return token


def _endpoint(value: str) -> str:
    endpoint_id = value.strip()
    if not _ENDPOINT_RE.fullmatch(endpoint_id):
        raise AudioSongProviderFailure("provider_unconfigured", retryable=False)
    return endpoint_id


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return parsed if math.isfinite(parsed) else None


def _validate_artifact_url(
    value: str,
    *,
    allowed_hosts: frozenset[str] | None,
) -> str:
    url = value.strip()
    if not 12 <= len(url) <= 4_096:
        raise AudioSongProviderFailure("provider_artifact_url", retryable=False)
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise AudioSongProviderFailure("provider_artifact_url", retryable=False)
    try:
        parsed_ip = ipaddress.ip_address(hostname)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        raise AudioSongProviderFailure("provider_artifact_url", retryable=False)
    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise AudioSongProviderFailure(
            "provider_artifact_host",
            retryable=False,
            metadata={"field": hostname[:160]},
        )
    return url


def _parse_artifact(value: Any) -> ProviderAudioArtifact:
    if not isinstance(value, dict):
        raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
    url = str(value.get("url") or "").strip()
    checksum = str(value.get("sha256") or "").strip().lower()
    media_type = str(value.get("media_type") or "").split(";", 1)[0].strip().lower()
    size = _parse_int(value.get("size_bytes"))
    duration = _parse_float(value.get("duration_seconds"))
    sample_rate = _parse_int(value.get("sample_rate_hz"))
    channels = _parse_int(value.get("channels"))
    if (
        size is None
        or duration is None
        or sample_rate is None
        or channels is None
    ):
        raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
    return ProviderAudioArtifact(
        url=url,
        sha256=checksum,
        size_bytes=int(size),
        media_type=media_type,
        duration_seconds=float(duration),
        sample_rate_hz=int(sample_rate),
        channels=int(channels),
    )


def _parse_result(value: Any) -> ProviderOpenSongResult:
    if not isinstance(value, dict):
        raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
    raw_stems = value.get("stems")
    if not isinstance(raw_stems, dict):
        raise AudioSongProviderFailure("provider_result_invalid", retryable=False)
    stems = {stem: _parse_artifact(raw_stems.get(stem)) for stem in _REQUIRED_STEMS}
    return ProviderOpenSongResult(
        schema=str(value.get("schema") or "").strip(),
        source_commit=str(value.get("source_commit") or "").strip().lower(),
        model_revision=str(value.get("model_revision") or "").strip().lower(),
        language_model_revision=str(
            value.get("language_model_revision") or ""
        ).strip().lower(),
        container_image_digest=str(
            value.get("container_image_digest") or ""
        ).strip().lower(),
        separation_source_commit=str(
            value.get("separation_source_commit") or ""
        ).strip().lower(),
        separation_checkpoint_sha256=str(
            value.get("separation_checkpoint_sha256") or ""
        ).strip().lower(),
        full_song=_parse_artifact(value.get("full_song")),
        stems=stems,
    )


def _parse_job(value: Any, *, expected_job_id: str | None = None) -> ProviderOpenSongJob:
    if not isinstance(value, dict):
        raise AudioSongProviderFailure("provider_response", retryable=False)
    job_id = str(value.get("id") or "").strip()
    state = str(value.get("status") or "").strip().upper()
    if not _JOB_RE.fullmatch(job_id) or state not in _RUNPOD_STATES:
        raise AudioSongProviderFailure("provider_response", retryable=False)
    if expected_job_id is not None and job_id != expected_job_id:
        raise AudioSongProviderFailure("provider_job_identity", retryable=False)
    execution_time = _parse_int(value.get("executionTime"))
    if execution_time is not None and not 0 <= execution_time <= 86_400_000:
        raise AudioSongProviderFailure("provider_response", retryable=False)
    result = _parse_result(value.get("output")) if state == "COMPLETED" else None
    metadata: dict[str, Any] = {"status": state}
    for source, destination in (("delayTime", "delaytime"), ("executionTime", "executiontime")):
        parsed = _parse_int(value.get(source))
        if parsed is not None:
            metadata[destination] = parsed
    error = value.get("error")
    if isinstance(error, str) and error:
        metadata["error_type"] = error[:160]
    return ProviderOpenSongJob(
        job_id=job_id,
        state=state,
        execution_time_ms=execution_time,
        result=result,
        metadata=metadata,
    )


class RunPodOpenSongAdapter:
    """One-shot RunPod Serverless transport for the AIONEX handler contract."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        poll_timeout_seconds: float = 30.0,
        download_timeout_seconds: float = 180.0,
        max_content_bytes: int = 256 * 1024 * 1024,
        allowed_artifact_hosts: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        hosts = frozenset(
            host.strip().lower().rstrip(".")
            for host in allowed_artifact_hosts
            if host.strip()
        )
        if not hosts:
            raise AudioSongProviderFailure("provider_unconfigured", retryable=False)
        if any("/" in host or ":" in host or " " in host for host in hosts):
            raise AudioSongProviderFailure("provider_unconfigured", retryable=False)
        self.transport = transport
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 300.0))
        self.poll_timeout_seconds = max(5.0, min(float(poll_timeout_seconds), 120.0))
        self.download_timeout_seconds = max(
            10.0, min(float(download_timeout_seconds), 600.0)
        )
        self.max_content_bytes = max(1_048_576, min(int(max_content_bytes), 536_870_912))
        self.allowed_artifact_hosts = hosts

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_credential(credential)}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def submit(
        self,
        request: ProviderOpenSongRequest,
        *,
        credential: str,
        endpoint_id: str,
    ) -> ProviderOpenSongJob:
        endpoint = _endpoint(endpoint_id)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{_RUNPOD_API_ROOT}/{endpoint}/run",
                    headers=self._headers(credential),
                    json={"input": request.provider_payload()},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AudioSongProviderFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=True)
        try:
            return _parse_job(response.json())
        except (ValueError, AudioSongProviderFailure) as exc:
            raise AudioSongProviderFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc

    async def retrieve(
        self,
        job_id: str,
        *,
        credential: str,
        endpoint_id: str,
    ) -> ProviderOpenSongJob:
        endpoint = _endpoint(endpoint_id)
        normalized_job_id = job_id.strip()
        if not _JOB_RE.fullmatch(normalized_job_id):
            raise AudioSongProviderFailure("provider_job_invalid", retryable=False)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.poll_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{_RUNPOD_API_ROOT}/{endpoint}/status/{normalized_job_id}",
                    headers=self._headers(credential),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AudioSongProviderFailure(
                "provider_poll_transport", retryable=True
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response, submission=False)
        try:
            return _parse_job(response.json(), expected_job_id=normalized_job_id)
        except ValueError as exc:
            raise AudioSongProviderFailure("provider_response", retryable=False) from exc

    async def download(
        self,
        artifact: ProviderAudioArtifact,
    ) -> ProviderDownloadedArtifact:
        url = _validate_artifact_url(
            artifact.url,
            allowed_hosts=self.allowed_artifact_hosts,
        )
        declared_limit = min(artifact.size_bytes, self.max_content_bytes)
        if artifact.size_bytes > self.max_content_bytes:
            raise AudioSongProviderFailure(
                "provider_content_too_large", retryable=False
            )
        chunks: list[bytes] = []
        total = 0
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.download_timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "audio/wav"},
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure_for_response(response, submission=False)
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    if content_type not in _ALLOWED_AUDIO_TYPES:
                        raise AudioSongProviderFailure(
                            "provider_content_type", retryable=False
                        )
                    content_length = _parse_int(response.headers.get("content-length"))
                    if content_length is not None and content_length != artifact.size_bytes:
                        raise AudioSongProviderFailure(
                            "provider_content_length", retryable=False
                        )
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > declared_limit:
                            raise AudioSongProviderFailure(
                                "provider_content_too_large", retryable=False
                            )
                        chunks.append(chunk)
        except AudioSongProviderFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AudioSongProviderFailure(
                "provider_download_transport", retryable=True
            ) from exc
        body = b"".join(chunks)
        if len(body) != artifact.size_bytes:
            raise AudioSongProviderFailure("provider_content_length", retryable=False)
        digest = hashlib.sha256(body).hexdigest()
        if digest != artifact.sha256:
            raise AudioSongProviderFailure("provider_content_checksum", retryable=False)
        return ProviderDownloadedArtifact(
            body=body,
            media_type="audio/wav",
            sha256=digest,
        )
