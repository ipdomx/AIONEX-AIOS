from __future__ import annotations
try:
    from fastapi import APIRouter
except ImportError:
    APIRouter = None


def build_operations_router(controller):
    if APIRouter is None:
        raise RuntimeError("fastapi is required to build the operations router")
    router = APIRouter(prefix="/operations", tags=["Enterprise Operations"])

    @router.get("/dashboard")
    async def dashboard():
        return await controller.dashboard.dashboard()

    @router.get("/health")
    async def health():
        return await controller.dashboard.health()

    @router.post("/refresh")
    async def refresh():
        await controller.resources.collect()
        return await controller.dashboard.dashboard()

    @router.get("/version")
    async def version():
        return {"component": "Enterprise Operations", "version": "2.3.0-beta.5"}

    return router
