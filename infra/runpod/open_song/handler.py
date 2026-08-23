"""Isolated RunPod handler for one ACE-Step song plus four Demucs stems.

No request text, credential, local path, object key, or presigned URL is logged.
The AIONEX Backend remains the durable authority and performs all cost approval,
job reconciliation, final mix/master, Studio materialization, and public evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit
import urllib.error
import urllib.request

from contract import (
    HandlerSongRequest,
    OpenSongHandlerContractError,
    REQUIRED_STEMS,
    canonicalize_command,
    demucs_command,
    inspect_wav,
    parse_query_response,
    parse_release_response,
    provider_result,
)

_MAX_HTTP_BYTES = 536_870_912
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{4,240}$")
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


class OpenSongHandlerRuntimeError(RuntimeError):
    """The isolated runtime could not complete a bounded operation."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise OpenSongHandlerRuntimeError(f"{name} is invalid") from exc
    if not minimum <= value <= maximum:
        raise OpenSongHandlerRuntimeError(f"{name} is invalid")
    return value


def _required_env(name: str, *, maximum: int = 4_096) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value or len(value) > maximum or "\x00" in value:
        raise OpenSongHandlerRuntimeError(f"{name} is unavailable")
    return value


def _json_request(
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: int,
    max_bytes: int = 2_000_000,
) -> Mapping[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **dict(headers or {}),
        },
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise OpenSongHandlerRuntimeError("local ACE-Step response is oversized")
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise OpenSongHandlerRuntimeError("local ACE-Step request failed") from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenSongHandlerRuntimeError("local ACE-Step response is invalid") from exc
    if not isinstance(document, Mapping):
        raise OpenSongHandlerRuntimeError("local ACE-Step response is invalid")
    return document


