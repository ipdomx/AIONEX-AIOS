from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TWO_D = ROOT / "src/aios/three_d_web/two_d.py"
HISTORICAL_RECEIPT = ROOT / "docs/phase-36/receipts/36I-2026-08-25-two-d-runtime.md"

EXPECTED_TWO_D_SHA256 = "f992d00c15ca37d0a8156891be2e47b145a0d5e90494f424214ffe35af82241b"



def test_current_two_d_source_is_exact_historically_executed_blob() -> None:
    assert TWO_D.is_file()
    assert hashlib.sha256(TWO_D.read_bytes()).hexdigest() == EXPECTED_TWO_D_SHA256



def test_real_browser_acceptance_receipt_remains_present_and_explicit() -> None:
    assert HISTORICAL_RECEIPT.is_file()
    text = HISTORICAL_RECEIPT.read_text(encoding="utf-8").lower()
    for marker in ("chromium", "2d-animation", "2d-game", "webm"):
        assert marker in text
