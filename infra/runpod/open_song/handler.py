"""Isolated RunPod handler for one ACE-Step song plus four Demucs stems.

No request text, credential, local path, object key, or presigned URL is logged.
The AIONEX Backend remains the durable authority and performs all cost approval,
job reconciliation, final mix/master, Studio materialization, and public evidence.
"""
from __future__ import annotations

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


def _run_command(
    command: list[str],
    *,
    timeout_seconds: int,
    failure_message: str = "isolated audio command failed",
) -> None:
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
        raise OpenSongHandlerRuntimeError(failure_message) from exc
    if completed.returncode != 0:
        raise OpenSongHandlerRuntimeError(failure_message)


def _ace_step_health_ready(document: Mapping[str, Any]) -> bool:
    """Require the exact ACE-Step model pair before accepting localhost readiness."""
    if document.get("code") != 200 or document.get("error") not in {None, ""}:
        return False
    data = document.get("data")
    if not isinstance(data, Mapping):
        return False
    return (
        data.get("status") == "ok"
        and data.get("service") == "ACE-Step API"
        and data.get("models_initialized") is True
        and data.get("llm_initialized") is True
        and data.get("loaded_model") == "acestep-v15-base"
        and data.get("loaded_lm_model") == "acestep-5Hz-lm-4B"
    )


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
            return _ace_step_health_ready(document)
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
                "ACESTEP_LM_BACKEND": "pt",
                "ACESTEP_NO_INIT": "false",
                "ACESTEP_INIT_LLM": "true",
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
            canonicalize_command(raw_path, canonical_path),
            timeout_seconds=180,
            failure_message="ACE-Step canonicalization failed",
        )
        inspect_wav(canonical_path)
        return canonical_path


