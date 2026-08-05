#!/usr/bin/env python3
"""Validate the Linux-preparable iOS source package without Xcode or signing."""

from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS_ROOT = ROOT / "mobile" / "ios"
APP_ROOT = IOS_ROOT / "AIONEXAIOS"
ICON_ROOT = APP_ROOT / "Resources" / "Assets.xcassets" / "AppIcon.appiconset"


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    required = (
        IOS_ROOT / "project.yml",
        APP_ROOT / "AIONEXAIOSApp.swift",
        APP_ROOT / "PortalView.swift",
        APP_ROOT / "AIONEXAIOS.entitlements",
        APP_ROOT / "Resources" / "Web" / "offline.html",
        ICON_ROOT / "Contents.json",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing iOS source files: " + ", ".join(missing))

    project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")
    portal = (APP_ROOT / "PortalView.swift").read_text(encoding="utf-8")
    entitlements = (APP_ROOT / "AIONEXAIOS.entitlements").read_text(encoding="utf-8")
    if "PRODUCT_BUNDLE_IDENTIFIER: net.vipe.aionex" not in project:
        raise SystemExit("iOS bundle identifier is missing")
    if 'URL(string: "https://ai.vip-e.net/ar/")' not in portal:
        raise SystemExit("iOS portal URL is not fixed to the production HTTPS portal")
    if "http://" in portal or "allowsArbitraryLoads" in project:
        raise SystemExit("iOS source permits insecure transport")
    if "applinks:ai.vip-e.net" not in entitlements:
        raise SystemExit("iOS associated-domain entitlement is missing")

    contents = json.loads((ICON_ROOT / "Contents.json").read_text(encoding="utf-8"))
    images = contents.get("images")
    if not isinstance(images, list) or len(images) < 10:
        raise SystemExit("iOS app icon set is incomplete")
    for item in images:
        filename = item.get("filename")
        size = item.get("size")
        scale = item.get("scale")
        if not filename or not size or not scale:
            raise SystemExit("iOS app icon entry is incomplete")
        icon_path = ICON_ROOT / filename
        if not icon_path.is_file():
            raise SystemExit(f"missing iOS icon: {filename}")
        logical = float(str(size).split("x", 1)[0])
        multiplier = int(str(scale).rstrip("x"))
        expected = round(logical * multiplier)
        if png_dimensions(icon_path) != (expected, expected):
            raise SystemExit(f"incorrect iOS icon dimensions: {filename}")

    forbidden = tuple(IOS_ROOT.rglob("*.p12")) + tuple(IOS_ROOT.rglob("*.mobileprovision"))
    if forbidden:
        raise SystemExit("iOS signing material must not be stored in the repository")
    print("IOS_SOURCE_VALIDATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
