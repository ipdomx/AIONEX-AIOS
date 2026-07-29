"""Final consolidated integration validation endpoints."""

from fastapi import APIRouter, Request

from app.core.integration_registry import integration_registry

router = APIRouter()


def _available_api_routes(request: Request) -> set[str]:
    """Collect routes from both eager and lazy FastAPI router versions."""

    paths: set[str] = set()
    for route in request.app.routes:
        effective_route_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_route_contexts):
            paths.update(
                context.path
                for context in effective_route_contexts()
                if getattr(context, "path", None)
            )
        elif getattr(route, "path", None):
            paths.add(route.path)
    return {path.removeprefix("/api/v1") for path in paths}


@router.get("/contracts")
async def integration_contracts(request: Request):
    return integration_registry.validate(_available_api_routes(request))


@router.get("/readiness")
async def final_readiness(request: Request):
    result = integration_registry.validate(_available_api_routes(request))
    return {
        "status": "ready" if result["valid"] else "not_ready",
        "integration": result,
    }
