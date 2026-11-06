"""P6 gate 6.4 smoke test, run INSIDE the isolated restore-drill network.

Proves the restored copy is usable, not just present:
  1. /health and /ready of the restored backend (DB + Redis connected)
  2. login with the synthetic restore canary (its Argon2 hash came from the
     backup, so this proves the auth data restored)
  3. list projects and read one by id (tenant-scoped project data restored)
  4. fetch a media asset: a published portal asset (public route) and, when
     DRILL_STUDIO_ASSET_ID is given, the canary's studio asset download
Prints one JSON object; exit 0 only when every required check passed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("DRILL_BASE_URL", "http://backend:8000").rstrip("/")


def call(method: str, path: str, *, token: str | None = None, data: bytes | None = None,
         content_type: str | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, method=method, data=data)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, error.read(64 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def main() -> int:
    checks: dict[str, object] = {}
    checks["health"] = call("GET", "/health")[0]
    checks["ready"] = call("GET", "/ready")[0]
    email = os.environ["DRILL_CANARY_EMAIL"]
    with open(os.environ["DRILL_CANARY_PASSWORD_FILE"], encoding="utf-8") as handle:
        password = handle.read().strip()
    status, body = call("POST", "/api/v1/auth/login",
                        data=urllib.parse.urlencode({"username": email, "password": password}).encode(),
                        content_type="application/x-www-form-urlencoded")
    token = json.loads(body).get("access_token") if status == 200 else None
    checks["canary_login"] = status
    project_status, project_id = 0, None
    if token:
        status, body = call("GET", "/api/v1/projects", token=token)
        rows = json.loads(body) if status == 200 else []
        rows = rows.get("items", []) if isinstance(rows, dict) else rows
        checks["projects_list"] = status
        checks["projects_count"] = len(rows)
        if rows:
            project_id = rows[0].get("id")
            project_status = call("GET", f"/api/v1/projects/{project_id}", token=token)[0]
    checks["project_read"] = project_status
    status, body = call("GET", "/api/v1/portal/published")
    asset_ids = sorted(set(re.findall(r"/portal/assets/([0-9a-f]{32})", body.decode("utf-8", "replace"))))
    checks["portal_published"] = status
    portal_asset = None
    if asset_ids:
        asset_status, asset_body = call("GET", f"/api/v1/portal/assets/{asset_ids[0]}")
        portal_asset = {"status": asset_status, "bytes": len(asset_body)}
    checks["portal_asset"] = portal_asset
    studio_asset = None
    studio_id = os.environ.get("DRILL_STUDIO_ASSET_ID", "").strip()
    if studio_id and token:
        asset_status, asset_body = call("GET", f"/api/v1/studio/assets/{studio_id}/download", token=token)
        studio_asset = {"status": asset_status, "bytes": len(asset_body)}
    checks["studio_asset"] = studio_asset
    media_ok = any(
        isinstance(item, dict) and item.get("status") == 200 and item.get("bytes", 0) > 0
        for item in (portal_asset, studio_asset)
    )
    required = {
        "health": checks["health"] == 200,
        "ready": checks["ready"] == 200,
        "canary_login": checks["canary_login"] == 200,
        "project_read": checks["project_read"] == 200,
        "media_asset_fetch": media_ok,
    }
    result = {"status": "PASS" if all(required.values()) else "FAIL", "required": required, "checks": checks}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
