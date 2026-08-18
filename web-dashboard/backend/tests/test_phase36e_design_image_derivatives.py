from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest

from app.services.design_image_derivatives import (
    DesignImageDerivativeError,
    SharpDerivativeRuntime,
    SharpDerivativeSpec,
)


def png_envelope(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


def test_sharp_derivative_spec_is_bounded_and_governed() -> None:
    assert SharpDerivativeSpec(width=1920, height=1080, output_format="webp").fit == "cover"
    with pytest.raises(DesignImageDerivativeError, match="dimensions"):
        SharpDerivativeSpec(width=0, height=1080, output_format="png")
    with pytest.raises(DesignImageDerivativeError, match="format"):
        SharpDerivativeSpec(width=100, height=100, output_format="gif")
    with pytest.raises(DesignImageDerivativeError, match="fit"):
        SharpDerivativeSpec(width=100, height=100, output_format="png", fit="fill")


def test_sharp_runtime_rejects_bad_source_checksum_before_execution(tmp_path: Path) -> None:
    script = tmp_path / "derivative.mjs"
    script.write_text("// test", encoding="utf-8")
    runtime = SharpDerivativeRuntime(
        node_binary="node",
        script_path=script,
        temp_root=tmp_path / "work",
    )
    with pytest.raises(DesignImageDerivativeError, match="checksum"):
        runtime.render(
            source_body=png_envelope(64, 64),
            source_format="png",
            source_checksum="0" * 64,
            spec=SharpDerivativeSpec(width=128, height=128, output_format="png"),
        )


def test_sharp_runtime_verifies_receipt_output_dimensions_and_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "derivative.mjs"
    script.write_text("// test", encoding="utf-8")
    source = png_envelope(64, 48)
    source_sha = hashlib.sha256(source).hexdigest()

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="v24.18.1\n", stderr="")
        if command[-1] == "--probe":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "engine": "sharp",
                        "engine_version": "0.35.3",
                        "libvips_version": "8.18.3",
                    }
                ),
                stderr="",
            )
        output = Path(command[command.index("--output") + 1])
        width = int(command[command.index("--width") + 1])
        height = int(command[command.index("--height") + 1])
        output.write_bytes(png_envelope(width, height))
        receipt = {
            "engine": "sharp",
            "engine_version": "0.35.3",
            "input_format": "png",
            "input_width": 64,
            "input_height": 48,
            "input_has_alpha": False,
            "output_format": "png",
            "output_width": width,
            "output_height": height,
            "output_has_alpha": False,
            "output_size": output.stat().st_size,
            "fit": "cover",
            "position": "centre",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(receipt), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runtime = SharpDerivativeRuntime(
        node_binary="node",
        script_path=script,
        temp_root=tmp_path / "work",
    )
    assert runtime.preflight()["node_version"] == "24.18.1"
    result = runtime.render(
        source_body=source,
        source_format="png",
        source_checksum=source_sha,
        spec=SharpDerivativeSpec(width=320, height=180, output_format="png"),
    )
    assert (result.width, result.height, result.content_type) == (320, 180, "image/png")
    assert result.input_sha256 == source_sha
    assert result.sha256 == hashlib.sha256(result.body).hexdigest()
    assert len(result.command_hash) == 64
    assert result.metadata["engine_version"] == "0.35.3"


def test_sharp_runtime_fails_closed_on_version_or_receipt_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "derivative.mjs"
    script.write_text("// test", encoding="utf-8")
    runtime = SharpDerivativeRuntime(node_binary="node", script_path=script, temp_root=tmp_path / "work")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="v23.0.0\n", stderr=""),
    )
    with pytest.raises(DesignImageDerivativeError, match="Node 24"):
        runtime.preflight()


def test_sharp_runtime_subprocess_environment_excludes_application_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "derivative.mjs"
    script.write_text("// test", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sensitive")
    monkeypatch.setenv("OPENAI_API_KEY", "sensitive-provider-key")
    monkeypatch.setenv("SECRET_KEY", "sensitive-app-key")
    captured_envs: list[dict[str, str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured_envs.append({str(k): str(v) for k, v in env.items()})
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="v24.18.1\n", stderr="")
        assert command[-1] == "--probe"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "engine": "sharp",
                    "engine_version": "0.35.3",
                    "libvips_version": "8.18.3",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    runtime = SharpDerivativeRuntime(
        node_binary="node",
        script_path=script,
        temp_root=tmp_path / "work",
    )
    evidence = runtime.preflight()
    assert evidence["engine_version"] == "0.35.3"
    assert len(captured_envs) == 2
    for env in captured_envs:
        assert env["HOME"] == "/tmp"
        assert env["NO_COLOR"] == "1"
        assert "DATABASE_URL" not in env
        assert "OPENAI_API_KEY" not in env
        assert "SECRET_KEY" not in env
