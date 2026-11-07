"""Build-time model asset fetch, checksum verification and safetensors conversion.

Runs only inside the ``weights`` build stage (FR-16D). Every file is fetched
from an immutable revision URL and checked against ``weights.lock.json``
(size + SHA-256, taken from the Hugging Face LFS pointers / release assets).
Pickle-format checkpoints are loaded once with ``torch.load(weights_only=True)``
(restricted unpickler, tensors and plain containers only), re-saved as
safetensors, and deleted. The final tree is scanned to prove that no pickle or
torch-zip checkpoint and no Python file reaches the runtime image.

Usage: python fetch_weights.py weights.lock.json /models
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import zipfile

CHUNK = 8 * 1024 * 1024
PICKLE_SUFFIXES = {".ckpt", ".bin", ".pth", ".pt", ".pkl", ".pickle"}


def download(url: str, target: Path, size: int, digest: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 6):
        hasher = sha256()
        received = 0
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "aionex-fr16d-build"})
            with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
                while chunk := response.read(CHUNK):
                    received += len(chunk)
                    if received > size:
                        raise ValueError(f"{target.name}: more bytes than pinned")
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


def _flatten(prefix: str, value: object, out: dict) -> None:
    import torch

    if isinstance(value, torch.Tensor):
        out[prefix] = value
    elif isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), item, out)
    else:
        raise SystemExit(f"unexpected non-tensor entry {prefix!r} ({type(value).__name__})")


def to_safetensors(source: Path, target: Path, *, unwrap: str | None, nested: bool) -> None:
    import safetensors.torch
    import torch

    state = torch.load(source, map_location="cpu", weights_only=True, mmap=True)
    if unwrap is not None:
        state = state[unwrap]
    flat: dict[str, torch.Tensor] = {}
    if nested:
        _flatten("", state, flat)
    else:
        if not isinstance(state, dict):
            raise SystemExit(f"{source.name}: expected a state dict")
        for key, tensor in state.items():
            if not isinstance(tensor, torch.Tensor):
                raise SystemExit(f"{source.name}: non-tensor entry {key!r}")
            flat[str(key)] = tensor
    seen: dict[tuple[int, int, tuple[int, ...]], str] = {}
    for key, tensor in list(flat.items()):
        identity = (tensor.untyped_storage().data_ptr(), tensor.storage_offset(), tuple(tensor.shape))
        flat[key] = tensor.clone().contiguous() if identity in seen else tensor.contiguous()
        seen[identity] = key
    safetensors.torch.save_file(flat, str(target), metadata={"format": "pt", "source_sha256": file_sha256(source)})
    reloaded = safetensors.torch.load_file(str(target), device="cpu")
    if set(reloaded) != set(flat):
        raise SystemExit(f"{target.name}: safetensors round-trip key mismatch")
    source.unlink()


def file_sha256(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def assert_no_pickle(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"symlink in model tree: {path}")
        if not path.is_file():
            continue
        if path.suffix in PICKLE_SUFFIXES or path.suffix == ".py":
            raise SystemExit(f"forbidden file type in model tree: {path}")
        with path.open("rb") as handle:
            head = handle.read(4)
        if head[:1] == b"\x80":
            raise SystemExit(f"pickle stream in model tree: {path}")
        if head == b"PK\x03\x04" and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if any(name.endswith(".pkl") for name in archive.namelist()):
                    raise SystemExit(f"torch zip checkpoint in model tree: {path}")


def main() -> None:
    lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = Path(sys.argv[2])
    for source in lock["sources"]:
        base = source["url"].rstrip("/")
        for item in source["files"]:
            target = root / source["dest"] / item["path"]
            download(f"{base}/{item['path']}", target, int(item["size"]), item["sha256"])
            convert = item.get("convert")
            if convert:
                to_safetensors(
                    target,
                    target.parent / convert["to"],
                    unwrap=convert.get("unwrap"),
                    nested=bool(convert.get("nested")),
                )
    shutil.rmtree(root / ".cache", ignore_errors=True)
    assert_no_pickle(root)
    manifest = {str(path.relative_to(root)): file_sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}
    (root / "MANIFEST.sha256").write_text("".join(f"{digest}  {name}\n" for name, digest in manifest.items()), encoding="utf-8")
    print(f"model assets verified: {len(manifest)} files, no pickle checkpoints")


if __name__ == "__main__":
    main()