def _download_local_audio(
    url: str,
    *,
    api_root: str,
    headers: Mapping[str, str],
    timeout_seconds: int,
) -> bytes:
    absolute = urljoin(api_root.rstrip("/") + "/", url)
    target = urlsplit(absolute)
    root = urlsplit(api_root)
    if (
        target.scheme != "http"
        or target.hostname not in {"127.0.0.1", "localhost"}
        or target.hostname != root.hostname
        or target.port != root.port
        or target.username is not None
        or target.password is not None
    ):
        raise OpenSongHandlerRuntimeError("ACE-Step output locator escaped localhost")
    request = urllib.request.Request(
        absolute,
        headers={"Accept": "application/octet-stream", **dict(headers)},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(_MAX_HTTP_BYTES + 1)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise OpenSongHandlerRuntimeError("ACE-Step audio download failed") from exc
    if len(body) < 44 or len(body) > _MAX_HTTP_BYTES:
        raise OpenSongHandlerRuntimeError("ACE-Step audio size is invalid")
    return body


def _run_command(command: list[str], *, timeout_seconds: int) -> None:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OpenSongHandlerRuntimeError("isolated audio command failed") from exc
    if completed.returncode != 0:
        raise OpenSongHandlerRuntimeError("isolated audio command was rejected")


class AceStepLocalService:
    """One private localhost ACE-Step API process per warm RunPod worker."""

    def __init__(self) -> None:
        self.port = _positive_int("AIONEX_ACESTEP_PORT", 18_080, 1_024, 65_535)
        self.api_root = f"http://127.0.0.1:{self.port}"
        self.token = secrets.token_urlsafe(48)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _healthy(self) -> bool:
        try:
            document = _json_request(
                "GET",
                f"{self.api_root}/health",
                headers=self.headers,
                timeout_seconds=5,
                max_bytes=100_000,
            )
            return bool(document)
        except OpenSongHandlerRuntimeError:
            return False

    def ensure_started(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self._healthy():
                return
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
            environment = {
                **os.environ,
                "ACESTEP_API_KEY": self.token,
                "ACESTEP_API_HOST": "127.0.0.1",
                "ACESTEP_API_PORT": str(self.port),
                "ACESTEP_QUEUE_WORKERS": "1",
                "ACESTEP_QUEUE_MAXSIZE": "1",
                "ACESTEP_CONFIG_PATH": "acestep-v15-base",
                "ACESTEP_LM_MODEL_PATH": "acestep-5Hz-lm-4B",
                "ACESTEP_LLM_BACKEND": "pt",
                "ACESTEP_INIT_SERVICE": "true",
                "ACESTEP_CHECKPOINTS_DIR": "/app/checkpoints",
                "ACESTEP_PROJECT_ROOT": "/app",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
            try:
                self._process = subprocess.Popen(
                    [
                        "acestep-api",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(self.port),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                )
            except OSError as exc:
                raise OpenSongHandlerRuntimeError("ACE-Step API could not start") from exc
            deadline = time.monotonic() + _positive_int(
                "AIONEX_ACESTEP_STARTUP_TIMEOUT_SECONDS", 600, 30, 1_800
            )
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise OpenSongHandlerRuntimeError("ACE-Step API exited during startup")
                if self._healthy():
                    return
                time.sleep(2)
            self._process.terminate()
            raise OpenSongHandlerRuntimeError("ACE-Step API startup timed out")

    def generate(self, request: HandlerSongRequest, workdir: Path) -> Path:
        self.ensure_started()
        submitted = _json_request(
            "POST",
            f"{self.api_root}/release_task",
            payload=request.ace_step_api_payload(),
            headers=self.headers,
            timeout_seconds=30,
        )
        task_id = parse_release_response(submitted)
        deadline = time.monotonic() + _positive_int(
            "AIONEX_ACESTEP_GENERATION_TIMEOUT_SECONDS", 900, 60, 1_800
        )
        locator: str | None = None
        while time.monotonic() < deadline:
            document = _json_request(
                "POST",
                f"{self.api_root}/query_result",
                payload={"task_id_list": json.dumps([task_id])},
                headers=self.headers,
                timeout_seconds=30,
            )
            status, locator = parse_query_response(document)
            if status == "failed":
                raise OpenSongHandlerRuntimeError("ACE-Step generation failed")
            if status == "completed" and locator:
                break
            time.sleep(2)
        if not locator:
            raise OpenSongHandlerRuntimeError("ACE-Step generation timed out")
        provider_body = _download_local_audio(
            locator,
            api_root=self.api_root,
            headers=self.headers,
            timeout_seconds=180,
        )
        raw_path = workdir / "ace-step-output.bin"
        raw_path.write_bytes(provider_body)
        canonical_path = workdir / "song.wav"
        _run_command(
            canonicalize_command(raw_path, canonical_path), timeout_seconds=180
        )
        inspect_wav(canonical_path)
        return canonical_path


class S3ArtifactPublisher:
    """Publish private artifacts and return short-lived HTTPS GET URLs."""

    def __init__(self) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
            from botocore.config import Config  # type: ignore[import-untyped]
        except ImportError as exc:
            raise OpenSongHandlerRuntimeError("artifact publisher is unavailable") from exc
        self.bucket = _required_env("AIONEX_ARTIFACT_S3_BUCKET", maximum=255)
        self.region = _required_env("AIONEX_ARTIFACT_S3_REGION", maximum=100)
        access_key = _required_env("AIONEX_ARTIFACT_S3_ACCESS_KEY_ID", maximum=512)
        secret_key = _required_env("AIONEX_ARTIFACT_S3_SECRET_ACCESS_KEY", maximum=1_024)
        endpoint = str(os.getenv("AIONEX_ARTIFACT_S3_ENDPOINT_URL") or "").strip() or None
        self.prefix = str(
            os.getenv("AIONEX_ARTIFACT_PREFIX") or "aionex/open-song"
        ).strip("/")
        self.ttl_seconds = _positive_int(
            "AIONEX_ARTIFACT_URL_TTL_SECONDS", 1_800, 300, 3_600
        )
        hosts = {
            item.strip().lower().rstrip(".")
            for item in _required_env(
                "AIONEX_ARTIFACT_ALLOWED_HOSTS", maximum=4_096
            ).split(",")
            if item.strip()
        }
        if not hosts or any(not _HOST_RE.fullmatch(item) for item in hosts):
            raise OpenSongHandlerRuntimeError("artifact host allowlist is invalid")
        self.allowed_hosts = frozenset(hosts)
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=self.region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )

    def publish(self, path: Path, *, job_scope: str, logical_key: str) -> dict[str, Any]:
        evidence = inspect_wav(path)
        key = (
            f"{self.prefix}/{job_scope}/{logical_key}/"
            f"{evidence.sha256[:24]}.wav"
        )
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=path.read_bytes(),
                ContentType="audio/wav",
                ServerSideEncryption="AES256",
                Metadata={
                    "sha256": evidence.sha256,
                    "lifecycle-required": "true",
                    "ai-generated": "true",
                },
            )
            url = str(
                self.client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=self.ttl_seconds,
                )
            )
        except Exception as exc:
            raise OpenSongHandlerRuntimeError("artifact publication failed") from exc
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or host not in self.allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise OpenSongHandlerRuntimeError("artifact URL is outside the allowlist")
        return {"url": url, **evidence.public_snapshot()}


_service = AceStepLocalService()


def _safe_job_scope(value: object) -> str:
    job_id = str(value or "").strip()
    if _JOB_ID_RE.fullmatch(job_id):
        return hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:32]
    return secrets.token_hex(16)


