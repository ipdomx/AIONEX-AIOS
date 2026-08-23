"""Pure contracts for the isolated AIONEX ACE-Step open-song handler."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
import wave

REQUEST_SCHEMA = "aionex.open-song-request.v1"
RESULT_SCHEMA = "aionex.open-song-provider-result.v1"
ACE_STEP_SOURCE_COMMIT = "dce621408bee8c31b4fcf4811682eb9359e1bc94"
ACE_STEP_MODEL = "acestep-v15-base"
ACE_STEP_MODEL_REVISION = "e432212fec32b8965a14ffa57ae653438d6abd14"
ACE_STEP_LANGUAGE_MODEL = "acestep-5Hz-lm-4B"
ACE_STEP_LANGUAGE_MODEL_REVISION = "0a3ec94b557aea7d508da38b31cfe7341f6ff737"
DEMUCS_MODEL = "htdemucs"
DEMUCS_MODEL_SIGNATURE = "955717e8"
DEMUCS_SOURCE_COMMIT = "ef66d254cd6d558e207eeff2c4b8d053db2e77dd"
DEMUCS_CHECKPOINT_SHA256 = (
    "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
)
REQUIRED_STEMS = ("vocals", "drums", "bass", "other")

_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_KEY_RE = re.compile(r"^[A-G](?:#|b)?(?:m|maj|min)?$")
_FORBIDDEN_IMITATION_RE = re.compile(
    r"\b(?:in\s+the\s+style\s+of|sounds?\s+like|voice\s+of|sing\s+like|"
    r"imitat(?:e|ing|ion)|clone\s+(?:the\s+)?voice|impersonat(?:e|ing|ion))\b",
    re.IGNORECASE,
)


class OpenSongHandlerContractError(ValueError):
    """The isolated handler request or result is unsafe or malformed."""


def _text(value: object, *, label: str, minimum: int, maximum: int) -> str:
    normalized = "\n".join(
        line.rstrip() for line in str(value or "").strip().splitlines()
    ).strip()
    if not minimum <= len(normalized) <= maximum or "\x00" in normalized:
        raise OpenSongHandlerContractError(f"{label} is invalid")
    return normalized


def _integer(value: object, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise OpenSongHandlerContractError(f"{label} is invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise OpenSongHandlerContractError(f"{label} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise OpenSongHandlerContractError(f"{label} is invalid")
    return parsed


@dataclass(frozen=True, slots=True)
class HandlerSongRequest:
    title: str
    concept: str
    lyrics: str
    language: str
    duration_seconds: int
    bpm: int
    musical_key: str
    time_signature: int
    seed: int
    container_image_digest: str

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
        *,
        expected_image_digest: str,
    ) -> "HandlerSongRequest":
        if value.get("schema") != REQUEST_SCHEMA:
            raise OpenSongHandlerContractError("request schema is invalid")
        if value.get("route_id") != "runpod-flex-a40":
            raise OpenSongHandlerContractError("request route is invalid")
        if value.get("model") != ACE_STEP_MODEL:
            raise OpenSongHandlerContractError("ACE-Step model is invalid")
        if value.get("model_revision") != ACE_STEP_MODEL_REVISION:
            raise OpenSongHandlerContractError("ACE-Step model revision is invalid")
        if value.get("language_model") != ACE_STEP_LANGUAGE_MODEL:
            raise OpenSongHandlerContractError("ACE-Step language model is invalid")
        if value.get("language_model_revision") != ACE_STEP_LANGUAGE_MODEL_REVISION:
            raise OpenSongHandlerContractError(
                "ACE-Step language model revision is invalid"
            )
        if value.get("source_commit") != ACE_STEP_SOURCE_COMMIT:
            raise OpenSongHandlerContractError("ACE-Step source commit is invalid")
        image_digest = str(value.get("container_image_digest") or "").lower()
        if (
            not _IMAGE_DIGEST_RE.fullmatch(image_digest)
            or image_digest != expected_image_digest
        ):
            raise OpenSongHandlerContractError("handler image digest is invalid")
        separation = value.get("separation")
        if not isinstance(separation, Mapping):
            raise OpenSongHandlerContractError("separation contract is invalid")
        if separation.get("model") != DEMUCS_MODEL:
            raise OpenSongHandlerContractError("Demucs model is invalid")
        if separation.get("source_commit") != DEMUCS_SOURCE_COMMIT:
            raise OpenSongHandlerContractError("Demucs source commit is invalid")
        if separation.get("checkpoint_sha256") != DEMUCS_CHECKPOINT_SHA256:
            raise OpenSongHandlerContractError("Demucs checkpoint is invalid")
        stems = separation.get("stems")
        if not isinstance(stems, list) or tuple(stems) != REQUIRED_STEMS:
            raise OpenSongHandlerContractError("Demucs stem contract is invalid")
        output = value.get("output")
        if not isinstance(output, Mapping) or (
            output.get("media_type") != "audio/wav"
            or output.get("sample_rate_hz") != 48_000
            or output.get("channels") != 2
            or tuple(output.get("stems") or ()) != REQUIRED_STEMS
        ):
            raise OpenSongHandlerContractError("output contract is invalid")
        safety = value.get("safety")
        if not isinstance(safety, Mapping) or (
            safety.get("max_attempts") != 1
            or safety.get("automatic_retry") is not False
            or safety.get("automatic_cross_provider_fallback") is not False
            or safety.get("known_person_voice") is not False
            or safety.get("voice_clone") is not False
            or safety.get("voice_transformation") is not False
            or safety.get("ai_generated_disclosure_required") is not True
        ):
            raise OpenSongHandlerContractError("safety contract is invalid")
        song = value.get("song")
        if not isinstance(song, Mapping):
            raise OpenSongHandlerContractError("song payload is invalid")
        title = _text(song.get("title"), label="title", minimum=3, maximum=160)
        concept = _text(
            song.get("concept"), label="concept", minimum=20, maximum=1_000
        )
        lyrics = _text(
            song.get("lyrics"), label="lyrics", minimum=40, maximum=8_000
        )
        if _FORBIDDEN_IMITATION_RE.search(f"{title}\n{concept}"):
            raise OpenSongHandlerContractError("artist or identity imitation is forbidden")
        language = str(song.get("language") or "").strip()
        key = str(song.get("musical_key") or "").strip()
        if not _LANGUAGE_RE.fullmatch(language):
            raise OpenSongHandlerContractError("language is invalid")
        if not _KEY_RE.fullmatch(key):
            raise OpenSongHandlerContractError("musical key is invalid")
        return cls(
            title=title,
            concept=concept,
            lyrics=lyrics,
            language=language,
            duration_seconds=_integer(
                song.get("duration_seconds"),
                label="duration",
                minimum=15,
                maximum=180,
            ),
            bpm=_integer(song.get("bpm"), label="BPM", minimum=40, maximum=220),
            musical_key=key,
            time_signature=_integer(
                song.get("time_signature"),
                label="time signature",
                minimum=2,
                maximum=6,
            ),
            seed=_integer(
                song.get("seed"), label="seed", minimum=0, maximum=2_147_483_647
            ),
            container_image_digest=image_digest,
        )

    def ace_step_api_payload(self) -> dict[str, Any]:
        return {
            "prompt": self.concept,
            "lyrics": self.lyrics,
            "thinking": True,
            "sample_mode": False,
            "use_format": False,
            "model": ACE_STEP_MODEL,
            "bpm": self.bpm,
            "key_scale": self.musical_key,
            "time_signature": str(self.time_signature),
            "vocal_language": self.language,
            "inference_steps": 50,
            "guidance_scale": 7.0,
            "use_random_seed": False,
            "seed": str(self.seed),
            "audio_duration": float(self.duration_seconds),
            "batch_size": 1,
            "task_type": "text2music",
            "audio_format": "wav",
            "lm_model_path": ACE_STEP_LANGUAGE_MODEL,
            "lm_backend": "pt",
            "allow_lm_batch": False,
            "get_scores": False,
            "get_lrc": False,
        }


@dataclass(frozen=True, slots=True)
class WavEvidence:
    sha256: str
    size_bytes: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": "audio/wav",
            "duration_seconds": self.duration_seconds,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "storage_locator_returned": False,
        }


def inspect_wav(path: str | Path, *, max_bytes: int = 536_870_912) -> WavEvidence:
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise OpenSongHandlerContractError("WAV artifact is unavailable") from exc
    if size < 44 or size > max_bytes:
        raise OpenSongHandlerContractError("WAV artifact size is invalid")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        with wave.open(str(source), "rb") as reader:
            channels = int(reader.getnchannels())
            sample_rate = int(reader.getframerate())
            sample_width = int(reader.getsampwidth())
            frames = int(reader.getnframes())
            compression = str(reader.getcomptype())
    except (OSError, EOFError, wave.Error) as exc:
        raise OpenSongHandlerContractError("WAV artifact is invalid") from exc
    if (
        compression != "NONE"
        or channels != 2
        or sample_rate != 48_000
        or sample_width not in {2, 3, 4}
        or frames <= 0
    ):
        raise OpenSongHandlerContractError("WAV audio profile is invalid")
    duration = frames / sample_rate
    if not 0 < duration <= 190:
        raise OpenSongHandlerContractError("WAV duration is invalid")
    return WavEvidence(
        sha256=digest.hexdigest(),
        size_bytes=size,
        duration_seconds=round(duration, 6),
        sample_rate_hz=sample_rate,
        channels=channels,
    )


def demucs_command(source: str | Path, output_root: str | Path) -> list[str]:
    return [
        "python",
        "-m",
        "demucs.separate",
        "--device",
        "cuda",
        "--repo",
        "/opt/aionex-demucs-models",
        "--name",
        DEMUCS_MODEL_SIGNATURE,
        "--shifts",
        "1",
        "--overlap",
        "0.1",
        "--out",
        str(Path(output_root)),
        str(Path(source)),
    ]


def canonicalize_command(source: str | Path, target: str | Path) -> list[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(Path(source)),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(Path(target)),
    ]


def parse_release_response(value: Mapping[str, Any]) -> str:
    if value.get("code") != 200 or value.get("error") not in {None, ""}:
        raise OpenSongHandlerContractError("ACE-Step submission was rejected")
    data = value.get("data")
    task_id = data.get("task_id") if isinstance(data, Mapping) else None
    normalized = str(task_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{4,200}", normalized):
        raise OpenSongHandlerContractError("ACE-Step task identity is invalid")
    return normalized


def parse_query_response(value: Mapping[str, Any]) -> tuple[str, str | None]:
    if value.get("code") != 200 or value.get("error") not in {None, ""}:
        raise OpenSongHandlerContractError("ACE-Step query was rejected")
    data = value.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise OpenSongHandlerContractError("ACE-Step query response is invalid")
    item = data[0]
    status = item.get("status")
    if status == 0:
        return "pending", None
    if status == 2:
        return "failed", None
    if status != 1:
        raise OpenSongHandlerContractError("ACE-Step query status is invalid")
    raw_result = item.get("result")
    try:
        result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except json.JSONDecodeError as exc:
        raise OpenSongHandlerContractError("ACE-Step result JSON is invalid") from exc
    if not isinstance(result, list) or not result or not isinstance(result[0], Mapping):
        raise OpenSongHandlerContractError("ACE-Step result is invalid")
    file_value = str(result[0].get("file") or "").strip()
    if not file_value or len(file_value) > 4_096:
        raise OpenSongHandlerContractError("ACE-Step output locator is invalid")
    return "completed", file_value


def provider_result(
    *,
    image_digest: str,
    full_song: Mapping[str, Any],
    stems: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not _IMAGE_DIGEST_RE.fullmatch(image_digest):
        raise OpenSongHandlerContractError("handler image digest is invalid")
    if set(stems) != set(REQUIRED_STEMS):
        raise OpenSongHandlerContractError("stem result is incomplete")
    return {
        "schema": RESULT_SCHEMA,
        "source_commit": ACE_STEP_SOURCE_COMMIT,
        "model_revision": ACE_STEP_MODEL_REVISION,
        "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
        "container_image_digest": image_digest,
        "separation_source_commit": DEMUCS_SOURCE_COMMIT,
        "separation_checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
        "full_song": dict(full_song),
        "stems": {stem: dict(stems[stem]) for stem in REQUIRED_STEMS},
        "raw_title_returned": False,
        "raw_concept_returned": False,
        "raw_lyrics_returned": False,
        "credential_returned": False,
    }
