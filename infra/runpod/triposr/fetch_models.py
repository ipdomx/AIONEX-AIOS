"""Build-time TripoSR model fetch: pinned revisions, SHA-256, safetensors only.

Usage: python fetch_models.py MODEL_ROOT TRIPOSR_REVISION DINO_REVISION
The revisions must match the checksum table below; anything else fails.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import time
import urllib.request

ASSETS = {
    ("stabilityai/TripoSR", "5b521936b01fbe1890f6f9baed0254ab6351c04a"): {
        "config.yaml": (987, "74ca708ce086bf68e97709ea6b3d91f14717921c04691e84043f0eb8fcc68e62"),
        "model.ckpt": (1677246742, "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee"),
    },
    ("facebook/dino-vitb16", "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2"): {
        "config.json": (454, "b87c0270b97db085fd82cf114a761fd0f62ae7914fbd407c752a2260646b689c"),
    },
}
U2NET = (
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    175997641,
    "8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491",
)


def fetch(url: str, target: Path, size: int, digest: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 6):
        hasher, received = sha256(), 0
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "aionex-fr16d-build"}), timeout=120) as response, target.open("wb") as handle:
                while chunk := response.read(8 * 1024 * 1024):
                    received += len(chunk)
                    if received > size:
                        raise ValueError("more bytes than pinned")
                    hasher.update(chunk)
                    handle.write(chunk)
        except (OSError, ValueError) as exc:
            target.unlink(missing_ok=True)
            if attempt == 5:
                raise SystemExit(f"download failed for {target}: {exc}") from exc
            time.sleep(5 * attempt)
            continue
        if received != size or hasher.hexdigest() != digest:
            target.unlink(missing_ok=True)
            raise SystemExit(f"checksum mismatch for {target}")
        return


def main() -> None:
    root, triposr_rev, dino_rev = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    plan = {
        ("stabilityai/TripoSR", triposr_rev): root / "TripoSR",
        ("facebook/dino-vitb16", dino_rev): root / "dino-vitb16",
    }
    for key, dest in plan.items():
        if key not in ASSETS:
            raise SystemExit(f"revision {key} has no pinned checksums")
        for name, (size, digest) in ASSETS[key].items():
            fetch(f"https://huggingface.co/{key[0]}/resolve/{key[1]}/{name}", dest / name, size, digest)
    url, size, digest = U2NET
    fetch(url, root / "rembg" / "u2net.onnx", size, digest)

    import safetensors.torch
    import torch

    checkpoint = root / "TripoSR" / "model.ckpt"
    state = torch.load(checkpoint, map_location="cpu", weights_only=True, mmap=True)
    if not isinstance(state, dict) or not all(isinstance(value, torch.Tensor) for value in state.values()):
        raise SystemExit("TripoSR checkpoint is not a plain tensor state dict")
    safetensors.torch.save_file({key: value.contiguous() for key, value in state.items()}, str(root / "TripoSR" / "model.safetensors"))
    checkpoint.unlink()
    config = root / "TripoSR" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8").replace("facebook/dino-vitb16", str(root / "dino-vitb16")), encoding="utf-8")
    leftovers = [path for path in root.rglob("*") if path.suffix in {".ckpt", ".bin", ".pth", ".pt", ".pkl"}]
    if leftovers:
        raise SystemExit(f"pickle checkpoints left in model tree: {leftovers}")
    print("TripoSR model assets verified and converted to safetensors")


if __name__ == "__main__":
    main()
