"""FR-23C probe: runs inside the isolated DAST stack only (http://backend:8000).

Two synthetic tenants (A, B) seeded into an EMPTY database. A creates resources;
B and an anonymous client then try to read and change them through every route
in the app's own OpenAPI document. Also probes the auth-channel boundary and the
media upload validator. Prints one JSON verdict; exit 0 only when no check failed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

BASE = os.environ["DAST_BASE_URL"].rstrip("/")
PUBLIC = {"X-AIOS-Auth-Channel": "public"}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Routes that are public by design (no tenant data) are excluded from the anonymous check.
ANON_ALLOWED_PREFIXES = (
    "/health", "/ready", "/api/v1/billing/catalog/public", "/api/v1/billing/providers/public",
    "/api/v1/auth/free-tier/public", "/api/v1/auth/firebase/", "/api/v1/auth/passkeys/authentication",
    "/api/v1/portal/", "/api/v1/social/media/public/", "/api/v1/studio/identity-media/provider-input/",
    "/api/v1/audio-song-artifacts/", "/api/v1/social/meta/", "/api/v1/billing/webhooks/",
)


def call(method: str, path: str, *, token: str | None = None, data: bytes | None = None,
         content_type: str = "application/json", headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, data=data, method=method)
    for key, value in {**PUBLIC, **(headers or {})}.items():
        request.add_header(key, value)
    if data is not None:
        request.add_header("Content-Type", content_type)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception:  # noqa: BLE001 - a transport failure is recorded, not fatal
        return 0, b""


def as_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        return None


def login(email: str, password: str) -> str:
    status, body = call("POST", "/api/v1/auth/login",
                        data=urllib.parse.urlencode({"username": email, "password": password}).encode(),
                        content_type="application/x-www-form-urlencoded")
    if status != 200:
        raise SystemExit(json.dumps({"status": "FAIL", "reason": f"login {status}"}))
    return as_json(body)["access_token"]


def multipart(field: str, filename: str, content_type: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "fr23c" + uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode()
    return head + payload + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f0e0000000049454e44ae426082")


SETUP: dict[str, int] = {}


def seed_tenant_a(token: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    status, body = call("GET", "/api/v1/auth/me", token=token)
    me = as_json(body) or {}
    SETUP["me"] = status
    ids["user"] = str(me.get("id", ""))
    ids["organization"] = str((me.get("organization") or {}).get("id", "") or me.get("organization_id", ""))
    status, body = call("GET", "/api/v1/projects", token=token)
    SETUP["projects_list"] = status
    rows = as_json(body) or []
    rows = rows.get("items", rows.get("projects", [])) if isinstance(rows, dict) else rows
    if not rows:
        status, body = call("GET", "/api/v1/workspaces", token=token)
        SETUP["workspaces_list"] = status
        spaces = as_json(body) or []
        spaces = spaces.get("items", spaces.get("workspaces", [])) if isinstance(spaces, dict) else spaces
        payload = {"name": "FR-23C tenant A"}
        if spaces:
            payload["workspace_id"] = spaces[0]["id"]
        status, body = call("POST", "/api/v1/projects", token=token, data=json.dumps(payload).encode())
        SETUP["project_create"] = status
        if status in (200, 201):
            rows = [as_json(body)]
    if rows:
        ids["project"] = rows[0]["id"]
        if rows[0].get("workspace_id"):
            ids["workspace"] = rows[0]["workspace_id"]
        status, body = call("POST", "/api/v1/project-conversations", token=token, data=json.dumps(
            {"project_id": ids["project"], "title": "FR-23C tenant A", "request_id": "fr23c-a-conv"}).encode())
        SETUP["conversation_create"] = status
        if status in (200, 201):
            ids["conversation"] = as_json(body)["id"]
    status, body = call("POST", "/api/v1/support/requests", token=token, data=json.dumps(
        {"subject": "FR-23C tenant A", "message": "Isolated DAST tenant A support request."}).encode())
    SETUP["support_create"] = status
    if status in (200, 201):
        ids["support_request"] = str((as_json(body) or {}).get("id", ""))
    payload, ctype = multipart("file", "a.png", "image/png", PNG_1PX)
    status, body = call("POST", "/api/v1/social/media", token=token, data=payload, content_type=ctype)
    SETUP["media_upload"] = status
    if status in (200, 201):
        ids["media"] = str((as_json(body) or {}).get("id", ""))
    status, body = call("POST", "/api/v1/studio/jobs", token=token, data=json.dumps(
        {"department": "text", "title": "FR-23C tenant A", "brief": "Isolated DAST tenant A studio job."}).encode())
    SETUP["studio_job_create"] = status
    if status in (200, 201, 202):
        ids["studio_job"] = str((as_json(body) or {}).get("id", ""))
    return {k: v for k, v in ids.items() if v}


def candidates(param: str, ids: dict[str, str]) -> list[str]:
    name = param.lower()
    for key in ("conversation", "project", "workspace", "organization", "media", "studio_job", "support_request", "user"):
        stem = key.split("_")[0]
        if stem in name:
            return [ids[key]] if key in ids else []
    return sorted(set(ids.values()))


def expand(path: str, ids: dict[str, str]) -> list[str]:
    params = re.findall(r"{([^}]+)}", path)
    if not params or len(params) > 2:
        return []
    out = [path]
    for param in params:
        values = candidates(param, ids)[:6]
        out = [p.replace("{" + param + "}", v, 1) for p in out for v in values]
    return out[:12]


def main() -> int:
    accounts = [json.loads(line) for line in open("/scratch/accounts.jsonl", encoding="utf-8") if line.strip()]
    password = open(os.environ["DAST_PASSWORD_FILE"], encoding="utf-8").read().strip()
    token_a, token_b = login(accounts[0]["email"], password), login(accounts[1]["email"], password)
    ids = seed_tenant_a(token_a)
    spec = json.load(open("/scratch/openapi.json", encoding="utf-8"))
    findings: list[dict[str, Any]] = []
    counts = {"cross_tenant_requests": 0, "anonymous_requests": 0, "routes": 0}

    for path, operations in sorted(spec.get("paths", {}).items()):
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in operations:
                continue
            counts["routes"] += 1
            for concrete in expand(path, ids):
                body = b"{}" if method != "get" else None
                status, response = call(method.upper(), concrete, token=token_b, data=body)
                counts["cross_tenant_requests"] += 1
                leaked = [v for v in ids.values() if v.encode() in response]
                if 200 <= status < 300 and (method != "get" or leaked):
                    findings.append({"check": "cross_tenant", "method": method.upper(), "route": path,
                                     "status": status, "leaked_ids": len(leaked)})
                if method == "get" and not concrete.startswith(ANON_ALLOWED_PREFIXES):
                    anon_status, anon_body = call("GET", concrete)
                    counts["anonymous_requests"] += 1
                    if 200 <= anon_status < 300 and any(v.encode() in anon_body for v in ids.values()):
                        findings.append({"check": "anonymous_read", "route": path, "status": anon_status})

    # Tenant B must still see only its own data in list views.
    for listing in ("/api/v1/projects", "/api/v1/project-conversations", "/api/v1/studio/jobs",
                    "/api/v1/studio/assets", "/api/v1/support/requests", "/api/v1/social/media"):
        status, body = call("GET", listing, token=token_b)
        if status == 200 and any(v.encode() in body for v in ids.values()):
            findings.append({"check": "list_leak", "route": listing})

    # A normal user on the private channel must be refused.
    status, _ = call("GET", "/api/v1/projects", token=token_b, headers={"X-AIOS-Auth-Channel": "private"})
    channel = {"private_channel_status": status}
    if 200 <= status < 300:
        findings.append({"check": "private_channel", "status": status})

    # Upload validator: none of these may be stored.
    uploads = {
        "php_as_jpeg": ("x.jpg", "image/jpeg", b"<?php system($_GET['c']); ?>"),
        "svg_script": ("x.svg", "image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
        "html_as_png": ("x.png", "image/png", b"<html><script>alert(1)</script></html>"),
        "empty": ("x.png", "image/png", b""),
        "oversized_image": ("big.png", "image/png", PNG_1PX + b"\0" * (11 * 1024 * 1024)),
        "path_traversal_name": ("../../etc/passwd.png", "image/png", PNG_1PX),
    }
    upload_results = {}
    for name, (filename, ctype, payload) in uploads.items():
        data, multipart_type = multipart("file", filename, ctype, payload)
        status, body = call("POST", "/api/v1/social/media", token=token_b, data=data, content_type=multipart_type)
        upload_results[name] = status
        stored = 200 <= status < 300
        if stored and name != "path_traversal_name":
            findings.append({"check": "upload_accepted", "case": name, "status": status})
        if stored and name == "path_traversal_name" and b".." in body:
            findings.append({"check": "upload_name_not_sanitized", "status": status})

    # Token for the ZAP API scan (tenant B; only inside the isolated stack).
    with open("/scratch/zap-auth.conf", "w", encoding="utf-8") as stream:
        stream.write(" ".join([
            "-config replacer.full_list(0).description=auth",
            "-config replacer.full_list(0).enabled=true",
            "-config replacer.full_list(0).matchtype=REQ_HEADER",
            "-config replacer.full_list(0).matchstr=Authorization",
            "-config replacer.full_list(0).regex=false",
            f"-config replacer.full_list(0).replacement=Bearer\\ {token_b}",
            "-config replacer.full_list(1).description=channel",
            "-config replacer.full_list(1).enabled=true",
            "-config replacer.full_list(1).matchtype=REQ_HEADER",
            "-config replacer.full_list(1).matchstr=X-AIOS-Auth-Channel",
            "-config replacer.full_list(1).regex=false",
            "-config replacer.full_list(1).replacement=public",
        ]))

    # Coverage gate: the sweep only proves isolation for resources tenant A really owns.
    for required in ("organization", "project", "conversation"):
        if required not in ids:
            findings.append({"check": "coverage", "missing_resource": required})
    result = {"status": "PASS" if not findings else "FAIL", "tenant_a_resources": sorted(ids), "setup": SETUP,
              "counts": counts, "uploads": upload_results, **channel, "findings": findings[:200]}
    print(json.dumps(result, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
