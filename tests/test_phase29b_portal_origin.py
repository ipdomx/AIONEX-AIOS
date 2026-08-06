from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vip_frontend_image_uses_public_api_boundary() -> None:
    dockerfile = source("vip-frontend/Dockerfile")
    assert "ARG NEXT_PUBLIC_API_URL=https://api.vip-e.net/api/v1" in dockerfile
    assert "ARG AIOS_BACKEND_ORIGIN=https://api.vip-e.net" in dockerfile
    assert "http://backend:8000" not in dockerfile
    assert "USER nextjs" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile


def test_live_compose_has_a_dedicated_private_portal_origin() -> None:
    compose = source("web-dashboard/docker-compose.production.yml")
    assert "  portal:" in compose
    assert "context: ../vip-frontend" in compose
    assert "NEXT_PUBLIC_API_URL: https://api.vip-e.net/api/v1" in compose
    assert "AIOS_BACKEND_ORIGIN: https://api.vip-e.net" in compose
    assert '"127.0.0.1:${AIOS_PORTAL_PORT:-8082}:8082"' in compose
    assert "portal: {condition: service_healthy}" in compose
    assert "http://127.0.0.1:8082/en/" in compose
    assert "8082:8082" not in compose


def test_portal_listener_is_separate_from_api_and_owner_control() -> None:
    nginx = source("web-dashboard/docker/nginx.conf")
    assert "listen 8080" in nginx
    assert "listen 8081" in nginx
    assert "listen 8082" in nginx
    portal = nginx.split("# Public user portal origin.", 1)[1].split(
        "# Private control plane.", 1
    )[0]
    assert "set $portal_upstream portal:3000" in portal
    assert "proxy_pass http://$portal_upstream" in portal
    assert "location /api/" in portal
    assert "location /ws/" in portal
    assert portal.count("return 404") >= 3
    assert "X-AIOS-Auth-Channel private" not in portal
    assert "X-Robots-Tag" not in portal


def test_ci_builds_the_server_managed_portal_image() -> None:
    workflow = source(".github/workflows/final-validation.yml")
    assert "build backend frontend portal" in workflow
