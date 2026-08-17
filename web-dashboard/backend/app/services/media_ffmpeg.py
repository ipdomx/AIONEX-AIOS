"""Hardened FFmpeg 9 runtime adapter for Phase 36D media rendering."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.core.config import settings
from app.services.media_orchestrator import MediaOutputProfile, output_profile

_COLOR_RE = re.compile(r"^(?:#[0-9a-fA-F]{6}|[a-zA-Z]{1,20})$")


class MediaFFmpegError(RuntimeError):
    """Sanitized FFmpeg execution failure."""


@dataclass(frozen=True, slots=True)
class MediaRenderResult:
    output_path: Path
    command_hash: str
    probe: dict[str, Any]
    engine_version: str
    hardware_adapter: str
    qa: dict[str, Any] = field(default_factory=dict)


def render_command_hash(
    *,
    operation: str,
    profile_id: str,
    metadata: dict[str, Any],
    input_checksums: Sequence[str],
) -> str:
    payload = {
        "engine": "ffmpeg",
        "engine_version": settings.MEDIA_FFMPEG_TARGET_VERSION,
        "operation": operation,
        "profile": profile_id,
        "metadata": metadata,
        "input_checksums": list(input_checksums),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FFmpegRuntime:
    def __init__(
        self,
        *,
        ffmpeg_binary: str | None = None,
        ffprobe_binary: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary or settings.MEDIA_FFMPEG_BINARY
        self.ffprobe_binary = ffprobe_binary or settings.MEDIA_FFPROBE_BINARY
        self.timeout_seconds = int(timeout_seconds or settings.MEDIA_RENDER_TIMEOUT_SECONDS)
        self._version: str | None = None

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env={"PATH": "/opt/ffmpeg/bin:/usr/local/bin:/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            raise MediaFFmpegError("media render exceeded the configured timeout") from None
        except (subprocess.CalledProcessError, OSError) as exc:
            raise MediaFFmpegError(f"media render failed: {type(exc).__name__}") from None

    def preflight(self) -> dict[str, Any]:
        try:
            ffmpeg = self._run([self.ffmpeg_binary, "-version"])
            ffprobe = self._run([self.ffprobe_binary, "-version"])
        except MediaFFmpegError:
            raise
        first = (ffmpeg.stdout or "").splitlines()[0] if ffmpeg.stdout else ""
        probe_first = (ffprobe.stdout or "").splitlines()[0] if ffprobe.stdout else ""
        target = settings.MEDIA_FFMPEG_TARGET_VERSION.strip()
        if not first.startswith(f"ffmpeg version {target}"):
            raise MediaFFmpegError("FFmpeg runtime does not match the required version")
        if not probe_first.startswith(f"ffprobe version {target}"):
            raise MediaFFmpegError("FFprobe runtime does not match the required version")
        self._version = target
        encoders = self._run([self.ffmpeg_binary, "-hide_banner", "-encoders"]).stdout
        required_encoders = ("libx264", "aac", "png", "pcm_s16le", "libsvtav1", "libopus")
        missing = [name for name in required_encoders if name not in encoders]
        if missing:
            raise MediaFFmpegError("FFmpeg runtime is missing required governed encoders")
        return {
            "engine": "ffmpeg",
            "version": target,
            "required_encoders": list(required_encoders),
            "hardware_adapters": list(self.hardware_adapters()),
            "compiled_hardware_adapters": list(self.compiled_hardware_adapters()),
            "hardware_adapter_allowlist": list(self._allowed_hardware_adapters()),
        }

    def compiled_hardware_adapters(self) -> tuple[str, ...]:
        result = self._run([self.ffmpeg_binary, "-hide_banner", "-hwaccels"])
        values: list[str] = []
        for line in (result.stdout or "").splitlines():
            value = line.strip().lower()
            if value and not value.startswith("hardware acceleration"):
                values.append(value)
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _allowed_hardware_adapters() -> tuple[str, ...]:
        values = tuple(
            dict.fromkeys(
                item.strip().lower()
                for item in settings.MEDIA_HARDWARE_ADAPTER_ALLOWLIST.split(",")
                if item.strip()
            )
        )
        return values or ("software",)

    def hardware_adapters(self) -> tuple[str, ...]:
        compiled = set(self.compiled_hardware_adapters())
        allowed = set(self._allowed_hardware_adapters())
        available = ["software"]
        drm_device = Path(settings.MEDIA_RENDER_DRM_DEVICE)
        if drm_device.exists():
            for adapter in ("vaapi", "qsv"):
                if adapter in compiled and adapter in allowed:
                    available.append(adapter)
        return tuple(dict.fromkeys(available))

    def _hardware_preamble(self, adapter: str) -> list[str]:
        device = settings.MEDIA_RENDER_DRM_DEVICE
        if adapter == "software":
            return []
        if adapter == "vaapi":
            return ["-vaapi_device", device]
        if adapter == "qsv":
            return ["-init_hw_device", f"qsv=hw:{device}", "-filter_hw_device", "hw"]
        raise MediaFFmpegError("unsupported media hardware adapter")

    @staticmethod
    def _bounded_int(metadata: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(metadata.get(key, default))
        except (TypeError, ValueError):
            raise MediaFFmpegError(f"invalid media render {key}") from None
        if value < low or value > high:
            raise MediaFFmpegError(f"media render {key} is outside the allowed range")
        return value

    @staticmethod
    def _bounded_float(
        metadata: dict[str, Any], key: str, default: float, low: float, high: float
    ) -> float:
        try:
            value = float(metadata.get(key, default))
        except (TypeError, ValueError):
            raise MediaFFmpegError(f"invalid media render {key}") from None
        if not low <= value <= high:
            raise MediaFFmpegError(f"media render {key} is outside the allowed range")
        return value

    @staticmethod
    def _video_encoder_args(profile: MediaOutputProfile, adapter: str) -> list[str]:
        if adapter == "software":
            if profile.profile_id == "video-mp4-h264":
                return [
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", profile.pixel_format or "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", *profile.ffmpeg_args,
                ]
            if profile.profile_id == "video-webm-av1":
                return [
                    "-c:v", "libsvtav1", "-preset", "10", "-crf", "35",
                    "-pix_fmt", profile.pixel_format or "yuv420p",
                    "-c:a", "libopus", "-b:a", "96k",
                ]
        elif adapter == "vaapi":
            encoder = "h264_vaapi" if profile.profile_id == "video-mp4-h264" else "av1_vaapi"
            audio = ["-c:a", "aac", "-b:a", "128k"] if profile.profile_id == "video-mp4-h264" else ["-c:a", "libopus", "-b:a", "96k"]
            return ["-vf", "format=nv12,hwupload", "-c:v", encoder, "-qp", "23", *audio, *profile.ffmpeg_args]
        elif adapter == "qsv":
            encoder = "h264_qsv" if profile.profile_id == "video-mp4-h264" else "av1_qsv"
            audio = ["-c:a", "aac", "-b:a", "128k"] if profile.profile_id == "video-mp4-h264" else ["-c:a", "libopus", "-b:a", "96k"]
            return ["-vf", "format=nv12,hwupload=extra_hw_frames=64", "-c:v", encoder, "-global_quality", "23", *audio, *profile.ffmpeg_args]
        raise MediaFFmpegError("unsupported governed video output profile or hardware adapter")

    @staticmethod
    def qa_output(
        *,
        operation: str,
        profile: MediaOutputProfile,
        probe: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        streams = [item for item in (probe.get("streams") or []) if isinstance(item, dict)]
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        checks: dict[str, bool] = {"has_streams": bool(streams)}
        if profile.asset_kind == "video":
            expected_codec = "h264" if profile.profile_id == "video-mp4-h264" else "av1"
            checks["video_codec"] = bool(video and video.get("codec_name") == expected_codec)
            if operation == "render_scene":
                expected_audio = "aac" if profile.profile_id == "video-mp4-h264" else "opus"
                checks["audio_codec"] = bool(audio and audio.get("codec_name") == expected_audio)
            if video is not None and metadata.get("width") is not None:
                checks["width"] = int(video.get("width") or 0) == int(metadata["width"])
            if video is not None and metadata.get("height") is not None:
                checks["height"] = int(video.get("height") or 0) == int(metadata["height"])
        elif profile.asset_kind == "image":
            checks["image_codec"] = bool(video and video.get("codec_name") == "png")
            if video is not None and metadata.get("width") is not None:
                checks["width"] = int(video.get("width") or 0) == int(metadata["width"])
            if video is not None and metadata.get("height") is not None:
                checks["height"] = int(video.get("height") or 0) == int(metadata["height"])
        elif profile.asset_kind == "audio":
            checks["audio_codec"] = bool(audio and audio.get("codec_name") == "pcm_s16le")
            checks["sample_rate"] = bool(audio and str(audio.get("sample_rate") or "") == "48000")
        else:
            raise MediaFFmpegError("unsupported media QA profile")

        raw_format = probe.get("format")
        format_data = raw_format if isinstance(raw_format, dict) else {}
        try:
            duration = float(format_data.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        checks["positive_duration_or_image"] = profile.asset_kind == "image" or duration > 0.0
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise MediaFFmpegError("rendered media failed governed QA: " + ",".join(failed))
        return {
            "passed": True,
            "profile": profile.profile_id,
            "operation": operation,
            "checks": checks,
            "duration_seconds": duration,
        }

    def render(
        self,
        *,
        operation: str,
        profile_id: str,
        input_paths: Sequence[Path],
        output_path: Path,
        metadata: dict[str, Any],
        input_checksums: Sequence[str],
        hardware_adapter: str = "software",
    ) -> MediaRenderResult:
        profile = output_profile(profile_id)
        op = operation.strip().lower()
        adapter = hardware_adapter.strip().lower()
        if adapter not in self._allowed_hardware_adapters():
            raise MediaFFmpegError("hardware adapter is not armed by operator policy")
        if adapter not in self.hardware_adapters():
            raise MediaFFmpegError("requested hardware adapter is unavailable on this worker")
        if profile.asset_kind != "video" and adapter != "software":
            raise MediaFFmpegError("hardware adapter is only supported for governed video profiles")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [self.ffmpeg_binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *self._hardware_preamble(adapter)]

        if op == "render_scene":
            if profile.asset_kind != "video":
                raise MediaFFmpegError("render_scene requires a video output profile")
            width = self._bounded_int(metadata, "width", 320, 64, 7680)
            height = self._bounded_int(metadata, "height", 180, 64, 4320)
            if width % 2 or height % 2:
                raise MediaFFmpegError("video dimensions must be even")
            fps = self._bounded_int(metadata, "fps", 24, 1, 120)
            duration = self._bounded_float(metadata, "duration_seconds", 1.0, 0.1, 60.0)
            tone = self._bounded_int(metadata, "tone_hz", 440, 20, 20_000)
            color = str(metadata.get("color", "#1d4ed8")).strip()
            if not _COLOR_RE.fullmatch(color):
                raise MediaFFmpegError("media scene color is invalid")
            command += [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={width}x{height}:r={fps}:d={duration:.3f}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone}:sample_rate=48000:duration={duration:.3f}",
                "-shortest",
                *self._video_encoder_args(profile, adapter),
            ]
        elif op == "assemble":
            if profile.asset_kind != "video" or not input_paths:
                raise MediaFFmpegError("assemble requires video inputs")
            concat_path = output_path.parent / "inputs.txt"
            concat_path.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in input_paths), encoding="utf-8"
            )
            command += ["-f", "concat", "-safe", "0", "-i", str(concat_path)]
            command += self._video_encoder_args(profile, adapter)
        elif op == "transcode":
            if len(input_paths) != 1:
                raise MediaFFmpegError("transcode requires exactly one input")
            command += ["-i", str(input_paths[0])]
            if profile.asset_kind == "video":
                command += self._video_encoder_args(profile, adapter)
            elif profile.asset_kind == "audio":
                command += ["-c:a", profile.audio_codec or "pcm_s16le", *profile.ffmpeg_args]
            elif profile.asset_kind == "image":
                command += ["-c:v", profile.video_codec or "png", *profile.ffmpeg_args]
            else:
                raise MediaFFmpegError("unsupported transcode output profile")
        elif op == "render_image":
            if profile.asset_kind != "image":
                raise MediaFFmpegError("render_image requires an image output profile")
            width = self._bounded_int(metadata, "width", 1024, 64, 7680)
            height = self._bounded_int(metadata, "height", 1024, 64, 7680)
            color = str(metadata.get("color", "#1d4ed8")).strip()
            if not _COLOR_RE.fullmatch(color):
                raise MediaFFmpegError("media image color is invalid")
            command += [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={width}x{height}:d=0.04",
                "-c:v",
                profile.video_codec or "png",
                *profile.ffmpeg_args,
            ]
        elif op == "render_audio":
            if profile.asset_kind != "audio":
                raise MediaFFmpegError("render_audio requires an audio output profile")
            duration = self._bounded_float(metadata, "duration_seconds", 1.0, 0.1, 300.0)
            tone = self._bounded_int(metadata, "tone_hz", 440, 20, 20_000)
            command += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone}:sample_rate=48000:duration={duration:.3f}",
                "-c:a",
                profile.audio_codec or "pcm_s16le",
                *profile.ffmpeg_args,
            ]
        else:
            raise MediaFFmpegError("unsupported media render operation")

        command.append(str(output_path))
        self._run(command)
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise MediaFFmpegError("media renderer did not produce an output")
        probe = self.probe(output_path)
        qa = self.qa_output(operation=op, profile=profile, probe=probe, metadata=metadata)
        return MediaRenderResult(
            output_path=output_path,
            command_hash=render_command_hash(
                operation=op,
                profile_id=profile_id,
                metadata=metadata,
                input_checksums=input_checksums,
            ),
            probe=probe,
            engine_version=self._version or settings.MEDIA_FFMPEG_TARGET_VERSION,
            hardware_adapter=adapter,
            qa=qa,
        )

    def probe(self, path: Path) -> dict[str, Any]:
        result = self._run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            raise MediaFFmpegError("FFprobe returned invalid metadata") from None
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            raise MediaFFmpegError("rendered media has no probeable streams")
        return payload