class AionexArtifactBridgePublisher:
    """Upload artifacts only to bounded, one-time AIONEX ingress grants."""

    _ARTIFACT_ID_RE = re.compile(r"^[0-9a-f]{48}$")
    _TOKEN_RE = re.compile(r"^[0-9]{10}:[0-9a-f]{64}$")
    _LOGICAL_KEYS = ("full_song", *REQUIRED_STEMS)

    def __init__(self, raw_input: Mapping[str, Any]) -> None:
        bridge = raw_input.get("artifact_bridge")
        if not isinstance(bridge, Mapping):
            raise OpenSongHandlerRuntimeError("artifact bridge is missing")
        if bridge.get("schema") != "aionex.open-song-artifact-bridge.v1":
            raise OpenSongHandlerRuntimeError("artifact bridge schema is invalid")
        artifacts = bridge.get("artifacts")
        if not isinstance(artifacts, Mapping) or set(artifacts) != set(self._LOGICAL_KEYS):
            raise OpenSongHandlerRuntimeError("artifact bridge targets are incomplete")
        expected_host = _required_env(
            "AIONEX_ARTIFACT_BRIDGE_ALLOWED_HOST", maximum=253
        ).lower().rstrip(".")
        if not _HOST_RE.fullmatch(expected_host):
            raise OpenSongHandlerRuntimeError("artifact bridge host is invalid")
        targets: dict[str, tuple[str, str, str]] = {}
        for logical_key in self._LOGICAL_KEYS:
            raw = artifacts.get(logical_key)
            if not isinstance(raw, Mapping) or set(raw) != {
                "artifact_id", "upload_url", "upload_token"
            }:
                raise OpenSongHandlerRuntimeError("artifact bridge target is invalid")
            artifact_id = str(raw.get("artifact_id") or "").strip()
            upload_url = str(raw.get("upload_url") or "").strip()
            upload_token = str(raw.get("upload_token") or "").strip()
            if not self._ARTIFACT_ID_RE.fullmatch(artifact_id):
                raise OpenSongHandlerRuntimeError("artifact identifier is invalid")
            if not self._TOKEN_RE.fullmatch(upload_token):
                raise OpenSongHandlerRuntimeError("artifact upload grant is invalid")
            parsed = urlsplit(upload_url)
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").lower().rstrip(".") != expected_host
                or parsed.port not in {None, 443}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path != f"/api/v1/audio-song-artifacts/{artifact_id}"
            ):
                raise OpenSongHandlerRuntimeError("artifact upload URL is invalid")
            targets[logical_key] = (artifact_id, upload_url, upload_token)
        self.targets = targets

    def publish(self, path: Path, *, logical_key: str) -> dict[str, Any]:
        if logical_key not in self.targets:
            raise OpenSongHandlerRuntimeError("artifact logical key is invalid")
        evidence = inspect_wav(path)
        artifact_id, upload_url, upload_token = self.targets[logical_key]
        body = path.read_bytes()
        if len(body) != evidence.size_bytes:
            raise OpenSongHandlerRuntimeError("artifact evidence changed before upload")
        request = urllib.request.Request(
            upload_url,
            data=body,
            headers={
                "Authorization": f"Bearer {upload_token}",
                "Content-Type": "audio/wav",
                "Accept": "application/json",
                "X-AIONEX-Artifact-SHA256": evidence.sha256,
                "X-AIONEX-Artifact-Size": str(evidence.size_bytes),
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=180) as response:
                status = int(getattr(response, "status", 0))
                response.read(65_536)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise OpenSongHandlerRuntimeError("artifact bridge upload failed") from exc
        if status != 201:
            raise OpenSongHandlerRuntimeError("artifact bridge upload failed")
        return {"artifact_id": artifact_id, **evidence.public_snapshot()}


_service = AceStepLocalService()


_SAFE_RUNTIME_FAILURE_CODES = {
    "ACE-Step API could not start": "acestep_api_start_failed",
    "ACE-Step API exited during startup": "acestep_api_startup_exit",
    "ACE-Step API startup timed out": "acestep_api_startup_timeout",
    "local ACE-Step request failed": "acestep_api_request_failed",
    "local ACE-Step response is invalid": "acestep_api_response_invalid",
    "local ACE-Step response is oversized": "acestep_api_response_oversized",
    "ACE-Step generation failed": "acestep_generation_failed",
    "ACE-Step generation timed out": "acestep_generation_timeout",
    "ACE-Step audio download failed": "acestep_audio_download_failed",
    "ACE-Step audio size is invalid": "acestep_audio_invalid",
    "ACE-Step output locator escaped localhost": "acestep_output_locator_invalid",
    "ACE-Step canonicalization failed": "acestep_canonicalization_failed",
    "Demucs separation failed": "demucs_separation_failed",
    "Demucs stem result is incomplete": "demucs_stems_incomplete",
    "Demucs stem canonicalization failed": "demucs_canonicalization_failed",
    "stem durations are inconsistent": "demucs_duration_mismatch",
    "artifact bridge is missing": "artifact_bridge_missing",
    "artifact bridge schema is invalid": "artifact_bridge_schema_invalid",
    "artifact bridge targets are incomplete": "artifact_bridge_targets_incomplete",
    "artifact bridge target is invalid": "artifact_bridge_target_invalid",
    "artifact bridge host is invalid": "artifact_bridge_host_invalid",
    "artifact identifier is invalid": "artifact_id_invalid",
    "artifact upload grant is invalid": "artifact_grant_invalid",
    "artifact upload URL is invalid": "artifact_upload_url_invalid",
    "artifact bridge upload failed": "artifact_upload_failed",
    "artifact evidence changed before upload": "artifact_evidence_changed",
}


def _safe_failure_code(exc: Exception) -> str:
    if isinstance(exc, OpenSongHandlerContractError):
        return "contract_invalid"
    message = str(exc)
    if message in _SAFE_RUNTIME_FAILURE_CODES:
        return _SAFE_RUNTIME_FAILURE_CODES[message]
    if message.startswith("AIONEX_") and (
        message.endswith(" is invalid") or message.endswith(" is unavailable")
    ):
        return "runtime_environment_invalid"
    return "runtime_unclassified"


def _separate(song: Path, workdir: Path) -> dict[str, Path]:
    demucs_root = workdir / "demucs"
    _run_command(
        demucs_command(song, demucs_root),
        timeout_seconds=_positive_int(
            "AIONEX_DEMUCS_TIMEOUT_SECONDS", 600, 60, 1_800
        ),
        failure_message="Demucs separation failed",
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
            canonicalize_command(candidates[0], target),
            timeout_seconds=180,
            failure_message="Demucs stem canonicalization failed",
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
        publisher = AionexArtifactBridgePublisher(raw_input)
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
                full_song, logical_key="full_song"
            )
            published_stems = {
                stem: publisher.publish(
                    stems[stem], logical_key=stem
                )
                for stem in REQUIRED_STEMS
            }
            return provider_result(
                image_digest=image_digest,
                full_song=published_song,
                stems=published_stems,
            )
    except (OpenSongHandlerContractError, OpenSongHandlerRuntimeError) as exc:
        code = _safe_failure_code(exc)
        print(json.dumps({"event": "open_song_failure", "error_code": code}), flush=True)
        return {"error": f"open_song_handler_failed:{code}"}
    except Exception:
        print(json.dumps({"event": "open_song_failure", "error_code": "unexpected"}), flush=True)
        return {"error": "open_song_handler_failed:unexpected"}


def main() -> None:
    try:
        import runpod  # type: ignore[import-untyped]
    except ImportError as exc:
        raise OpenSongHandlerRuntimeError("RunPod runtime is unavailable") from exc
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
