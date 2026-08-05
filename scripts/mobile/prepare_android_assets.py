#!/usr/bin/env python3
"""Prepare Next static export for Android AssetManager-safe paths."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "vip-frontend" / "out"
DESTINATION = ROOT / "mobile" / "android" / "generated-web"
TEXT_SUFFIXES = {
    ".html",
    ".txt",
    ".js",
    ".css",
    ".json",
    ".xml",
    ".webmanifest",
    ".svg",
}


def main() -> int:
    if not SOURCE.is_dir() or not (SOURCE / "ar" / "index.html").is_file():
        raise SystemExit("vip-frontend/out is missing; build the static portal first")
    shutil.rmtree(DESTINATION, ignore_errors=True)
    DESTINATION.mkdir(parents=True, mode=0o700)
    for source in sorted(SOURCE.rglob("*")):
        relative = source.relative_to(SOURCE)
        parts = tuple("next-static" if part == "_next" else part for part in relative.parts)
        destination = DESTINATION.joinpath(*parts)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_SUFFIXES or source.name in {".htaccess"}:
            text = source.read_text(encoding="utf-8", errors="strict")
            text = text.replace("/_next/", "/next-static/")
            destination.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(source, destination)
    if (DESTINATION / "_next").exists():
        raise SystemExit("Android asset preparation retained an unsupported _next directory")
    if not (DESTINATION / "next-static" / "static").is_dir():
        raise SystemExit("Android static asset tree is incomplete")
    print(f"ANDROID_WEB_ASSETS={DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
