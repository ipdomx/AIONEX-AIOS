"""Final consolidated integration validation endpoints."""

from fastapi import APIRouter, Request

from app.core.integration_registry import integration_registry

router = APIRouter()


@router.get("/contracts")
async def integration_contracts(request: Request):
    available_routes = {route.path.removeprefix("/api/v1") for route in request.app.routes if hasattr(route, "path")}
    return integration_registry.validate(available_routes)


@router.get("/readiness")
async def final_readiness(request: Request):
    available_routes = {route.path.removeprefix("/api/v1") for route in request.app.routes if hasattr(route, "path")}
    result = integration_registry.validate(available_routes)
    return {
        "status": "ready" if result["valid"] else "not_ready",
        "integration": result,
    }
