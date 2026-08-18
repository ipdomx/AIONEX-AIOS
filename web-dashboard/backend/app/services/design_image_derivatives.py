"""Phase 36E governed Sharp raster derivative runtime.

This module is local-only: it never calls a provider and never reads credentials.
Provider source bytes are verified before execution and the rendered raster envelope,
dimensions and checksum are verified before any caller may persist the result.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.design_image_runtime import DesignImageExecutionError, _inspect_raster

SHARP_TARGET_VERSION = "0.35.3"
_ALLOWED_FORMATS = frozenset({"png", "jpeg", "webp"})
_ALLOWED_FITS = frozenset({"cover", "contain"})
_ALLOWED_POSITIONS = frozenset({"centre", "center", "north", "south", "east", "west"})
_CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
_SUFFIXES = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
_SAFE_CHILD_ENV_KEYS = ("LANG", "LC_ALL", "TZ")


class DesignImageDerivativeError(RuntimeError):
    """A governed local raster derivative could not be produced safely."""


@dataclass(frozen=True, slots=True)
class SharpDerivativeSpec:
    width: int
    height: int
    output_format: str
    fit: str = "cover"
    position: str = "centre"

    def __post_init__(self) -> None:
        if not (1 <= int(self.width) <= 8192 and 1 <= int(self.height) <= 8192):
            raise DesignImageDerivativeError("derivative dimensions are outside the governed range")
        if self.output_format not in _ALLOWED_FORMATS:
            raise DesignImageDerivativeError("derivative output format is unsupported")
        if self.fit not in _ALLOWED_FITS:
            raise DesignImageDerivativeError("derivative fit is unsupported")
        if self.position not in _ALLOWED_POSITIONS:
            raise DesignImageDerivativeError("derivative position is unsupported")

    def canonical(self) -> dict[str, Any]:
        return {
            "width": int(self.width),
            "height": int(self.height),
            "output_format": self.output_format,
            "fit": self.fit,
            "position": self.position,
        }


@dataclass(frozen=True, slots=True)
class SharpDerivativeResult:
    body: bytes
    content_type: str
    width: int
    height: int
    output_format: str
    sha256: str
    size_bytes: int
    input_sha256: str
    command_hash: str
    engine_version: str
    metadata: dict[str, Any]


def _child_env() -> dict[str, str]:
    """Return a minimal child environment; provider/database credentials never cross this boundary."""
    env = {key: os.environ[key] for key in _SAFE_CHILD_ENV_KEYS if os.environ.get(key)}
    env["NO_COLOR"] = "1"
    env["HOME"] = "/tmp"
    return env


class SharpDerivativeRuntime:
    def __init__(
        self,
        *,
        node_binary: str | None = None,
        script_path: str | Path | None = None,
        timeout_seconds: int | None = None,
        temp_root: str | Path | None = None,
    ) -> None:
        self.node_binary = str(node_binary or settings.DESIGN_IMAGE_SHARP_NODE_BINARY).strip()
        self.script_path = Path(script_path or settings.DESIGN_IMAGE_SHARP_SCRIPT).resolve()
        self.timeout_seconds = int(timeout_seconds or settings.DESIGN_IMAGE_SHARP_TIMEOUT_SECONDS)
        self.temp_root = Path(temp_root or settings.DESIGN_IMAGE_SHARP_TEMP_ROOT).resolve()
        if not self.node_binary or not (5 <= self.timeout_seconds <= 600):
            raise DesignImageDerivativeError("Sharp runtime configuration is invalid")

    def preflight(self) -> dict[str, Any]:
        if not self.script_path.is_file():
            raise DesignImageDerivativeError("Sharp derivative script is unavailable")
        try:
            node = subprocess.run(
                [self.node_binary, "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                env=_child_env(),
            )
            probe = subprocess.run(
                [self.node_binary, str(self.script_path), "--probe"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                env=_child_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DesignImageDerivativeError("Sharp runtime preflight failed") from exc
        version = node.stdout.strip().lstrip("v")
        if not version.startswith("24."):
            raise DesignImageDerivativeError("Sharp derivative Node runtime must be Node 24")
        try:
            evidence = json.loads(probe.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DesignImageDerivativeError("Sharp runtime probe is invalid") from exc
        if (
            not isinstance(evidence, dict)
            or evidence.get("engine") != "sharp"
            or evidence.get("engine_version") != SHARP_TARGET_VERSION
        ):
            raise DesignImageDerivativeError("Sharp runtime version evidence is invalid")
        return {
            "engine": "sharp",
            "engine_version": SHARP_TARGET_VERSION,
            "node_version": version,
            "libvips_version": str(evidence.get("libvips_version") or "")[:40],
        }

    def render(
        self,
        *,
        source_body: bytes,
        source_format: str,
        source_checksum: str,
        spec: SharpDerivativeSpec,
    ) -> SharpDerivativeResult:
        if source_format not in _ALLOWED_FORMATS:
            raise DesignImageDerivativeError("derivative source format is unsupported")
        if not source_body or len(source_body) > int(settings.MEDIA_MAX_OBJECT_BYTES):
            raise DesignImageDerivativeError("derivative source size is outside the governed range")
        digest = hashlib.sha256(source_body).hexdigest()
        if digest != source_checksum:
            raise DesignImageDerivativeError("derivative source checksum verification failed")
        try:
            _inspect_raster(source_body, source_format)
        except DesignImageExecutionError as exc:
            raise DesignImageDerivativeError("derivative source raster verification failed") from exc
        self.temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.temp_root, 0o700)
        except OSError as exc:
            raise DesignImageDerivativeError("derivative temporary root cannot be secured") from exc
        with tempfile.TemporaryDirectory(prefix="phase36e-", dir=self.temp_root) as workdir_raw:
            workdir = Path(workdir_raw)
            source_path = workdir / f"source{_SUFFIXES[source_format]}"
            output_path = workdir / f"output{_SUFFIXES[spec.output_format]}"
            source_path.write_bytes(source_body)
            os.chmod(source_path, 0o600)
            command = [
                self.node_binary,
                str(self.script_path),
                "--input",
                str(source_path),
                "--output",
                str(output_path),
                "--width",
                str(spec.width),
                "--height",
                str(spec.height),
                "--format",
                spec.output_format,
                "--fit",
                spec.fit,
                "--position",
                spec.position,
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=_child_env(),
                )
            except subprocess.TimeoutExpired as exc:
                raise DesignImageDerivativeError("Sharp derivative execution timed out") from exc
            except (OSError, subprocess.CalledProcessError) as exc:
                raise DesignImageDerivativeError("Sharp derivative execution failed") from exc
            try:
                metadata = json.loads(completed.stdout)
            except (json.JSONDecodeError, TypeError) as exc:
                raise DesignImageDerivativeError("Sharp derivative receipt is invalid") from exc
            if not isinstance(metadata, dict) or metadata.get("engine") != "sharp":
                raise DesignImageDerivativeError("Sharp derivative receipt is invalid")
            if metadata.get("engine_version") != SHARP_TARGET_VERSION:
                raise DesignImageDerivativeError("Sharp derivative version evidence is invalid")
            if metadata.get("output_format") != spec.output_format:
                raise DesignImageDerivativeError("Sharp derivative output format evidence is invalid")
            try:
                output_body = output_path.read_bytes()
            except OSError as exc:
                raise DesignImageDerivativeError("Sharp derivative output is unavailable") from exc
            if not output_body or len(output_body) > int(settings.MEDIA_MAX_OBJECT_BYTES):
                raise DesignImageDerivativeError("derivative output size is outside the governed range")
            try:
                width, height = _inspect_raster(output_body, spec.output_format)
            except DesignImageExecutionError as exc:
                raise DesignImageDerivativeError("Sharp derivative output raster verification failed") from exc
            if width != spec.width or height != spec.height:
                raise DesignImageDerivativeError("Sharp derivative output dimensions do not match the plan")
            output_sha = hashlib.sha256(output_body).hexdigest()
            command_contract = json.dumps(
                {
                    "engine": "sharp",
                    "engine_version": SHARP_TARGET_VERSION,
                    "input_sha256": digest,
                    **spec.canonical(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            safe_metadata = {
                key: metadata.get(key)
                for key in (
                    "engine",
                    "engine_version",
                    "input_format",
                    "input_width",
                    "input_height",
                    "input_has_alpha",
                    "output_format",
                    "output_width",
                    "output_height",
                    "output_has_alpha",
                    "output_size",
                    "fit",
                    "position",
                )
            }
            return SharpDerivativeResult(
                body=output_body,
                content_type=_CONTENT_TYPES[spec.output_format],
                width=width,
                height=height,
                output_format=spec.output_format,
                sha256=output_sha,
                size_bytes=len(output_body),
                input_sha256=digest,
                command_hash=hashlib.sha256(command_contract).hexdigest(),
                engine_version=SHARP_TARGET_VERSION,
                metadata=safe_metadata,
            )
