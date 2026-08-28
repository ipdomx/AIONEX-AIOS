"""Build-only narrow compatibility patch for Demucs 4.0.1 on PyTorch 2.6+.

PyTorch 2.6 changed torch.load(..., weights_only=...) to default True. Demucs
4.0.1's trusted official checkpoint loader predates that change and loads a
serialized HTDemucs package. AIONEX pins the checkpoint by exact SHA-256 and
patches only this callsite after verifying the exact upstream source file SHA.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

TARGET = Path("/app/.venv/lib/python3.11/site-packages/demucs/states.py")
EXPECTED_UPSTREAM_SHA256 = (
    "37375543dad61a7dc549caf6f165c0500d903313159c70cf893d47718194b865"
)

source = TARGET.read_text(encoding="utf-8")
observed = hashlib.sha256(source.encode("utf-8")).hexdigest()
if observed != EXPECTED_UPSTREAM_SHA256:
    raise SystemExit(f"unexpected Demucs states.py sha256: {observed}")

old = "            package = torch.load(path, 'cpu')\n"
new = "            package = torch.load(path, 'cpu', weights_only=False)\n"
if source.count(old) != 1:
    raise SystemExit("expected Demucs torch.load callsite not found exactly once")
source = source.replace(old, new, 1)
TARGET.write_text(source, encoding="utf-8")
print("patched_sha256=" + hashlib.sha256(source.encode("utf-8")).hexdigest())
