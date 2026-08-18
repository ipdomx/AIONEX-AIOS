#!/usr/bin/env python3
"""Offline Phase 36E Sharp derivative image smoke check for CI/container acceptance."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from app.services.design_image_derivatives import SharpDerivativeRuntime, SharpDerivativeSpec

_SOURCE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAEklEQVQImWMQidoiErWFAUIBAB1GBIlIYWhqAAAAAElFTkSuQmCC"
)


def main() -> int:
    checksum = hashlib.sha256(_SOURCE).hexdigest()
    with tempfile.TemporaryDirectory(prefix="phase36e-sharp-smoke-") as root:
        runtime = SharpDerivativeRuntime(temp_root=Path(root) / "work")
        preflight = runtime.preflight()
        outputs = []
        for output_format in ("png", "webp", "jpeg"):
            result = runtime.render(
                source_body=_SOURCE,
                source_format="png",
                source_checksum=checksum,
                spec=SharpDerivativeSpec(
                    width=96,
                    height=64,
                    output_format=output_format,
                    fit="cover",
                    position="centre",
                ),
            )
            outputs.append(
                {
                    "format": result.output_format,
                    "width": result.width,
                    "height": result.height,
                    "size_bytes": result.size_bytes,
                    "sha256": result.sha256,
                    "command_hash": result.command_hash,
                    "engine_version": result.engine_version,
                }
            )
    print(json.dumps({"preflight": preflight, "outputs": outputs}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
