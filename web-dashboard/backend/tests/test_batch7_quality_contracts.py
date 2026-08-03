# Trusted repository-owner validation trigger for the mobile verification repair.
from app.api.v1.router import api_router
from fastapi import FastAPI
from fastapi.routing import APIRoute


def _registered_routes():
    app = FastAPI()
    app.include_router(api_router)
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


def test_required_runtime_routes_are_registered():
    paths = {route.path for route in _registered_routes()}
    required = {
        "/auth/login",
        "/auth/me",
        "/auth/firebase/phone/public",
        "/auth/firebase/phone/readiness",
        "/auth/free-tier/public",
        "/auth/register/free",
        "/support/requests",
        "/projects",
        "/tasks",
        "/workflows",
        "/meetings",
        "/reports",
        "/ai/agents",
        "/ai/providers",
        "/notifications",
        "/monitoring/metrics",
        "/security/events",
        "/backups",
        "/integration/health",
    }
    missing = required.difference(paths)
    assert not missing, f"Missing required routes: {sorted(missing)}"


def test_no_duplicate_api_paths_and_methods():
    seen: set[tuple[str, str]] = set()
    for route in _registered_routes():
        methods = getattr(route, "methods", set()) or set()
        for method in methods:
            key = (route.path, method)
            assert key not in seen, f"Duplicate route registration: {key}"
            seen.add(key)
