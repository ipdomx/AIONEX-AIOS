"""Evidence-based Owner dashboard finalization checks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.integration_registry import integration_registry
from app.integration import aios_bridge

router = APIRouter(prefix="/owner/finalization", tags=["owner-finalization"])

FinalizationCategory = Literal[
    "integration",
    "security",
    "performance",
    "reliability",
    "usability",
]
FinalizationStatus = Literal["passed", "warning", "failed"]


class OwnerFinalizationCheck(BaseModel):
    id: str
    label: str
    category: FinalizationCategory
    status: FinalizationStatus
    details: str


class OwnerFinalizationSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    completion: int = Field(ge=0, le=100)
    checks: list[OwnerFinalizationCheck]


def _available_routes(request: Request) -> set[str]:
    return {
        route.path.removeprefix("/api/v1")
        for route in request.app.routes
        if hasattr(route, "path")
    }


def _dependency_names(route: object) -> set[str]:
    root = getattr(route, "dependant", None)
    if root is None:
        return set()
    names: set[str] = set()
    pending = list(getattr(root, "dependencies", []))
    while pending:
        dependency = pending.pop()
        call = getattr(dependency, "call", None)
        name = getattr(call, "__name__", None)
        if name:
            names.add(name)
        pending.extend(getattr(dependency, "dependencies", []))
    return names


def _owner_routes_are_protected(request: Request) -> tuple[bool, int]:
    owner_routes = [
        route
        for route in request.app.routes
        if str(getattr(route, "path", "")).startswith("/api/v1/owner/")
    ]
    protected = bool(owner_routes) and all(
        "require_super_owner" in _dependency_names(route) for route in owner_routes
    )
    return protected, len(owner_routes)


def _owner_navigation_contract(repo_root: Path) -> tuple[bool, str]:
    app_root = repo_root / "web-dashboard" / "frontend" / "src" / "app"
    owner_root = app_root / "owner"
    navigation_file = (
        repo_root
        / "web-dashboard"
        / "frontend"
        / "src"
        / "config"
        / "owner-navigation.ts"
    )
    if not owner_root.is_dir() or not navigation_file.is_file():
        return False, "Owner frontend sources are unavailable to the backend runtime."

    page_routes = {
        (
            "/owner"
            if page.parent == owner_root
            else f"/owner/{page.parent.relative_to(owner_root).as_posix()}"
        )
        for page in owner_root.rglob("page.tsx")
    }
    navigation_routes = re.findall(
        r'href:\s*"(/owner(?:/[^"]*)?)"',
        navigation_file.read_text(encoding="utf-8"),
    )
    unique_navigation_routes = set(navigation_routes)
    valid = (
        len(navigation_routes) == len(unique_navigation_routes)
        and unique_navigation_routes == page_routes
    )
    if valid:
        return True, f"{len(page_routes)} Owner pages are registered exactly once."

    missing = sorted(page_routes - unique_navigation_routes)
    stale = sorted(unique_navigation_routes - page_routes)
    return (
        False,
        f"Missing navigation: {missing}; stale navigation: {stale}.",
    )


def build_finalization_snapshot(request: Request) -> OwnerFinalizationSnapshot:
    available_routes = _available_routes(request)
    integration_result = integration_registry.validate(available_routes)
    owner_routes_protected, owner_route_count = _owner_routes_are_protected(request)
    aios_status = aios_bridge.initialize()
    navigation_valid, navigation_details = _owner_navigation_contract(
        aios_bridge.repo_root
    )

    checks = [
        OwnerFinalizationCheck(
            id="integration-contracts",
            label="Required integration contracts",
            category="integration",
            status="passed" if integration_result["valid"] else "failed",
            details=(
                "All registered API contracts are available."
                if integration_result["valid"]
                else f"Missing routes: {integration_result['missing_routes']}."
            ),
        ),
        OwnerFinalizationCheck(
            id="owner-route-protection",
            label="Owner API access protection",
            category="security",
            status="passed" if owner_routes_protected else "failed",
            details=(
                f"All {owner_route_count} Owner API routes require Super Owner authorization."
                if owner_routes_protected
                else "At least one Owner API route lacks require_super_owner authorization."
            ),
        ),
        OwnerFinalizationCheck(
            id="performance-evidence",
            label="Dashboard performance evidence",
            category="performance",
            status="warning",
            details="No live performance result store is registered for this runtime.",
        ),
        OwnerFinalizationCheck(
            id="aios-runtime",
            label="AIOS runtime modules",
            category="reliability",
            status="passed" if aios_status.available else "failed",
            details=(
                f"AIOS {aios_status.version} required modules are importable."
                if aios_status.available
                else f"AIOS runtime unavailable: {aios_status.error or 'unknown error'}."
            ),
        ),
        OwnerFinalizationCheck(
            id="owner-navigation",
            label="Owner navigation contract",
            category="usability",
            status="passed" if navigation_valid else "failed",
            details=navigation_details,
        ),
    ]
    weights = {"passed": 100, "warning": 50, "failed": 0}
    completion = round(
        sum(weights[check.status] for check in checks) / max(1, len(checks))
    )
    return OwnerFinalizationSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        completion=completion,
        checks=checks,
    )


@router.get("", response_model=OwnerFinalizationSnapshot)
def get_owner_finalization(request: Request) -> OwnerFinalizationSnapshot:
    return build_finalization_snapshot(request)
