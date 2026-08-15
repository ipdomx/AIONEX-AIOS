from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.v1.router import api_router


def _effective_routes(app: FastAPI):
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


def test_paid_campaign_user_api_has_atomic_advisor_but_no_user_approval_route() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    routes = {
        (method, route.path)
        for route in _effective_routes(app)
        for method in route.methods
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }
    assert (
        "POST",
        "/api/v1/growth-social/paid-campaigns/prepare-and-simulate",
    ) in routes
    assert not any(
        path.startswith("/api/v1/growth-social/paid-campaigns/")
        and path.endswith("/approve")
        for method, path in routes
        if method == "POST"
    )
    assert (
        "POST",
        "/api/v1/owner/growth-social/paid-campaigns/{campaign_id}/approve",
    ) in routes
