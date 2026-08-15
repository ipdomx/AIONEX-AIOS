"""Owner Dashboard navigation, API, persistence, and authorization contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, require_super_owner
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    Organization,
    OwnerCommandRecord,
    OwnerControlRecord,
)
from app.db.seed import seed
from app.services.portal_cms import default_portal_configuration

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
    ("GET", "/api/v1/owner/resources/{domain}"),
    ("POST", "/api/v1/owner/resources/{domain}"),
    (
        "POST",
        "/api/v1/owner/resources/{domain}/{resource_id}/actions",
    ),
    ("POST", "/api/v1/owner/operations"),
    ("GET", "/api/v1/owner/runtime"),
    ("GET", "/api/v1/owner/executive"),
    ("GET", "/api/v1/owner/realtime"),
    ("GET", "/api/v1/owner/timeline"),
    ("GET", "/api/v1/owner/approvals"),
    ("PATCH", "/api/v1/owner/approvals/{approval_id}"),
    ("GET", "/api/v1/owner/communications/overview"),
    ("GET", "/api/v1/owner/communications/telegram/security"),
    ("POST", "/api/v1/owner/communications/telegram/auth-challenge"),
    ("DELETE", "/api/v1/owner/communications/telegram/session"),
    ("GET", "/api/v1/owner/communications/deliveries"),
    (
        "POST",
        "/api/v1/owner/communications/deliveries/{delivery_id}/retry",
    ),
    ("GET", "/api/v1/owner/support/requests"),
    ("GET", "/api/v1/owner/support/requests/{request_id}"),
    (
        "POST",
        "/api/v1/owner/support/requests/{request_id}/messages",
    ),
    ("PATCH", "/api/v1/owner/support/requests/{request_id}"),
    ("DELETE", "/api/v1/owner/support/requests/{request_id}"),
    ("GET", "/api/v1/owner/growth-social/capabilities"),
    ("GET", "/api/v1/owner/growth-social/access"),
    ("GET", "/api/v1/owner/growth-social/meta-targets"),
    ("PUT", "/api/v1/owner/growth-social/access"),
    ("DELETE", "/api/v1/owner/growth-social/access"),
    ("GET", "/api/v1/owner/growth-social/paid-campaigns"),
    ("POST", "/api/v1/owner/growth-social/paid-campaigns/{campaign_id}/approve"),
    ("GET", "/api/v1/owner/growth-social/pilots"),
    ("POST", "/api/v1/owner/growth-social/pilots"),
    ("GET", "/api/v1/owner/growth-social/pilots/{pilot_id}/readiness"),
    ("PATCH", "/api/v1/owner/growth-social/pilots/{pilot_id}/controls"),
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/validate-read-only"),
    (
        "POST",
        "/api/v1/owner/growth-social/pilots/{pilot_id}/authorize-no-spend-write-validation",
    ),
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/authorize-launch"),
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/arm"),
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/disarm"),
    ("GET", "/api/v1/owner/governance/overview"),
    ("GET", "/api/v1/owner/compliance-controls"),
    (
        "POST",
        "/api/v1/owner/compliance-controls/{control_id}/attest",
    ),
    ("GET", "/api/v1/owner/notification-rules"),
    ("PATCH", "/api/v1/owner/notification-rules/{rule_id}"),
    ("GET", "/api/v1/owner/licenses"),
    ("PATCH", "/api/v1/owner/licenses/{license_id}"),
    ("GET", "/api/v1/owner/mobile/readiness"),
    ("GET", "/api/v1/owner/mobile/releases/{release_id}"),
    ("GET", "/api/v1/owner/mobile/releases"),
    (
        "GET",
        "/api/v1/owner/mobile/releases/{release_id}/artifacts/{artifact_id}/download",
    ),
    ("GET", "/api/v1/owner/releases"),
    ("POST", "/api/v1/owner/releases/{candidate_id}/decision"),
    ("POST", "/api/v1/owner/releases/{candidate_id}/evidence"),
    ("GET", "/api/v1/owner/finalization"),
    ("GET", "/api/v1/owner/free-tier"),
    ("PATCH", "/api/v1/owner/free-tier"),
    ("GET", "/api/v1/owner/3d"),
    ("PATCH", "/api/v1/owner/3d"),
    ("GET", "/api/v1/owner/3d/metrics"),
    ("POST", "/api/v1/owner/3d/circuit/reset"),
    ("POST", "/api/v1/owner/3d/cleanup"),
    ("GET", "/api/v1/owner/portal"),
    ("PUT", "/api/v1/owner/portal/draft"),
    ("POST", "/api/v1/owner/portal/publish"),
    ("POST", "/api/v1/owner/portal/rollback/{version}"),
    ("POST", "/api/v1/owner/portal/reset-draft"),
    ("POST", "/api/v1/owner/portal/assets"),
    ("DELETE", "/api/v1/owner/portal/assets/{asset_id}"),
    ("GET", "/api/v1/owner/security-lab"),
    ("PATCH", "/api/v1/owner/security-lab/policy"),
    ("POST", "/api/v1/owner/security-lab/grants"),
    ("POST", "/api/v1/owner/security-lab/grants/{user_id}/revoke"),
    ("GET", "/api/v1/owner/security-lab/findings"),
    ("POST", "/api/v1/owner/security-lab/findings/{finding_id}/decision"),
    ("GET", "/api/v1/owner/security-lab/rules"),
    ("POST", "/api/v1/owner/security-lab/rules/{rule_id}/validate"),
    ("POST", "/api/v1/owner/security-lab/rules/{rule_id}/promote"),
    ("GET", "/api/v1/owner/security-lab/release-gates"),
    ("POST", "/api/v1/owner/security-lab/release-gates"),
    ("GET", "/api/v1/owner/security-lab/eligible-users"),
    ("GET", "/api/v1/owner/security-lab/eligible-projects"),
    ("POST", "/api/v1/owner/security-lab/managed-targets"),
    ("POST", "/api/v1/owner/security-lab/clone-targets"),
    ("GET", "/api/v1/owner/security-lab/scans"),
}

OWNER_GET_ROUTES = sorted(
    path for method, path in OWNER_API_CONTRACT if method == "GET"
)
OWNER_MUTATION_REQUESTS = {
    ("POST", "/api/v1/owner/platform-integration/command"): {
        "action": "validate",
        "target_id": "missing-target",
    },
    ("POST", "/api/v1/owner/operations-integration/{target_id}/command"): {
        "action": "validate",
    },
    ("POST", "/api/v1/owner/security-integration/{target_id}/command"): {
        "action": "validate",
    },
    ("POST", "/api/v1/owner/production-runtime/command"): {
        "target_id": "missing-target",
        "action": "validate",
    },
    ("POST", "/api/v1/owner/final-platform-integration/command"): {
        "target_id": "missing-target",
        "action": "validate",
    },
    ("POST", "/api/v1/owner/resources/{domain}"): {
        "id": "missing-resource",
        "payload": {"name": "Missing resource"},
    },
    (
        "POST",
        "/api/v1/owner/resources/{domain}/{resource_id}/actions",
    ): {
        "action": "toggle",
        "payload": {},
    },
    ("POST", "/api/v1/owner/operations"): {
        "entity": "organization",
        "operation": "create",
        "payload": {"name": "Missing organization"},
    },
    ("PATCH", "/api/v1/owner/approvals/{approval_id}"): {
        "status": "approved",
        "reason": "",
    },
    (
        "POST",
        "/api/v1/owner/communications/deliveries/{delivery_id}/retry",
    ): None,
    ("POST", "/api/v1/owner/communications/telegram/auth-challenge"): None,
    ("DELETE", "/api/v1/owner/communications/telegram/session"): None,
    (
        "POST",
        "/api/v1/owner/support/requests/{request_id}/messages",
    ): {"message": "Owner test reply", "visibility": "requester"},
    ("PATCH", "/api/v1/owner/support/requests/{request_id}"): {
        "status": "in_progress",
        "assigned_to_id": None,
    },
    ("DELETE", "/api/v1/owner/support/requests/{request_id}"): None,
    ("DELETE", "/api/v1/owner/growth-social/access"): None,
    ("POST", "/api/v1/owner/growth-social/paid-campaigns/{campaign_id}/approve"): None,
    ("POST", "/api/v1/owner/growth-social/pilots"): {
        "provider": "meta",
        "provider_scope": "owned_assets",
        "mode": "read_only",
        "owner_approval_reference": "contract-test",
    },
    ("PATCH", "/api/v1/owner/growth-social/pilots/{pilot_id}/controls"): {
        "legal_policy_acknowledged": False,
    },
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/validate-read-only"): None,
    (
        "POST",
        "/api/v1/owner/growth-social/pilots/{pilot_id}/authorize-no-spend-write-validation",
    ): {"reference": "approvalref://contract-no-spend-write"},
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/authorize-launch"): None,
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/arm"): None,
    ("POST", "/api/v1/owner/growth-social/pilots/{pilot_id}/disarm"): {
        "reason": "contract-test",
    },
    (
        "POST",
        "/api/v1/owner/compliance-controls/{control_id}/attest",
    ): None,
    ("PATCH", "/api/v1/owner/notification-rules/{rule_id}"): {
        "enabled": True,
    },
    ("PATCH", "/api/v1/owner/licenses/{license_id}"): {
        "action": "suspend",
    },
    ("PATCH", "/api/v1/owner/free-tier"): {
        "enabled": True,
    },
    ("PATCH", "/api/v1/owner/3d"): {"enabled": True},
    ("POST", "/api/v1/owner/3d/circuit/reset"): None,
    ("POST", "/api/v1/owner/3d/cleanup"): None,
    ("POST", "/api/v1/owner/releases/{candidate_id}/decision"): {
        "decision": "approve",
        "note": "",
    },
    ("POST", "/api/v1/owner/releases/{candidate_id}/evidence"): {
        "event": "deployment",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "image_digests": {},
        "validated": True,
        "note": "contract test",
    },
    ("PUT", "/api/v1/owner/growth-social/access"): {
        "scope": "user",
        "subject_id": "user-1",
        "capability": "campaign.research",
        "allowed": True,
        "approval_required": False,
        "limits": {},
    },
    ("PUT", "/api/v1/owner/portal/draft"): {
        "configuration": default_portal_configuration(),
    },
    ("POST", "/api/v1/owner/portal/publish"): None,
    ("POST", "/api/v1/owner/portal/rollback/{version}"): None,
    ("POST", "/api/v1/owner/portal/reset-draft"): None,
    ("POST", "/api/v1/owner/portal/assets"): {"__files__": True},
    ("DELETE", "/api/v1/owner/portal/assets/{asset_id}"): None,
    ("PATCH", "/api/v1/owner/security-lab/policy"): {"enabled": True},
    ("POST", "/api/v1/owner/security-lab/grants"): {
        "user_id": "missing-user",
        "level": "standard",
    },
    ("POST", "/api/v1/owner/security-lab/grants/{user_id}/revoke"): None,
    ("POST", "/api/v1/owner/security-lab/findings/{finding_id}/decision"): {
        "state": "confirmed",
    },
    ("POST", "/api/v1/owner/security-lab/rules/{rule_id}/validate"): None,
    ("POST", "/api/v1/owner/security-lab/rules/{rule_id}/promote"): None,
    ("POST", "/api/v1/owner/security-lab/release-gates"): {
        "scan_id": "missing-scan",
    },
    ("POST", "/api/v1/owner/security-lab/managed-targets"): {
        "project_id": "missing-project",
        "origin": "https://managed-security.vip-e.net",
        "environment": "staging",
    },
    ("POST", "/api/v1/owner/security-lab/clone-targets"): {
        "source_target_id": "missing-target",
        "origin": "https://security-clone.vip-e.net",
    },
}

NON_DATA_OWNER_PAGES = {"completion", "search", "costs", "licensing"}
OWNER_DATA_SOURCE_MARKERS = (
    "@/hooks/use-owner-resource",
    "@/lib/owner-",
    "@/lib/billing-api",
)
CLIENT_CALL_PATTERN = re.compile(
    r"apiClient\.(get|post|put|patch|delete)" r"(?:<.*?>)?\(\s*([`\"'])(.*?)\2",
    re.DOTALL,
)
INITIAL_ARRAY_PATTERN = re.compile(
    r"\b(?:const|let)\s+initial[A-Za-z0-9_]*" r"\s*(?::[^=]+)?=\s*\[",
    re.DOTALL,
)
TOP_LEVEL_OBJECT_ARRAY_PATTERN = re.compile(
    r"^const\s+([A-Za-z][A-Za-z0-9_]*)" r"\s*(?::[^=]+)?=\s*\[\s*\{",
    re.MULTILINE,
)
STATIC_CONFIGURATION_ARRAY_NAMES = {
    "entities",
    "summaryCards",
    "tabs",
}
BUTTON_PATTERN = re.compile(r"<button\b(?P<attributes>[^>]*)>", re.DOTALL)


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app


def _user(
    role: str,
    *,
    user_id: str | None = None,
    organization_id: str = "org-1",
) -> UserRecord:
    return UserRecord(
        id=user_id or f"{role.lower().replace(' ', '-')}-id",
        email=f"{role.lower().replace(' ', '-')}@example.com",
        name=role,
        role=role,
        password_hash="unused",
        organization_id=organization_id,
        organization_name="Example",
        organization_plan="enterprise",
        permissions=["*"],
    )


def _effective_api_routes(app: FastAPI) -> Iterator[Any]:
    """Yield API routes across old and lazy-inclusion FastAPI releases."""
    for candidate in app.routes:
        route_contexts = getattr(candidate, "effective_route_contexts", None)
        if callable(route_contexts):
            yield from (
                route
                for route in route_contexts()
                if getattr(route, "dependant", None) is not None
            )
        elif isinstance(candidate, APIRoute):
            yield candidate


def _owner_routes(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in _effective_api_routes(app)
        if route.path.startswith("/api/v1/owner/")
        for method in route.methods
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }


def _materialize_route(path: str) -> str:
    values = {
        "domain": "services",
        "target_id": "missing-target",
        "resource_id": "missing-resource",
        "approval_id": "missing-approval",
        "control_id": "missing-control",
        "rule_id": "missing-rule",
        "user_id": "missing-user",
        "finding_id": "missing-finding",
        "license_id": "missing-license",
        "candidate_id": "missing-release",
        "version": "1",
        "asset_id": "0" * 32,
        "delivery_id": "missing-delivery",
        "request_id": "missing-support-request",
    }
    return re.sub(
        r"\{([^}]+)\}",
        lambda match: values.get(match.group(1), "missing"),
        path,
    )


def _path_shape(path: str) -> str:
    without_prefix = path.removeprefix("/api/v1")
    without_templates = re.sub(r"\$\{[^}]+\}", "{}", without_prefix)
    return re.sub(r"\{[^}]+\}", "{}", without_templates)


def _client_api_calls() -> dict[str, set[tuple[str, str]]]:
    calls: dict[str, set[tuple[str, str]]] = {}
    for client in sorted(OWNER_CLIENTS.glob("owner-*.ts")):
        matches = {
            (match.group(1).upper(), _path_shape(match.group(3)))
            for match in CLIENT_CALL_PATTERN.finditer(client.read_text())
        }
        assert matches, f"{client.name} does not call the authenticated API client"
        calls[client.name] = matches
    return calls


def test_owner_navigation_registry_matches_all_owner_pages() -> None:
    page_routes = {
        f"/owner/{page.parent.relative_to(OWNER_APP).as_posix()}"
        for page in OWNER_APP.glob("*/page.tsx")
    }
    assert len(page_routes) == 46

    registry = (FRONTEND / "src" / "config" / "owner-navigation.ts").read_text()
    registry_routes = re.findall(r'href:\s*"(/owner/[^"]+)"', registry)

    assert len(registry_routes) == 46
    assert len(set(registry_routes)) == 46
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


def test_super_owner_sidebar_exposes_only_production_ready_owner_routes() -> None:
    sidebar = (FRONTEND / "src" / "components" / "layout" / "Sidebar.tsx").read_text()
    assert "...baseMainNavSections" not in sidebar
    assert "ownerNavigationSections.map" in sidebar


def test_super_owner_search_surfaces_exclude_legacy_placeholder_routes() -> None:
    command_palette = (
        FRONTEND / "src" / "components" / "layout" / "CommandPalette.tsx"
    ).read_text()
    global_search = (
        FRONTEND / "src" / "components" / "search" / "GlobalSearch.tsx"
    ).read_text()

    assert "...navigationCommands," not in command_palette
    assert "...platformPages," not in global_search
    assert 'command.href === "/settings"' in command_palette
    assert 'page.url === "/settings"' in global_search
    assert "...ownerUtilityCommands" in command_palette
    assert "...ownerUtilityPages" in global_search


def test_every_owner_data_page_uses_a_live_client_without_mock_arrays() -> None:
    failures: list[str] = []
    for page in sorted(OWNER_APP.glob("*/page.tsx")):
        route = page.parent.name
        if route in NON_DATA_OWNER_PAGES:
            continue
        source = page.read_text()
        if not any(marker in source for marker in OWNER_DATA_SOURCE_MARKERS):
            failures.append(f"{route}: no Owner API client or resource hook")
        if INITIAL_ARRAY_PATTERN.search(source):
            failures.append(f"{route}: initial mock array remains")
        unexpected_top_level_arrays = sorted(
            set(TOP_LEVEL_OBJECT_ARRAY_PATTERN.findall(source))
            - STATIC_CONFIGURATION_ARRAY_NAMES
        )
        if unexpected_top_level_arrays:
            failures.append(
                f"{route}: top-level mock data arrays remain: "
                f"{', '.join(unexpected_top_level_arrays)}"
            )
        lowered = source.lower()
        if "this page is under development" in lowered:
            failures.append(f"{route}: placeholder text remains")

    assert not failures, "\n".join(failures)


def test_every_owner_button_has_an_explicit_handler() -> None:
    failures: list[str] = []
    for page in sorted(OWNER_APP.glob("*/page.tsx")):
        source = page.read_text()
        for match in BUTTON_PATTERN.finditer(source):
            attributes = match.group("attributes")
            interactive = (
                re.search(r"\bonClick\s*=", attributes) is not None
                or re.search(r"\btype\s*=\s*[\"']submit[\"']", attributes) is not None
                or re.search(r"\bformAction\s*=", attributes) is not None
            )
            if interactive:
                continue
            line = source.count("\n", 0, match.start()) + 1
            failures.append(f"{page.parent.name}:{line}")

    assert not failures, "Owner buttons without handlers: " + ", ".join(failures)


def test_growth_social_access_console_is_private_and_provider_neutral() -> None:
    dashboard_root = Path(__file__).resolve().parents[2]
    console = (
        dashboard_root
        / "frontend"
        / "src"
        / "components"
        / "owner"
        / "GrowthSocialAccessConsole.tsx"
    ).read_text(encoding="utf-8")
    access_page = (OWNER_APP / "access" / "page.tsx").read_text(encoding="utf-8")
    growth_client = (OWNER_CLIENTS / "owner-growth-social.ts").read_text(
        encoding="utf-8"
    )

    assert "GrowthSocialAccessConsole" in access_page
    assert "@/components/owner/GrowthSocialAccessConsole" in access_page
    for marker in (
        "fetchOwnerGrowthCapabilities",
        "fetchOwnerGrowthAccessOverrides",
        "setOwnerGrowthAccess",
        "clearOwnerGrowthAccess",
        "fetchOwnerRuntimeSnapshot",
        "ads.manage",
        "live-pilot gate",
    ):
        assert marker in console

    assert 'from "@/lib/owner-growth-social"' in console
    assert 'from "@/lib/owner-runtime"' in console
    assert "apiClient" not in console
    assert "fetch(" not in console
    assert "graph.facebook.com" not in console
    assert "Bearer " not in console
    assert "access_token=" not in console
    assert '"/owner/growth-social/access"' in growth_client
    assert "provider mutation or real advertising spend" in console


def test_billing_selector_uses_the_published_backend_catalogue() -> None:
    billing_page = (OWNER_APP / "billing" / "page.tsx").read_text()
    billing_client = (OWNER_CLIENTS / "billing-api.ts").read_text()

    assert "fetchBillingOverview" in billing_page
    assert "overview.catalog.plans.map" in billing_page
    assert "plan.code" in billing_page
    assert "updateBillingAccount" in billing_page
    assert '"/billing/owner/overview"' in billing_client
    assert "supportedPlans" not in billing_page


def test_owner_api_contract_is_complete_and_protected() -> None:
    app = _test_app()
    assert _owner_routes(app) == OWNER_API_CONTRACT
    assert set(OWNER_MUTATION_REQUESTS) == {
        route for route in OWNER_API_CONTRACT if route[0] != "GET"
    }

    for route in _effective_api_routes(app):
        if not route.path.startswith("/api/v1/owner/"):
            continue
        assert any(
            dependency.call is require_super_owner
            for dependency in route.dependant.dependencies
        ), route.path


def test_every_owner_client_call_matches_a_registered_api_route() -> None:
    registered = {(method, _path_shape(path)) for method, path in OWNER_API_CONTRACT}
    calls_by_client = _client_api_calls()
    client_calls = set().union(*calls_by_client.values())

    unexpected = client_calls - registered
    uncovered = registered - client_calls
    assert (
        not unexpected
    ), f"Owner clients call unregistered routes: {sorted(unexpected)}"
    assert not uncovered, f"Owner routes have no frontend client: {sorted(uncovered)}"

    combined = "\n".join(
        client.read_text() for client in sorted(OWNER_CLIENTS.glob("owner-*.ts"))
    )
    assert "fetch(" not in combined
    assert "/api/owner" not in combined
    assert "localhost:8000/owner" not in combined
    # Real provider failover is production behavior; only simulated fallback payloads are forbidden.
    assert "fallbackData" not in combined
    assert "fallbackResponse" not in combined


def _mutation_request_kwargs(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload == {"__files__": True}:
        return {
            "files": {
                "asset": (
                    "owner-logo.png",
                    b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
                    "image/png",
                )
            }
        }
    return {} if payload is None else {"json": payload}


@pytest.mark.asyncio
async def test_owner_api_rejects_anonymous_requests() -> None:
    app = _test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for path in OWNER_GET_ROUTES:
            response = await client.get(_materialize_route(path))
            assert response.status_code == 401, (path, response.text)

        for (method, path), payload in OWNER_MUTATION_REQUESTS.items():
            request_kwargs = _mutation_request_kwargs(payload)
            response = await client.request(
                method,
                _materialize_route(path),
                **request_kwargs,
            )
            assert response.status_code == 401, (method, path, response.text)


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
            response = await client.get(_materialize_route(path))
            assert response.status_code == 403, (path, response.text)

        for (method, path), payload in OWNER_MUTATION_REQUESTS.items():
            request_kwargs = _mutation_request_kwargs(payload)
            response = await client.request(
                method,
                _materialize_route(path),
                **request_kwargs,
            )
            assert response.status_code == 403, (method, path, response.text)


@pytest.mark.asyncio
async def test_owner_mutations_persist_and_create_audit_records() -> None:
    await seed()
    app = _test_app()
    app.dependency_overrides[current_user] = lambda: _user(
        "Super Owner",
        user_id="owner-1",
        organization_id="aionex-org",
    )
    policy_id = f"ci-policy-{uuid4().hex}"
    organization_slug = f"ci-owner-{uuid4().hex}"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/v1/owner/resources/policies",
            json={
                "id": policy_id,
                "payload": {
                    "name": "CI persisted policy",
                    "scope": "global",
                    "status": "draft",
                    "enforcement": "mandatory",
                },
            },
        )
        assert created.status_code == 201, created.text
        assert any(item["id"] == policy_id for item in created.json()["items"])

        paused = await client.post(
            f"/api/v1/owner/resources/policies/{policy_id}/actions",
            json={"action": "pause", "payload": {}},
        )
        assert paused.status_code == 200, paused.text
        policy = next(
            item for item in paused.json()["items"] if item["id"] == policy_id
        )
        assert policy["status"] == "paused"
        assert policy["enabled"] is False

        operation = await client.post(
            "/api/v1/owner/operations",
            json={
                "entity": "organization",
                "operation": "create",
                "payload": {
                    "name": "CI Owner Organization",
                    "slug": organization_slug,
                    "plan": "enterprise",
                },
            },
        )
        assert operation.status_code == 200, operation.text
        assert operation.json()["ok"] is True

    async with SessionLocal() as session:
        persisted_policy = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == "policies",
                OwnerControlRecord.resource_id == policy_id,
            )
        )
        assert persisted_policy is not None
        assert persisted_policy.status == "paused"
        assert persisted_policy.enabled is False

        commands = (
            await session.scalars(
                select(OwnerCommandRecord).where(
                    OwnerCommandRecord.resource_id == policy_id
                )
            )
        ).all()
        assert {command.action for command in commands} >= {"create", "pause"}
        assert all(command.status == "completed" for command in commands)

        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "owner.policies.pause",
                AuditEvent.resource_id == policy_id,
            )
        )
        assert audit is not None

        organization = await session.scalar(
            select(Organization).where(Organization.slug == organization_slug)
        )
        assert organization is not None
        assert organization.status == "active"


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
    assert "_integration_items" in platform_contract
    assert "_TARGETS" not in platform_contract


def test_growth_social_pilot_console_is_private_fail_closed_and_translated() -> None:
    dashboard_root = Path(__file__).resolve().parents[2]
    console = (
        dashboard_root
        / "frontend"
        / "src"
        / "components"
        / "owner"
        / "GrowthSocialPilotConsole.tsx"
    ).read_text(encoding="utf-8")
    integrations_page = (OWNER_APP / "integrations" / "page.tsx").read_text(
        encoding="utf-8"
    )
    growth_client = (OWNER_CLIENTS / "owner-growth-social.ts").read_text(
        encoding="utf-8"
    )
    arabic_check = (
        dashboard_root / "frontend" / "scripts" / "check-owner-arabic-coverage.mjs"
    ).read_text(encoding="utf-8")

    assert "GrowthSocialPilotConsole" in integrations_page
    assert "@/components/owner/GrowthSocialPilotConsole" in integrations_page

    for marker in (
        "fetchOwnerGrowthPilots",
        "fetchOwnerGrowthMetaTargets",
        "fetchOwnerRuntimeSnapshot",
        "fetchOwnerGrowthPilotReadiness",
        "createOwnerGrowthPilot",
        "configureOwnerGrowthPilot",
        "validateOwnerGrowthPilotReadOnly",
        "authorizeOwnerGrowthPilotLaunch",
        "armOwnerGrowthPilot",
        "disarmOwnerGrowthPilot",
        "ready_to_arm",
        "ARM LIVE SPEND",
        "real_spend_allowed",
        "automatic_execution_allowed",
    ):
        assert marker in console

    assert 'from "@/lib/owner-growth-social"' in console
    assert "apiClient" not in console
    assert "fetch(" not in console
    assert "graph.facebook.com" not in console
    assert "Bearer " not in console
    assert "access_token=" not in console
    assert '"daily_budget"' not in console
    assert "'daily_budget'" not in console
    assert '"lifetime_budget"' not in console
    assert "'lifetime_budget'" not in console
    assert "Select active Meta account" in console
    assert "Raw account IDs and credentials" in console
    assert "never returned to this console" in console
    assert "ads_management" in console
    assert "components/owner" in arabic_check

    for path in (
        "/owner/growth-social/meta-targets",
        "/owner/growth-social/pilots",
        "/owner/growth-social/paid-campaigns",
        "/owner/growth-social/pilots/${pilotId}/readiness",
        "/owner/growth-social/pilots/${pilotId}/controls",
        "/owner/growth-social/pilots/${pilotId}/validate-read-only",
        "/owner/growth-social/pilots/${pilotId}/authorize-launch",
        "/owner/growth-social/pilots/${pilotId}/arm",
        "/owner/growth-social/pilots/${pilotId}/disarm",
    ):
        assert path in growth_client


def test_growth_paid_campaign_owner_approval_console_is_private_and_advisory_only() -> (
    None
):
    dashboard_root = Path(__file__).resolve().parents[2]
    console = (
        dashboard_root
        / "frontend"
        / "src"
        / "components"
        / "owner"
        / "GrowthPaidCampaignApprovalConsole.tsx"
    ).read_text(encoding="utf-8")
    integrations_page = (OWNER_APP / "integrations" / "page.tsx").read_text(
        encoding="utf-8"
    )
    growth_client = (OWNER_CLIENTS / "owner-growth-social.ts").read_text(
        encoding="utf-8"
    )

    assert "GrowthPaidCampaignApprovalConsole" in integrations_page
    assert "@/components/owner/GrowthPaidCampaignApprovalConsole" in integrations_page
    for marker in (
        "fetchOwnerGrowthPaidCampaigns",
        "approveOwnerGrowthPaidCampaign",
        "AIOS analyzes the user's chosen campaign values",
        "Approval preserves the user's budget",
        "Approve campaign",
    ):
        assert marker in console

    assert 'from "@/lib/owner-growth-social"' in console
    assert "apiClient" not in console
    assert "fetch(" not in console
    assert "graph.facebook.com" not in console
    assert "Bearer " not in console
    assert "access_token=" not in console
    assert "automatic_execution_allowed" not in console
    assert '"/owner/growth-social/paid-campaigns"' in growth_client
    assert "/owner/growth-social/paid-campaigns/${campaignId}/approve" in growth_client
