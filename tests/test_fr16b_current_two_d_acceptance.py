from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TWO_D = ROOT / "src/aios/three_d_web/two_d.py"
HISTORICAL_RECEIPT = ROOT / "docs/phase-36/receipts/36I-2026-08-25-two-d-runtime.md"
CURRENT_RECEIPT = ROOT / "docs/phase-36/receipts/36I-2026-10-18-two-d-continuity.md"

EXPECTED_TWO_D_SHA256 = "9614a1862e93b79980131c5ee213e39d0457e81018cb74fb176b886f64d07e48"


def test_current_two_d_source_matches_executed_continuity_candidate() -> None:
    assert TWO_D.is_file()
    assert hashlib.sha256(TWO_D.read_bytes()).hexdigest() == EXPECTED_TWO_D_SHA256


def test_current_browser_receipt_binds_the_accepted_source_and_scope() -> None:
    assert CURRENT_RECEIPT.is_file()
    text = CURRENT_RECEIPT.read_text(encoding="utf-8").lower()
    for marker in (
        EXPECTED_TWO_D_SHA256, "chromium", "2d-animation", "2d-game",
        "1440", "900", "390", "844", "continuity", "keyboard",
    ):
        assert marker in text


def test_real_browser_acceptance_receipt_remains_present_and_explicit() -> None:
    assert HISTORICAL_RECEIPT.is_file()
    text = HISTORICAL_RECEIPT.read_text(encoding="utf-8").lower()
    for marker in ("chromium", "2d-animation", "2d-game", "webm"):
        assert marker in text
