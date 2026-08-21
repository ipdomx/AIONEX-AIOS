"""Render real bounded media with the shipped Phase 36D FFmpeg worker image."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.services.media_ffmpeg import FFmpegRuntime


def _brief(result) -> dict[str, object]:
    return {
        "size_bytes": result.output_path.stat().st_size,
        "command_hash": result.command_hash,
        "probe": result.probe,
    }


def main() -> int:
    runtime = FFmpegRuntime(timeout_seconds=120)
    preflight = runtime.preflight()
    with tempfile.TemporaryDirectory(prefix="aionex-p36d-ffmpeg-") as temporary:
        root = Path(temporary)
        scene_a = runtime.render(
            operation="render_scene",
            profile_id="video-mp4-h264",
            input_paths=[],
            output_path=root / "scene-a.mp4",
            metadata={
                "color": "#1d4ed8",
                "duration_seconds": 0.6,
                "width": 320,
                "height": 180,
                "fps": 24,
                "tone_hz": 440,
            },
            input_checksums=[],
        )
        scene_b = runtime.render(
            operation="render_scene",
            profile_id="video-mp4-h264",
            input_paths=[],
            output_path=root / "scene-b.mp4",
            metadata={
                "color": "#0f766e",
                "duration_seconds": 0.6,
                "width": 320,
                "height": 180,
                "fps": 24,
                "tone_hz": 550,
            },
            input_checksums=[],
        )
        final = runtime.render(
            operation="assemble",
            profile_id="video-mp4-h264",
            input_paths=[scene_a.output_path, scene_b.output_path],
            output_path=root / "final.mp4",
            metadata={},
            input_checksums=[scene_a.command_hash, scene_b.command_hash],
        )
        av1 = runtime.render(
            operation="render_scene",
            profile_id="video-webm-av1",
            input_paths=[],
            output_path=root / "scene-av1.webm",
            metadata={
                "color": "#7c3aed",
                "duration_seconds": 0.3,
                "width": 320,
                "height": 180,
                "fps": 24,
                "tone_hz": 700,
            },
            input_checksums=[],
        )
        image = runtime.render(
            operation="render_image",
            profile_id="image-png-lossless",
            input_paths=[],
            output_path=root / "poster.png",
            metadata={"color": "#991b1b", "width": 640, "height": 360},
            input_checksums=[],
        )
        audio = runtime.render(
            operation="render_audio",
            profile_id="audio-wav-pcm",
            input_paths=[],
            output_path=root / "tone.wav",
            metadata={"duration_seconds": 0.5, "tone_hz": 660},
            input_checksums=[],
        )

        audio_source_a = runtime.render(
            operation="render_audio",
            profile_id="audio-wav-pcm",
            input_paths=[],
            output_path=root / "audio-source-a.wav",
            metadata={"duration_seconds": 2.0, "tone_hz": 440},
            input_checksums=[],
        )
        audio_source_b = runtime.render(
            operation="render_audio",
            profile_id="audio-wav-pcm",
            input_paths=[],
            output_path=root / "audio-source-b.wav",
            metadata={"duration_seconds": 1.5, "tone_hz": 660},
            input_checksums=[],
        )
        audio_cleanup = runtime.render(
            operation="audio_cleanup",
            profile_id="audio-wav-pcm",
            input_paths=[audio_source_a.output_path],
            output_path=root / "audio-cleanup.wav",
            metadata={"highpass_hz": 70, "lowpass_hz": 18_000},
            input_checksums=[audio_source_a.command_hash],
        )
        audio_align = runtime.render(
            operation="audio_align",
            profile_id="audio-wav-pcm",
            input_paths=[audio_source_b.output_path],
            output_path=root / "audio-align.wav",
            metadata={"offset_ms": 250, "gain_db": -3.0},
            input_checksums=[audio_source_b.command_hash],
        )
        audio_mix = runtime.render(
            operation="audio_mix",
            profile_id="audio-wav-pcm",
            input_paths=[audio_cleanup.output_path, audio_align.output_path],
            output_path=root / "audio-mix.wav",
            metadata={},
            input_checksums=[audio_cleanup.command_hash, audio_align.command_hash],
        )
        audio_targets = {
            "target_integrated_lufs": -16.0,
            "max_true_peak_dbtp": -1.0,
            "max_loudness_range_lu": 12.0,
            "loudness_tolerance_lu": 1.5,
            "silence_noise_db": -50.0,
            "silence_min_duration_seconds": 0.2,
        }
        audio_master = runtime.render(
            operation="audio_master",
            profile_id="audio-wav-pcm",
            input_paths=[audio_mix.output_path],
            output_path=root / "audio-master.wav",
            metadata=audio_targets,
            input_checksums=[audio_mix.command_hash],
        )
        audio_waveform = runtime.render(
            operation="audio_waveform",
            profile_id="image-png-lossless",
            input_paths=[audio_master.output_path],
            output_path=root / "audio-waveform.png",
            metadata={"width": 1_200, "height": 320, "color": "#38bdf8"},
            input_checksums=[audio_master.command_hash],
        )
        audio_exports = {}
        for profile_id, filename in (
            ("audio-wav-pcm", "audio-final.wav"),
            ("audio-wav-pcm-mono", "audio-final-mono.wav"),
            ("audio-m4a-aac", "audio-final.m4a"),
            ("audio-webm-opus", "audio-final.webm"),
        ):
            result = runtime.render(
                operation="audio_export",
                profile_id=profile_id,
                input_paths=[audio_master.output_path, audio_waveform.output_path],
                output_path=root / filename,
                metadata={"primary_input_index": 0, **audio_targets},
                input_checksums=[audio_master.command_hash, audio_waveform.command_hash],
            )
            audio_exports[profile_id] = _brief(result) | {"qa": result.qa}

        payload = {
            "preflight": preflight,
            "scene_a": _brief(scene_a),
            "scene_b": _brief(scene_b),
            "final": _brief(final),
            "av1": _brief(av1),
            "image": _brief(image),
            "audio": _brief(audio),
            "phase36g_audio": {
                "cleanup": _brief(audio_cleanup),
                "align": _brief(audio_align),
                "mix": _brief(audio_mix),
                "master": _brief(audio_master) | {"qa": audio_master.qa},
                "waveform": _brief(audio_waveform),
                "exports": audio_exports,
                "provider_requests": 0,
                "provider_spend_usd": 0.0,
            },
        }
        if preflight.get("version") != "9.0":
            raise RuntimeError("unexpected FFmpeg version")
        final_streams = final.probe.get("streams") or []
        av1_streams = av1.probe.get("streams") or []
        image_streams = image.probe.get("streams") or []
        audio_streams = audio.probe.get("streams") or []
        if not any(item.get("codec_type") == "video" for item in final_streams):
            raise RuntimeError("assembled output has no video stream")
        if not any(
            item.get("codec_type") == "video" and item.get("codec_name") == "av1"
            for item in av1_streams
        ) or not any(
            item.get("codec_type") == "audio" and item.get("codec_name") == "opus"
            for item in av1_streams
        ):
            raise RuntimeError("AV1 WebM render is not AV1/Opus")
        if not any(
            item.get("codec_type") == "video" and item.get("codec_name") == "png"
            for item in image_streams
        ):
            raise RuntimeError("PNG render is not probeable as PNG")
        if not any(item.get("codec_type") == "audio" for item in audio_streams):
            raise RuntimeError("WAV render has no audio stream")
        analysis = audio_master.qa.get("audio_analysis")
        if not isinstance(analysis, dict) or analysis.get("passed") is not True:
            raise RuntimeError("Phase36G audio master has no governed QA evidence")
        if audio_waveform.probe.get("streams", [{}])[0].get("codec_name") != "png":
            raise RuntimeError("Phase36G waveform output is not PNG")
        expected_codecs = {
            "audio-wav-pcm": "pcm_s16le",
            "audio-wav-pcm-mono": "pcm_s16le",
            "audio-m4a-aac": "aac",
            "audio-webm-opus": "opus",
        }
        for profile_id, expected_codec in expected_codecs.items():
            streams = audio_exports[profile_id]["probe"].get("streams") or []
            if not any(
                item.get("codec_type") == "audio"
                and item.get("codec_name") == expected_codec
                for item in streams
            ):
                raise RuntimeError(f"Phase36G {profile_id} export codec mismatch")
            export_qa = audio_exports[profile_id]["qa"].get("audio_analysis")
            if not isinstance(export_qa, dict) or export_qa.get("passed") is not True:
                raise RuntimeError(f"Phase36G {profile_id} export QA missing")
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
