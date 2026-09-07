#!/usr/bin/env python3
"""Fail closed on committed secrets, private keys, unsafe artifacts, and production debug leaks."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".conf", ".sh", ".md", ".txt", ".env", ".html", ".css",
}
EXCLUDED_PARTS = {".git", "node_modules", ".next", "dist", "build", "coverage", "htmlcov"}
DENY_FILENAMES = {
    ".env", ".env.production", ".env.local", "firebase-admin.json", "service-account.json",
    "id_rsa", "id_ed25519", ".pypirc", "credentials.json",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "openai key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}
PLACEHOLDER_MARKERS = ("replace-with-", "example", "dummy", "changeme", "test-token", "redacted")
ALLOWED_PATTERN_FILES = {
    "openai key": {Path("tests/test_cloud_provider_sandbox.py")},
}

ALLOWED_FAKE_PRIVATE_KEYS = {
    Path("web-dashboard/backend/tests/test_firebase_phone_auth.py"):
        "-----BEGIN PRIVATE KEY-----\\ntest\\n-----END PRIVATE KEY-----",
}

SCHEDULED_AVAILABILITY_TARGETS = (
    ("public-portal", "https://vip-e.net/en/"),
    ("public-api", "https://api.vip-e.net/ready"),
    ("user-portal", "https://ai.vip-e.net/en/"),
)


def scheduled_availability_failures() -> list[str]:
    """Probe production from the off-host GitHub runner on scheduled audits only."""
    if os.environ.get("GITHUB_EVENT_NAME", "").strip().lower() not in {"schedule", "workflow_dispatch"}:
        return []
    failures: list[str] = []
    for label, url in SCHEDULED_AVAILABILITY_TARGETS:
        ok = False
        for attempt in range(3):
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "AIONEX-OffHost-Availability/1.0"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    ok = response.status == 200
            except (OSError, urllib.error.URLError):
                ok = False
            if ok:
                break
            if attempt < 2:
                time.sleep(2)
        if not ok:
            failures.append(label)
    return failures


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env") or path.name in {"Dockerfile", "Makefile"}


def main() -> int:
    findings: list[tuple[str, Path, int | None]] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in DENY_FILENAMES and not path.name.endswith(".example"):
            findings.append(("forbidden tracked file", relative, None))
        if path.suffix.lower() in {".pem", ".p12", ".pfx", ".key", ".keystore", ".jks"}:
            findings.append(("forbidden credential artifact", relative, None))
        if not path.is_file() or not is_text_candidate(path):
            continue
        if path.resolve() == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scan_text = text
        fake_key = ALLOWED_FAKE_PRIVATE_KEYS.get(relative)
        if fake_key:
            scan_text = scan_text.replace(fake_key, "")
        lowered = scan_text.lower()
        for label, pattern in SECRET_PATTERNS.items():
            if relative in ALLOWED_PATTERN_FILES.get(label, set()):
                continue
            for match in pattern.finditer(scan_text):
                window = lowered[max(0, match.start() - 100): match.end() + 100]
                if any(marker in window for marker in PLACEHOLDER_MARKERS):
                    continue
                findings.append((f"possible {label}", relative, scan_text.count(chr(10), 0, match.start()) + 1))
        if path.name in {"next.config.js", "next.config.mjs", "next.config.ts"} and re.search(r"productionBrowserSourceMaps\s*:\s*true", text):
            findings.append(("production browser source maps enabled", relative, None))
        if path.resolve() != SELF:
            compact = text.replace(" ", "")
            if "allow_origins=[\"*\"]" in compact or "allow_origins=['*']" in compact:
                findings.append(("wildcard CORS policy", relative, None))

    availability_failures = scheduled_availability_failures()
    if availability_failures:
        print(
            "Security audit failed: scheduled off-host production availability probe did not pass "
            f"for {len(availability_failures)} target(s).",
            file=sys.stderr,
        )
        return 1
    if findings:
        print(
            f"Security audit failed with {len(set(findings))} finding(s); details are intentionally not logged.",
            file=sys.stderr,
        )
        return 1
    print("Security audit passed: no tracked secret artifacts or forbidden production patterns detected.")
    if os.environ.get("GITHUB_EVENT_NAME", "").strip().lower() in {"schedule", "workflow_dispatch"}:
        print("Off-host production availability probe passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
