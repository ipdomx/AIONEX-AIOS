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
        payload = {
            "preflight": preflight,
            "scene_a": _brief(scene_a),
            "scene_b": _brief(scene_b),
            "final": _brief(final),
            "av1": _brief(av1),
            "image": _brief(image),
            "audio": _brief(audio),
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
        ):
            raise RuntimeError("AV1 render is not probeable as AV1")
        if not any(
            item.get("codec_type") == "video" and item.get("codec_name") == "png"
            for item in image_streams
        ):
            raise RuntimeError("PNG render is not probeable as PNG")
        if not any(item.get("codec_type") == "audio" for item in audio_streams):
            raise RuntimeError("WAV render has no audio stream")
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
