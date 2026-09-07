#!/usr/bin/env python3
"""Generate the authoritative AIONEX release manifest without reading secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _match(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise RuntimeError(f"version contract not found in {path.relative_to(ROOT)}")
    return match.group(1)


def source_manifest() -> dict[str, object]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads((ROOT / "web-dashboard/frontend/package.json").read_text(encoding="utf-8"))
    return {
        "schemaVersion": 1,
        "sourceCommit": _run("git", "rev-parse", "HEAD"),
        "sourceTreeClean": not bool(_run("git", "status", "--porcelain")),
        "components": {
            "core": str(pyproject["project"]["version"]),
            "backend": _match(ROOT / "web-dashboard/backend/app/core/config.py", r'APP_VERSION: str = "([^"]+)"'),
            "ownerFrontend": str(frontend.get("version", "unknown")),
            "android": _match(ROOT / "mobile/android/app/build.gradle", r"AIOS_ANDROID_VERSION_NAME'\) \?: '([^']+)'"),
            "ios": _match(ROOT / "mobile/ios/project.yml", r"MARKETING_VERSION:\s*([^\s]+)"),
        },
        "compose": {
            "webDashboardSha256": _sha256(ROOT / "web-dashboard/docker-compose.production.yml"),
            "deploySha256": _sha256(ROOT / "deploy/production/docker-compose.production.yml"),
        },
    }


def runtime_manifest() -> dict[str, object]:
    names = _run("docker", "ps", "--filter", "label=com.docker.compose.project=web-dashboard", "--format", "{{.Names}}").splitlines()
    images: dict[str, str] = {}
    for name in sorted(filter(None, names)):
        images[name] = _run("docker", "inspect", name, "--format", "{{.Image}}")
    alembic = _run("docker", "exec", "web-dashboard-backend-1", "alembic", "heads").splitlines()
    return {"alembicHeads": alembic, "containerCount": len(images), "containerImageIds": images}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--production-runtime", action="store_true")
    args = parser.parse_args()
    manifest = source_manifest()
    manifest["releaseId"] = args.release_id
    manifest["generatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest["runtime"] = runtime_manifest() if args.production_runtime else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"release_manifest_written={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
