import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user
from app.core.integration_registry import integration_registry
from main import app


WEB_DASHBOARD_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = WEB_DASHBOARD_ROOT / "frontend"
APP_ROOT = FRONTEND_ROOT / "src" / "app"
OWNER_NAVIGATION = FRONTEND_ROOT / "src" / "config" / "owner-navigation.ts"


def _page_routes() -> set[str]:
    routes: set[str] = set()
    for page in APP_ROOT.rglob("page.tsx"):
        relative = page.parent.relative_to(APP_ROOT).as_posix()
        routes.add("/" if relative == "." else f"/{relative}")
    return routes


def _owner_registry_routes() -> list[str]:
    content = OWNER_NAVIGATION.read_text(encoding="utf-8")
    return re.findall(r'href:\s*"(/owner(?:/[^"]*)?)"', content)


def _user(role: str) -> UserRecord:
    return UserRecord(
        id=f"{role.lower().replace(' ', '-')}-test-user",
        email="role-test@aionex.local",
        name="Role Test",
        role=role,
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX",
        organization_plan="enterprise",
        permissions=["*"],
    )


def test_every_owner_page_is_registered_once() -> None:
    owner_pages = {
        route
        for route in _page_routes()
        if route == "/owner" or route.startswith("/owner/")
    }
    registry_routes = _owner_registry_routes()

    assert len(registry_routes) == len(set(registry_routes)), "Duplicate Owner hrefs"
    assert set(registry_routes) == owner_pages


def test_owner_navigation_targets_real_pages_and_required_modules() -> None:
    page_routes = _page_routes()
    owner_page = (APP_ROOT / "owner" / "page.tsx").read_text(encoding="utf-8")
    completion_page = (APP_ROOT / "owner" / "completion" / "page.tsx").read_text(
        encoding="utf-8"
    )
    owner_source = "\n".join(
        page.read_text(encoding="utf-8") for page in (APP_ROOT / "owner").rglob("*.tsx")
    )

    literal_hrefs = re.findall(
        r'href(?:\s*:\s*|=)"([^"]+)"',
        owner_source,
    )
    internal_targets = {
        href.split("?", 1)[0]
        for href in literal_hrefs
        if href.startswith("/") and "[" not in href
    }
    assert not internal_targets.difference(page_routes)
    assert "/owner/system-health" not in owner_source
    assert "ownerNavigationGroups" in owner_page
    assert "ownerNavigationGroups" in completion_page

    required_modules = {
        "/settings",
        "/owner/organizations",
        "/owner/policies",
        "/owner/services",
        "/ai/providers",
        "/owner/notifications",
        "/security/threats",
        "/owner/integrations",
        "/monitoring/metrics",
        "/owner/runtime",
        "/owner/release-governance",
        "/owner/operations",
    }
    assert all(f'href: "{href}"' in owner_page for href in required_modules)


def test_root_layout_uses_dashboard_shell_and_owner_navigation_is_role_aware() -> None:
    root_layout = (APP_ROOT / "layout.tsx").read_text(encoding="utf-8")
    sidebar = (
        FRONTEND_ROOT / "src" / "components" / "layout" / "Sidebar.tsx"
    ).read_text(encoding="utf-8")
    auth_gate = (
        FRONTEND_ROOT / "src" / "components" / "auth" / "AuthGate.tsx"
    ).read_text(encoding="utf-8")

    assert "<DashboardShell>{children}</DashboardShell>" in root_layout
    assert "ownerNavigationGroups" in sidebar
    assert "canAccessOwner" in sidebar
    assert "ownerRoute" in auth_gate
    assert "isOwnerRole" in auth_gate


def test_owner_clients_use_the_authenticated_api_client() -> None:
    owner_clients = sorted((FRONTEND_ROOT / "src" / "lib").glob("owner-*.ts"))

    assert len(owner_clients) == 16
    for client in owner_clients:
        source = client.read_text(encoding="utf-8")
        assert "apiClient" in source, client.name
        assert "fetch(" not in source, client.name
        assert "/api/owner" not in source, client.name
        assert "NEXT_PUBLIC_OWNER" not in source, client.name