def _separate(song: Path, workdir: Path) -> dict[str, Path]:
    demucs_root = workdir / "demucs"
    _run_command(
        demucs_command(song, demucs_root),
        timeout_seconds=_positive_int(
            "AIONEX_DEMUCS_TIMEOUT_SECONDS", 600, 60, 1_800
        ),
    )
    canonical_root = workdir / "canonical-stems"
    canonical_root.mkdir(mode=0o700)
    result: dict[str, Path] = {}
    for stem in REQUIRED_STEMS:
        candidates = list(demucs_root.rglob(f"{stem}.wav"))
        if len(candidates) != 1:
            raise OpenSongHandlerRuntimeError("Demucs stem result is incomplete")
        target = canonical_root / f"{stem}.wav"
        _run_command(
            canonicalize_command(candidates[0], target), timeout_seconds=180
        )
        inspect_wav(target)
        result[stem] = target
    return result


def handler(event: Mapping[str, Any]) -> dict[str, Any]:
    try:
        raw_input = event.get("input")
        if not isinstance(raw_input, Mapping):
            raise OpenSongHandlerContractError("RunPod input is invalid")
        image_digest = _required_env("AIONEX_HANDLER_IMAGE_DIGEST", maximum=71).lower()
        request = HandlerSongRequest.from_payload(
            raw_input,
            expected_image_digest=image_digest,
        )
        publisher = S3ArtifactPublisher()
        job_scope = _safe_job_scope(event.get("id"))
        with tempfile.TemporaryDirectory(prefix="aionex-open-song-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            full_song = _service.generate(request, root)
            stems = _separate(full_song, root)
            full_evidence = inspect_wav(full_song)
            stem_evidence = {name: inspect_wav(path) for name, path in stems.items()}
            if any(
                abs(item.duration_seconds - full_evidence.duration_seconds) > 0.05
                for item in stem_evidence.values()
            ):
                raise OpenSongHandlerRuntimeError("stem durations are inconsistent")
            published_song = publisher.publish(
                full_song, job_scope=job_scope, logical_key="song"
            )
            published_stems = {
                stem: publisher.publish(
                    stems[stem], job_scope=job_scope, logical_key=f"stem-{stem}"
                )
                for stem in REQUIRED_STEMS
            }
            return provider_result(
                image_digest=image_digest,
                full_song=published_song,
                stems=published_stems,
            )
    except (OpenSongHandlerContractError, OpenSongHandlerRuntimeError) as exc:
        raise RuntimeError(f"open_song_handler_failed:{type(exc).__name__}") from None
    except Exception:
        raise RuntimeError("open_song_handler_failed:unexpected") from None


def main() -> None:
    try:
        import runpod  # type: ignore[import-untyped]
    except ImportError as exc:
        raise OpenSongHandlerRuntimeError("RunPod runtime is unavailable") from exc
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
