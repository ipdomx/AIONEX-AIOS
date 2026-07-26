"""AIOS core integration endpoints for the enterprise web dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.integration import aios_bridge

router = APIRouter()


@router.get("/status")
async def integration_status() -> dict[str, object]:
    status = aios_bridge.initialize()
    return {
        "available": status.available,
        "version": status.version,
        "root": status.root,
        "modules": status.modules,
        "error": status.error,
    }


@router.get("/platforms")
async def platform_status() -> dict[str, object]:
    platforms = aios_bridge.build_platforms()
    result: dict[str, object] = {}
    for name, platform in platforms.items():
        if platform is None:
            result[name] = {"available": False, "ready": False}
            continue
        validator = getattr(platform, "validate", None)
        checks = validator() if callable(validator) else {"ready": True}
        result[name] = {
            "available": True,
            "ready": bool(checks.get("ready", True)),
            "checks": checks,
        }
    return result


@router.get("/health")
async def integration_health() -> dict[str, object]:
    status = aios_bridge.initialize()
    platforms = aios_bridge.build_platforms()
    if not status.available:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AIOS_CORE_UNAVAILABLE",
                "error": status.error,
                "modules": status.modules,
            },
        )
    readiness = {
        name: platform is not None
        and bool(getattr(platform, "validate", lambda: {"ready": True})().get("ready", True))
        for name, platform in platforms.items()
    }
    return {
        "status": "healthy" if all(readiness.values()) else "degraded",
        "version": status.version,
        "platforms": readiness,
    }
