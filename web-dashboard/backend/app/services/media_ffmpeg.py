"""Hardened FFmpeg 9 runtime adapter for governed media rendering."""
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
_LOUDNORM_JSON_RE = re.compile(r'\{\s*"input_i".*?\}', re.DOTALL)
_METRIC_RE = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)")
_AUDIO_CODEC_NAMES = {"libopus": "opus", "pcm_s16le": "pcm_s16le", "aac": "aac"}
_REQUIRED_AUDIO_FILTERS = (
    "adelay",
    "amix",
    "aresample",
    "astats",
    "ebur128",
    "highpass",
    "loudnorm",
    "lowpass",
    "showwavespic",
    "silencedetect",
)


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
        ffmpeg = self._run([self.ffmpeg_binary, "-version"])
        ffprobe = self._run([self.ffprobe_binary, "-version"])
        first = (ffmpeg.stdout or "").splitlines()[0] if ffmpeg.stdout else ""
        probe_first = (ffprobe.stdout or "").splitlines()[0] if ffprobe.stdout else ""
        target = settings.MEDIA_FFMPEG_TARGET_VERSION.strip()
        if not first.startswith(f"ffmpeg version {target}"):
            raise MediaFFmpegError("FFmpeg runtime does not match the required version")
        if not probe_first.startswith(f"ffprobe version {target}"):
            raise MediaFFmpegError("FFprobe runtime does not match the required version")
        self._version = target
        encoders = self._run([self.ffmpeg_binary, "-hide_banner", "-encoders"]).stdout
        required_encoders = (
            "libx264",
            "aac",
            "png",
            "pcm_s16le",
            "libsvtav1",
            "libopus",
        )
        missing_encoders = [name for name in required_encoders if name not in encoders]
        if missing_encoders:
            raise MediaFFmpegError("FFmpeg runtime is missing required governed encoders")
        filters = self._run([self.ffmpeg_binary, "-hide_banner", "-filters"]).stdout
        missing_filters = [
            name
            for name in _REQUIRED_AUDIO_FILTERS
            if re.search(rf"\b{re.escape(name)}\b", filters or "") is None
        ]
        if missing_filters:
            raise MediaFFmpegError("FFmpeg runtime is missing required governed audio filters")
        return {
            "engine": "ffmpeg",
            "version": target,
            "required_encoders": list(required_encoders),
            "required_audio_filters": list(_REQUIRED_AUDIO_FILTERS),
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
            return [
                "-init_hw_device",
                f"qsv=hw:{device}",
                "-filter_hw_device",
                "hw",
            ]
        raise MediaFFmpegError("unsupported media hardware adapter")

    @staticmethod
    def _bounded_int(
        metadata: dict[str, Any], key: str, default: int, low: int, high: int
    ) -> int:
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
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    profile.pixel_format or "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    *profile.ffmpeg_args,
                ]
            if profile.profile_id == "video-webm-av1":
                return [
                    "-c:v",
                    "libsvtav1",
                    "-preset",
                    "10",
                    "-crf",
                    "35",
                    "-pix_fmt",
                    profile.pixel_format or "yuv420p",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "96k",
                ]
        elif adapter == "vaapi":
            encoder = (
                "h264_vaapi"
                if profile.profile_id == "video-mp4-h264"
                else "av1_vaapi"
            )
            audio = (
                ["-c:a", "aac", "-b:a", "128k"]
                if profile.profile_id == "video-mp4-h264"
                else ["-c:a", "libopus", "-b:a", "96k"]
            )
            return [
                "-vf",
                "format=nv12,hwupload",
                "-c:v",
                encoder,
                "-qp",
                "23",
                *audio,
                *profile.ffmpeg_args,
            ]
        elif adapter == "qsv":
            encoder = (
                "h264_qsv" if profile.profile_id == "video-mp4-h264" else "av1_qsv"
            )
            audio = (
                ["-c:a", "aac", "-b:a", "128k"]
                if profile.profile_id == "video-mp4-h264"
                else ["-c:a", "libopus", "-b:a", "96k"]
            )
            return [
                "-vf",
                "format=nv12,hwupload=extra_hw_frames=64",
                "-c:v",
                encoder,
                "-global_quality",
                "23",
                *audio,
                *profile.ffmpeg_args,
            ]
        raise MediaFFmpegError(
            "unsupported governed video output profile or hardware adapter"
        )

    @staticmethod
    def _audio_encoder_args(profile: MediaOutputProfile) -> list[str]:
        if profile.asset_kind != "audio" or not profile.audio_codec:
            raise MediaFFmpegError("governed audio output profile is invalid")
        args = ["-c:a", profile.audio_codec]
        if profile.bitrate_kbps is not None:
            args.extend(["-b:a", f"{profile.bitrate_kbps}k"])
        if profile.sample_rate_hz is not None:
            args.extend(["-ar", str(profile.sample_rate_hz)])
        if profile.channels is not None:
            args.extend(["-ac", str(profile.channels)])
        args.extend(profile.ffmpeg_args)
        return args

    @staticmethod
    def _format_matches(profile: MediaOutputProfile, format_name: str) -> bool:
        values = {item.strip().lower() for item in format_name.split(",") if item.strip()}
        container = (profile.container or "").lower()
        if container == "mp4":
            return bool(values & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
        if container == "webm":
            return "webm" in values
        if container:
            return container in values
        return True

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
        raw_format = probe.get("format")
        format_data = raw_format if isinstance(raw_format, dict) else {}
        format_name = str(format_data.get("format_name") or "").lower()
        checks: dict[str, bool] = {"has_streams": bool(streams)}
        if profile.asset_kind == "video":
            expected_codec = "h264" if profile.profile_id == "video-mp4-h264" else "av1"
            checks["video_codec"] = bool(video and video.get("codec_name") == expected_codec)
            if operation == "render_scene":
                expected_audio = (
                    "aac" if profile.profile_id == "video-mp4-h264" else "opus"
                )
                checks["audio_codec"] = bool(
                    audio and audio.get("codec_name") == expected_audio
                )
            if video is not None and metadata.get("width") is not None:
                checks["width"] = int(video.get("width") or 0) == int(metadata["width"])
            if video is not None and metadata.get("height") is not None:
                checks["height"] = int(video.get("height") or 0) == int(
                    metadata["height"]
                )
        elif profile.asset_kind == "image":
            checks["image_codec"] = bool(video and video.get("codec_name") == "png")
            if video is not None and metadata.get("width") is not None:
                checks["width"] = int(video.get("width") or 0) == int(metadata["width"])
            if video is not None and metadata.get("height") is not None:
                checks["height"] = int(video.get("height") or 0) == int(
                    metadata["height"]
                )
        elif profile.asset_kind == "audio":
            expected_codec = _AUDIO_CODEC_NAMES.get(
                profile.audio_codec or "", profile.audio_codec or ""
            )
            checks["audio_codec"] = bool(
                audio and audio.get("codec_name") == expected_codec
            )
            if profile.sample_rate_hz is not None:
                checks["sample_rate"] = bool(
                    audio
                    and str(audio.get("sample_rate") or "")
                    == str(profile.sample_rate_hz)
                )
            if profile.channels is not None:
                checks["channels"] = bool(
                    audio and int(audio.get("channels") or 0) == profile.channels
                )
            checks["container"] = FFmpegRuntime._format_matches(profile, format_name)
        else:
            raise MediaFFmpegError("unsupported media QA profile")

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

    @staticmethod
    def _metric(value: Any, label: str) -> float:
        text = str(value or "").strip().lower()
        if text in {"inf", "+inf", "-inf", "nan", ""}:
            raise MediaFFmpegError(f"audio analysis {label} is unavailable")
        try:
            return float(text)
        except ValueError:
            raise MediaFFmpegError(f"audio analysis {label} is invalid") from None

    def _analyze_audio(self, path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        target_i = self._bounded_float(
            metadata, "target_integrated_lufs", -16.0, -32.0, -8.0
        )
        target_tp = self._bounded_float(metadata, "max_true_peak_dbtp", -1.0, -6.0, 0.0)
        target_lra = self._bounded_float(
            metadata, "max_loudness_range_lu", 12.0, 1.0, 40.0
        )
        tolerance = self._bounded_float(
            metadata, "loudness_tolerance_lu", 1.5, 0.1, 5.0
        )
        silence_noise = self._bounded_float(
            metadata, "silence_noise_db", -50.0, -90.0, -20.0
        )
        silence_duration = self._bounded_float(
            metadata, "silence_min_duration_seconds", 0.2, 0.05, 10.0
        )
        loudness = self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                (
                    f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
                    "print_format=json"
                ),
                "-f",
                "null",
                "-",
            ]
        )
        matches = _LOUDNORM_JSON_RE.findall(loudness.stderr or "")
        if not matches:
            raise MediaFFmpegError("audio loudness analysis returned no governed metrics")
        try:
            metrics = json.loads(matches[-1])
        except json.JSONDecodeError:
            raise MediaFFmpegError("audio loudness analysis returned invalid metrics") from None
        integrated = self._metric(metrics.get("input_i"), "integrated loudness")
        true_peak = self._metric(metrics.get("input_tp"), "true peak")
        loudness_range = self._metric(metrics.get("input_lra"), "loudness range")

        silence = self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                f"silencedetect=noise={silence_noise}dB:d={silence_duration}",
                "-f",
                "null",
                "-",
            ]
        )
        silence_values = [
            float(value)
            for value in re.findall(
                r"silence_duration:\s*([-+]?\d+(?:\.\d+)?)", silence.stderr or ""
            )
        ]

        astats = self._run(
            [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                "astats=metadata=1:reset=0",
                "-f",
                "null",
                "-",
            ]
        )
        overall = (astats.stderr or "").rsplit("Overall", 1)[-1]
        peak_match = re.search(r"Peak level dB:\s*([^\r\n]+)", overall)
        if peak_match is None:
            raise MediaFFmpegError("audio clipping analysis returned no peak metric")
        metric_match = _METRIC_RE.search(peak_match.group(1))
        if metric_match is None:
            raise MediaFFmpegError("audio clipping analysis peak metric is invalid")
        sample_peak = float(metric_match.group(0))

        checks = {
            "integrated_loudness": abs(integrated - target_i) <= tolerance,
            "true_peak": true_peak <= target_tp + 0.1,
            "loudness_range": loudness_range <= target_lra,
            "not_clipped": sample_peak < -0.001,
        }
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise MediaFFmpegError("audio master failed governed QA: " + ",".join(failed))
        return {
            "schema": "36G.audio-qa.v1",
            "method": "ffmpeg-loudnorm-silencedetect-astats",
            "integrated_lufs": round(integrated, 3),
            "true_peak_dbtp": round(true_peak, 3),
            "loudness_range_lu": round(loudness_range, 3),
            "sample_peak_db": round(sample_peak, 3),
            "silence_segment_count": len(silence_values),
            "silence_duration_seconds": round(sum(silence_values), 3),
            "clipped": False,
            "targets": {
                "integrated_lufs": target_i,
                "max_true_peak_dbtp": target_tp,
                "max_loudness_range_lu": target_lra,
                "loudness_tolerance_lu": tolerance,
            },
            "checks": checks,
            "passed": True,
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
            raise MediaFFmpegError(
                "hardware adapter is only supported for governed video profiles"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *self._hardware_preamble(adapter),
        ]

        if op == "render_scene":
            if profile.asset_kind != "video":
                raise MediaFFmpegError("render_scene requires a video output profile")
            width = self._bounded_int(metadata, "width", 320, 64, 7680)
            height = self._bounded_int(metadata, "height", 180, 64, 4320)
            if width % 2 or height % 2:
                raise MediaFFmpegError("video dimensions must be even")
            fps = self._bounded_int(metadata, "fps", 24, 1, 120)
            duration = self._bounded_float(
                metadata, "duration_seconds", 1.0, 0.1, 60.0
            )
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
                "".join(f"file '{path.as_posix()}'\n" for path in input_paths),
                encoding="utf-8",
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
                command += ["-vn", *self._audio_encoder_args(profile)]
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
            duration = self._bounded_float(
                metadata, "duration_seconds", 1.0, 0.1, 300.0
            )
            tone = self._bounded_int(metadata, "tone_hz", 440, 20, 20_000)
            sample_rate = profile.sample_rate_hz or 48_000
            command += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone}:sample_rate={sample_rate}:duration={duration:.3f}",
                *self._audio_encoder_args(profile),
            ]
        elif op == "audio_cleanup":
            if profile.asset_kind != "audio" or len(input_paths) != 1:
                raise MediaFFmpegError("audio_cleanup requires one audio input")
            highpass = self._bounded_int(metadata, "highpass_hz", 70, 20, 1_000)
            lowpass = self._bounded_int(metadata, "lowpass_hz", 18_000, 3_000, 24_000)
            if highpass >= lowpass:
                raise MediaFFmpegError("audio cleanup filter range is invalid")
            rate = profile.sample_rate_hz or 48_000
            layout = "mono" if profile.channels == 1 else "stereo"
            command += [
                "-i",
                str(input_paths[0]),
                "-vn",
                "-af",
                (
                    f"highpass=f={highpass},lowpass=f={lowpass},"
                    f"aresample={rate},aformat=channel_layouts={layout}"
                ),
                *self._audio_encoder_args(profile),
            ]
        elif op == "audio_align":
            if profile.asset_kind != "audio" or len(input_paths) != 1:
                raise MediaFFmpegError("audio_align requires one audio input")
            offset_ms = self._bounded_int(metadata, "offset_ms", 0, 0, 60_000)
            gain_db = self._bounded_float(metadata, "gain_db", 0.0, -24.0, 24.0)
            rate = profile.sample_rate_hz or 48_000
            layout = "mono" if profile.channels == 1 else "stereo"
            filters = [f"volume={gain_db:.3f}dB"]
            if offset_ms:
                filters.append(f"adelay={offset_ms}:all=1")
            filters.extend([f"aresample={rate}", f"aformat=channel_layouts={layout}"])
            command += [
                "-i",
                str(input_paths[0]),
                "-vn",
                "-af",
                ",".join(filters),
                *self._audio_encoder_args(profile),
            ]
        elif op == "audio_mix":
            if profile.asset_kind != "audio" or not 1 <= len(input_paths) <= 16:
                raise MediaFFmpegError("audio_mix requires one to sixteen audio inputs")
            for path in input_paths:
                command.extend(["-i", str(path)])
            labels = "".join(f"[{index}:a]" for index in range(len(input_paths)))
            rate = profile.sample_rate_hz or 48_000
            layout = "mono" if profile.channels == 1 else "stereo"
            filter_graph = (
                f"{labels}amix=inputs={len(input_paths)}:duration=longest:normalize=0,"
                f"alimiter=limit=0.95,aresample={rate},"
                f"aformat=channel_layouts={layout}[mixed]"
            )
            command += [
                "-filter_complex",
                filter_graph,
                "-map",
                "[mixed]",
                *self._audio_encoder_args(profile),
            ]
        elif op == "audio_master":
            if profile.asset_kind != "audio" or len(input_paths) != 1:
                raise MediaFFmpegError("audio_master requires one audio input")
            target_i = self._bounded_float(
                metadata, "target_integrated_lufs", -16.0, -32.0, -8.0
            )
            target_tp = self._bounded_float(
                metadata, "max_true_peak_dbtp", -1.0, -6.0, 0.0
            )
            target_lra = self._bounded_float(
                metadata, "max_loudness_range_lu", 12.0, 1.0, 40.0
            )
            rate = profile.sample_rate_hz or 48_000
            layout = "mono" if profile.channels == 1 else "stereo"
            command += [
                "-i",
                str(input_paths[0]),
                "-vn",
                "-af",
                (
                    f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra},"
                    f"aresample={rate},aformat=channel_layouts={layout}"
                ),
                *self._audio_encoder_args(profile),
            ]
        elif op == "audio_waveform":
            if profile.asset_kind != "image" or len(input_paths) != 1:
                raise MediaFFmpegError("audio_waveform requires one audio input")
            width = self._bounded_int(metadata, "width", 1_200, 320, 4_096)
            height = self._bounded_int(metadata, "height", 320, 120, 2_160)
            color = str(metadata.get("color", "#38bdf8")).strip()
            if not _COLOR_RE.fullmatch(color):
                raise MediaFFmpegError("audio waveform color is invalid")
            command += [
                "-i",
                str(input_paths[0]),
                "-filter_complex",
                (
                    "aformat=channel_layouts=mono,"
                    f"showwavespic=s={width}x{height}:colors={color}"
                ),
                "-frames:v",
                "1",
                "-c:v",
                profile.video_codec or "png",
                *profile.ffmpeg_args,
            ]
        elif op == "audio_export":
            if profile.asset_kind != "audio" or not input_paths:
                raise MediaFFmpegError("audio_export requires an audio dependency")
            primary_index = self._bounded_int(
                metadata, "primary_input_index", 0, 0, len(input_paths) - 1
            )
            target_i = self._bounded_float(
                metadata, "target_integrated_lufs", -16.0, -32.0, -8.0
            )
            target_tp = self._bounded_float(
                metadata, "max_true_peak_dbtp", -1.0, -6.0, 0.0
            )
            target_lra = self._bounded_float(
                metadata, "max_loudness_range_lu", 12.0, 1.0, 40.0
            )
            rate = profile.sample_rate_hz or 48_000
            layout = "mono" if profile.channels == 1 else "stereo"
            command += [
                "-i",
                str(input_paths[primary_index]),
                "-vn",
                "-af",
                (
                    f"aresample={rate},aformat=channel_layouts={layout},"
                    f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra},"
                    f"aresample={rate},aformat=channel_layouts={layout}"
                ),
                *self._audio_encoder_args(profile),
            ]
        else:
            raise MediaFFmpegError("unsupported media render operation")

        command.append(str(output_path))
        self._run(command)
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise MediaFFmpegError("media renderer did not produce an output")
        probe = self.probe(output_path)
        qa = self.qa_output(operation=op, profile=profile, probe=probe, metadata=metadata)
        if op in {"audio_master", "audio_export"}:
            qa = {**qa, "audio_analysis": self._analyze_audio(output_path, metadata)}
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
