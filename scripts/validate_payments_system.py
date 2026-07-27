#!/usr/bin/env python3
"""Static release gate for the complete AIOS payments and billing module."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_GROUPS = {
    "payment core": ("payments", "billing"),
    "providers": ("stripe", "paypal", "paddle"),
    "wallet and usage": ("wallet", "usage"),
    "finance domain": ("invoice", "refund", "coupon", "tax"),
    "local providers": ("paymob", "fawry", "mada", "bank"),
    "administration": ("finance", "health"),
    "security": ("webhook", "signature"),
}

TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".ts", ".tsx", ".js"}


def collect_text() -> str:
    chunks: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", "node_modules", ".venv", "venv"} for part in path.parts):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore").lower())
        except OSError:
            continue
    return "\n".join(chunks)


def main() -> int:
    corpus = collect_text()
    failures: list[str] = []

    for group, terms in REQUIRED_GROUPS.items():
        missing = [term for term in terms if term not in corpus]
        if missing:
            failures.append(f"{group}: missing {', '.join(missing)}")

    review = ROOT / "docs" / "payments" / "FINAL_SYSTEM_REVIEW.md"
    if not review.is_file():
        failures.append("final review document is missing")

    if failures:
        print("Payments final system review failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Payments final system review passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
