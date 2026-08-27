"""Build-only import and supply-chain verification."""
from importlib.metadata import PackageNotFoundError, version
import shutil
from pathlib import Path

import demucs
import runpod
import acestep.api_server

from contract import (
    ACE_STEP_MODEL_REVISION,
    DEMUCS_CHECKPOINT_SHA256,
)

assert ACE_STEP_MODEL_REVISION == "e432212fec32b8965a14ffa57ae653438d6abd14"
assert DEMUCS_CHECKPOINT_SHA256 == (
    "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
)
assert version("demucs") == "4.0.1"
assert version("runpod") == "1.11.0"
assert version("diffusers") == "0.38.0"
assert version("orjson") == "3.11.6"
assert version("pillow") == "12.3.0"
assert version("python-multipart") == "0.0.30"
assert version("starlette") == "1.3.1"
for removed in ("setuptools", "wheel"):
    try:
        version(removed)
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError(f"{removed} must not remain in the runtime image")
assert shutil.which("uv") is None and shutil.which("uvx") is None
assert demucs is not None and runpod is not None and acestep.api_server is not None
checkpoints = Path("/app/checkpoints")
assert (checkpoints / "vae" / "diffusion_pytorch_model.safetensors").is_file()
assert (checkpoints / "Qwen3-Embedding-0.6B" / "model.safetensors").is_file()
assert (checkpoints / "acestep-v15-base" / "model.safetensors").is_file()
assert (checkpoints / "acestep-5Hz-lm-4B" / "model.safetensors.index.json").is_file()
patched_precheck = Path(
    "/app/acestep/core/generation/handler/init_service_downloads.py"
).read_text(encoding="utf-8")
assert "Required Qwen3 text encoder is unavailable" in patched_precheck
assert "Required official VAE is unavailable" in patched_precheck
assert "Main model not found, starting auto-download" not in patched_precheck
