from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.services.media_ffmpeg import FFmpegRuntime, MediaFFmpegError


class CaptureFFmpegRuntime(FFmpegRuntime):
    def __init__(self) -> None:
        super().__init__(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe", timeout_seconds=5)
        self.commands: list[list[str]] = []

    def hardware_adapters(self) -> tuple[str, ...]:
        return ("software",)

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, '{"streams":[{"codec_type":"video","codec_name":"h264","width":1280,"height":720}],"format":{"duration":"3.0","format_name":"mov,mp4"}}', "")
        Path(command[-1]).write_bytes(b"rendered-vfx")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_vfx_composite_builds_bounded_chromakey_overlay_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = CaptureFFmpegRuntime()
    monkeypatch.setattr(runtime, "_allowed_hardware_adapters", lambda: ("software",))
    bg, fg = tmp_path / "bg.mp4", tmp_path / "fg.mp4"
    bg.write_bytes(b"bg")
    fg.write_bytes(b"fg")
    result = runtime.render(
        operation="vfx_composite", profile_id="video-mp4-h264", input_paths=[bg, fg],
        output_path=tmp_path / "out.mp4", metadata={"width":1280,"height":720,"overlay_x":80,"overlay_y":220,"chroma_key":"#00ff00","chroma_similarity":0.12,"chroma_blend":0.04},
        input_checksums=["a"*64,"b"*64], hardware_adapter="software",
    )
    command = runtime.commands[0]
    filter_value = command[command.index("-filter_complex") + 1]
    assert "chromakey=0x00ff00:0.120:0.040" in filter_value
    assert "overlay=x=80:y=220" in filter_value
    assert result.qa["passed"] is True


def test_vfx_composite_rejects_unbounded_or_injected_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = CaptureFFmpegRuntime()
    monkeypatch.setattr(runtime, "_allowed_hardware_adapters", lambda: ("software",))
    bg, fg = tmp_path / "bg.mp4", tmp_path / "fg.mp4"
    bg.write_bytes(b"bg")
    fg.write_bytes(b"fg")
    with pytest.raises(MediaFFmpegError, match="chroma key"):
        runtime.render(operation="vfx_composite",profile_id="video-mp4-h264",input_paths=[bg,fg],output_path=tmp_path/"x.mp4",metadata={"chroma_key":"green;movie=bad"},input_checksums=["a"*64,"b"*64])
