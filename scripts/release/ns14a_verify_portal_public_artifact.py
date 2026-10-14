#!/usr/bin/env python3
"""Fail-closed proof that the public Portal serves the exact expected image artifact."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ASSET_RE = re.compile(
    r'''(?:src|href)=["']([^"']*/_next/static/chunks/app/(?:%5B|\[)locale(?:%5D|\])/conversations/page-[0-9a-f]+\.js)["']''',
    re.IGNORECASE,
)


PUBLIC_HOST = "ai.vip-e.net"
MAX_REMOTE_BYTES = 8 * 1024 * 1024
LOCALES = {"ar", "en", "fr", "de", "es", "tr"}


def require_origin(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != PUBLIC_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "\\" in url
    ):
        raise ValueError("unexpected public host or non-HTTPS URL")
    return parsed


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, status, message, headers, newurl):
        require_origin(newurl)
        return super().redirect_request(request, response, status, message, headers, newurl)


def run(argv: list[str]) -> str:
    result = subprocess.run(argv, check=True, text=True, capture_output=True, timeout=20)
    return result.stdout.strip()


def fetch(url: str, timeout: float) -> tuple[int, str, bytes]:
    require_origin(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AIONEX-Portal-Artifact-Identity-Guard/1"},
    )
    opener = urllib.request.build_opener(SameHostRedirects)
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        require_origin(final_url)
        data = response.read(MAX_REMOTE_BYTES + 1)
        if len(data) > MAX_REMOTE_BYTES:
            raise ValueError("public response exceeds permitted bounded size")
        return int(response.status), final_url, data


def extract_conversation_asset(document: str, base_url: str) -> str:
    matches = sorted(set(html.unescape(value) for value in ASSET_RE.findall(document)))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one conversation asset, found {len(matches)}")
    asset_url = urllib.parse.urljoin(base_url, matches[0])
    parsed = require_origin(asset_url)
    if (
        not parsed.path.startswith("/_next/static/chunks/app/")
        or parsed.query
        or ".." in urllib.parse.unquote(parsed.path).split("/")
    ):
        raise ValueError("public conversation asset path invalid")
    return asset_url


def find_internal_conversation_chunk(container: str) -> str:
    listing = run([
        "docker", "exec", container, "find",
        "/app/.next/static/chunks/app", "-type", "f",
    ])
    matches = sorted(
        line for line in listing.splitlines()
        if "/conversations/page-" in line and line.endswith(".js")
    )
    if len(matches) != 1:
        raise ValueError(f"expected exactly one internal conversation chunk, found {len(matches)}")
    return matches[0]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="web-dashboard-portal-1")
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-build-id", required=True)
    parser.add_argument("--expected-route-chunk", required=True)
    parser.add_argument("--expected-route-sha256", required=True)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.container != "web-dashboard-portal-1":
        parser.error("only the AIONEX AIOS production Portal container is accepted")
    if not 1 <= args.timeout <= 30:
        parser.error("HTTP deadline must be between 1 and 30 seconds")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.expected_image_id):
        parser.error("expected image ID must be exact sha256 digest")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", args.expected_build_id):
        parser.error("expected Next BUILD_ID invalid")
    if not re.fullmatch(r"page-[a-f0-9]+\.js", args.expected_route_chunk):
        parser.error("expected route chunk invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", args.expected_route_sha256):
        parser.error("expected route SHA256 invalid")
    parsed = require_origin(args.url)
    pieces = parsed.path.strip("/").split("/")
    if (
        len(pieces) != 2 or pieces[0] not in LOCALES or pieces[1] != "conversations"
        or parsed.query
    ):
        parser.error("only an AIOS public conversation route may be probed")

    checks: dict[str, Any] = {}
    errors: list[str] = []

    try:
        image_id = run(["docker", "inspect", "--format", "{{.Image}}", args.container])
        checks["container_image_id"] = image_id
        checks["container_image_id_match"] = image_id == args.expected_image_id
        if not checks["container_image_id_match"]:
            errors.append("container image id mismatch")
    except Exception as exc:
        errors.append(f"container image inspection failed: {exc}")

    try:
        build_id = run(["docker", "exec", args.container, "cat", "/app/.next/BUILD_ID"])
        checks["container_build_id"] = build_id
        checks["container_build_id_match"] = build_id == args.expected_build_id
        if not checks["container_build_id_match"]:
            errors.append("container build id mismatch")
    except Exception as exc:
        errors.append(f"container build id inspection failed: {exc}")

    try:
        internal_chunk = find_internal_conversation_chunk(args.container)
        internal_basename = Path(internal_chunk).name
        internal_hash_line = run(["docker", "exec", args.container, "sha256sum", internal_chunk])
        internal_sha = internal_hash_line.split()[0]
        checks["internal_route_chunk"] = internal_basename
        checks["internal_route_chunk_match"] = internal_basename == args.expected_route_chunk
        checks["internal_route_sha256"] = internal_sha
        checks["internal_route_sha256_match"] = internal_sha == args.expected_route_sha256
        if not checks["internal_route_chunk_match"]:
            errors.append("internal route chunk name mismatch")
        if not checks["internal_route_sha256_match"]:
            errors.append("internal route chunk hash mismatch")
    except Exception as exc:
        errors.append(f"internal route chunk inspection failed: {exc}")

    try:
        status, final_url, body = fetch(args.url, args.timeout)
        checks["public_document_status"] = status
        checks["public_document_url"] = final_url
        checks["public_document_sha256"] = sha256_bytes(body)
        public_asset_url = extract_conversation_asset(body.decode("utf-8"), final_url)
        public_basename = Path(urllib.parse.urlparse(public_asset_url).path).name
        checks["public_route_asset_url"] = public_asset_url
        checks["public_route_chunk"] = public_basename
        checks["public_route_chunk_match"] = public_basename == args.expected_route_chunk
        if not checks["public_route_chunk_match"]:
            errors.append("public route chunk name mismatch")

        asset_status, asset_final_url, asset_body = fetch(public_asset_url, args.timeout)
        public_sha = sha256_bytes(asset_body)
        checks["public_route_asset_status"] = asset_status
        checks["public_route_asset_final_url"] = asset_final_url
        checks["public_route_sha256"] = public_sha
        checks["public_route_sha256_match"] = public_sha == args.expected_route_sha256
        if not checks["public_route_sha256_match"]:
            errors.append("public route chunk hash mismatch")
    except Exception as exc:
        errors.append(f"public artifact inspection failed: {exc}")

    payload = {
        "schema_version": 1,
        "kind": "portal_public_artifact_identity_guard",
        "container": args.container,
        "url": args.url,
        "expected": {
            "image_id": args.expected_image_id,
            "build_id": args.expected_build_id,
            "route_chunk": args.expected_route_chunk,
            "route_sha256": args.expected_route_sha256,
        },
        "checks": checks,
        "errors": errors,
        "result": "PASS" if not errors else "FAIL_CLOSED",
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        # Do not overwrite a previous release or follow a symlinked evidence path.
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    sys.stdout.write(encoded)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