def test_owner_shell_session_and_read_only_controls_are_actionable() -> None:
    api_client = (FRONTEND_ROOT / "src" / "lib" / "api-client.ts").read_text(
        encoding="utf-8"
    )
    auth_provider = (
        FRONTEND_ROOT / "src" / "components" / "providers" / "AuthProvider.tsx"
    ).read_text(encoding="utf-8")
    sidebar = (
        FRONTEND_ROOT / "src" / "components" / "layout" / "Sidebar.tsx"
    ).read_text(encoding="utf-8")
    notifications = (
        APP_ROOT / "owner" / "notification-runtime" / "page.tsx"
    ).read_text(encoding="utf-8")
    licensing = (APP_ROOT / "owner" / "licensing" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "AUTH_SESSION_EVENT" in api_client
    assert "AUTH_SESSION_EVENT" in auth_provider
    assert "window.dispatchEvent" in api_client
    assert "if (collapsed) onToggle()" in sidebar
    assert "updateNotificationRule" not in notifications
    assert "Observed rule · read-only" in notifications
    assert 'act(item.id, "renew")' not in licensing
    assert "Renewal unavailable" in licensing


def test_owner_api_routes_are_registered_without_duplicates() -> None:
    expected = {
        ("/owner/platform-integration/snapshot", "GET"),
        ("/owner/platform-integration/command", "POST"),
        ("/owner/operations-integration", "GET"),
        ("/owner/operations-integration/{target_id}/command", "POST"),
        ("/owner/security-integration", "GET"),
        ("/owner/security-integration/{target_id}/command", "POST"),
        ("/owner/final-platform-integration", "GET"),
        ("/owner/final-platform-integration/command", "POST"),
        ("/owner/production-runtime", "GET"),
        ("/owner/production-runtime/command", "POST"),
        ("/owner/runtime", "GET"),
        ("/owner/operations", "POST"),
        ("/owner/approvals", "GET"),
        ("/owner/approvals/{approval_id}", "PATCH"),
        ("/owner/realtime", "GET"),
        ("/owner/releases", "GET"),
        ("/owner/releases/{candidate_id}/decision", "POST"),
        ("/owner/timeline", "GET"),
        ("/owner/compliance-controls", "GET"),
        ("/owner/compliance-controls/{control_id}/attest", "POST"),
        ("/owner/executive", "GET"),
        ("/owner/licenses", "GET"),
        ("/owner/licenses/{license_id}", "PATCH"),
        ("/owner/notification-rules", "GET"),
        ("/owner/notification-rules/{rule_id}", "PATCH"),
        ("/owner/finalization", "GET"),
    }
    registered = [
        (route.path, method)
        for route in api_router.routes
        for method in (getattr(route, "methods", set()) or set())
    ]
    owner_routes = [route for route in registered if route[0].startswith("/owner/")]

    assert len(owner_routes) == len(set(owner_routes)) == len(expected)
    assert expected == set(owner_routes)


def test_final_integration_registry_matches_the_live_application() -> None:
    available_routes = {
        route.path.removeprefix("/api/v1")
        for route in app.routes
        if hasattr(route, "path")
    }
    result = integration_registry.validate(available_routes)
    assert result["valid"], result["missing_routes"]


@pytest.mark.asyncio
async def test_owner_api_rejects_unauthenticated_requests() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/owner/platform-integration/snapshot")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_owner_api_rejects_non_owner_accounts() -> None:
    async def manager_user() -> UserRecord:
        return _user("Manager")

    app.dependency_overrides[current_user] = manager_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/owner/platform-integration/command",
                json={"target_id": "workers", "action": "validate"},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_api_rejects_organization_owner_accounts() -> None:
    async def owner_user() -> UserRecord:
        return _user("Owner")

    app.dependency_overrides[current_user] = owner_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/owner/platform-integration/snapshot")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_api_accepts_super_owner_accounts() -> None:
    async def super_owner_user() -> UserRecord:
        return _user("Super Owner")

    app.dependency_overrides[current_user] = super_owner_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/owner/platform-integration/snapshot")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    assert response.json()["targets"]
