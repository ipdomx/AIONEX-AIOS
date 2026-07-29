"""Owner Dashboard navigation, API registration, and authorization contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, require_super_owner

WEB_DASHBOARD = Path(__file__).resolve().parents[2]
FRONTEND = WEB_DASHBOARD / "frontend"
OWNER_APP = FRONTEND / "src" / "app" / "owner"
OWNER_CLIENTS = FRONTEND / "src" / "lib"

OWNER_API_CONTRACT = {
    ("GET", "/api/v1/owner/platform-integration/snapshot"),
    ("POST", "/api/v1/owner/platform-integration/command"),
    ("GET", "/api/v1/owner/operations-integration"),
    ("POST", "/api/v1/owner/operations-integration/{target_id}/command"),
    ("GET", "/api/v1/owner/security-integration"),
    ("POST", "/api/v1/owner/security-integration/{target_id}/command"),
    ("GET", "/api/v1/owner/production-runtime"),
    ("POST", "/api/v1/owner/production-runtime/command"),
    ("GET", "/api/v1/owner/final-platform-integration"),
    ("POST", "/api/v1/owner/final-platform-integration/command"),
}

OWNER_GET_ROUTES = sorted(
    path for method, path in OWNER_API_CONTRACT if method == "GET"
)


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app


def _user(role: str) -> UserRecord:
    return UserRecord(
        id=f"{role.lower().replace(' ', '-')}-id",
        email=f"{role.lower().replace(' ', '-')}@example.com",
        name=role,
        role=role,
        password_hash="unused",
        organization_id="org-1",
        organization_name="Example",
        organization_plan="enterprise",
        permissions=["*"],
    )


def test_owner_navigation_registry_matches_all_owner_pages() -> None:
    page_routes = {
        f"/owner/{page.parent.relative_to(OWNER_APP).as_posix()}"
        for page in OWNER_APP.glob("*/page.tsx")
    }
    assert len(page_routes) == 41

    registry = (FRONTEND / "src" / "config" / "owner-navigation.ts").read_text()
    registry_routes = re.findall(r'href:\s*"(/owner/[^"]+)"', registry)

    assert len(registry_routes) == 41
    assert len(set(registry_routes)) == 41
    assert set(registry_routes) == page_routes


def test_all_literal_owner_links_resolve_and_use_the_registry() -> None:
    valid_routes = {
        "/owner",
        *{
            f"/owner/{page.parent.relative_to(OWNER_APP).as_posix()}"
            for page in OWNER_APP.glob("*/page.tsx")
        },
    }
    literal_links: set[str] = set()
    for source in (FRONTEND / "src").rglob("*"):
        if source.suffix not in {".ts", ".tsx"} or not source.is_file():
            continue
        text = source.read_text()
        literal_links.update(
            re.findall(r'(?:href=|href:)\s*["\'](/owner(?:/[^"\']*)?)["\']', text)
        )

    assert literal_links <= valid_routes
    assert "/owner/system-health" not in literal_links
    assert (
        "ownerNavigationSections"
        in (FRONTEND / "src" / "components" / "layout" / "Sidebar.tsx").read_text()
    )
    assert "ownerNavigationSections" in (OWNER_APP / "page.tsx").read_text()
    assert (
        "ownerNavigationItems"
        in (
            FRONTEND / "src" / "components" / "layout" / "CommandPalette.tsx"
        ).read_text()
    )
    assert (
        "ownerNavigationItems"
        in (FRONTEND / "src" / "components" / "search" / "GlobalSearch.tsx").read_text()
    )


def test_owner_api_contract_is_exact_and_protected() -> None:
    app = _test_app()
    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/owner/")
        for method in route.methods
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }
    assert routes == OWNER_API_CONTRACT

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(
            "/api/v1/owner/"
        ):
            continue
        assert any(
            dependency.call is require_super_owner
            for dependency in route.dependant.dependencies
        ), route.path


@pytest.mark.asyncio
async def test_owner_api_rejects_anonymous_requests() -> None:
    app = _test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for path in OWNER_GET_ROUTES:
            assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["Owner", "Manager"])
async def test_owner_api_rejects_non_global_roles_even_with_wildcard(role: str) -> None:
    app = _test_app()
    app.dependency_overrides[current_user] = lambda: _user(role)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for path in OWNER_GET_ROUTES:
            assert (await client.get(path)).status_code == 403


@pytest.mark.asyncio
async def test_owner_api_accepts_exact_super_owner_role() -> None:
    app = _test_app()
    app.dependency_overrides[current_user] = lambda: _user("Super Owner")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for path in OWNER_GET_ROUTES:
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text)

        response = await client.post(
            "/api/v1/owner/production-runtime/command",
            json={"target_id": "missing-target", "action": "validate"},
        )
        assert response.status_code == 404


def test_owner_clients_are_authenticated_and_do_not_fabricate_fallbacks() -> None:
    clients = sorted(OWNER_CLIENTS.glob("owner-*.ts"))
    assert len(clients) == 16

    combined = "\n".join(client.read_text() for client in clients)
    assert "fetch(" not in combined
    assert "/api/owner" not in combined
    assert "localhost:8000/owner" not in combined
    assert "fallback" not in combined.lower()

    live_clients = {
        "owner-platform-integration.ts": (
            "/owner/platform-integration/snapshot",
            "/owner/platform-integration/command",
        ),
        "owner-operations-integration.ts": (
            "/owner/operations-integration",
            "/owner/operations-integration/${encodeURIComponent(targetId)}/command",
        ),
        "owner-security-integration.ts": (
            "/owner/security-integration",
            "/owner/security-integration/${encodeURIComponent(targetId)}/command",
        ),
        "owner-production-runtime.ts": (
            "/owner/production-runtime",
            "/owner/production-runtime/command",
        ),
        "owner-final-platform-integration.ts": (
            "/owner/final-platform-integration",
            "/owner/final-platform-integration/command",
        ),
    }
    for filename, paths in live_clients.items():
        text = (OWNER_CLIENTS / filename).read_text()
        assert "apiClient." in text
        for path in paths:
            assert path in text


def test_integration_registry_references_live_health_routes() -> None:
    registry = (
        WEB_DASHBOARD / "backend" / "app" / "core" / "integration_registry.py"
    ).read_text()
    assert '"/realtime/status"' in registry
    assert '"/monitoring/health"' in registry
    assert '"/operations/health"' not in registry

    platform_contract = (
        WEB_DASHBOARD / "backend" / "app" / "api" / "owner" / "platform_integration.py"
    ).read_text()
    for route in {
        "/api/v1/integration/health",
        "/api/v1/realtime/status",
        "/api/v1/knowledge",
        "/api/v1/ai/providers",
        "/api/v1/notifications",
    }:
        assert route in platform_contract
    assert "/api/runtime/" not in platform_contract
