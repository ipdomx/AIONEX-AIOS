from __future__ import annotations

import pytest

from app.api.owner import production_runtime


@pytest.mark.asyncio
async def test_production_runtime_reports_configured_origins(monkeypatch):
    async def fake_health(_session):
        return [
            {"id": "database", "name": "PostgreSQL", "status": "healthy", "detail": "ok"},
            {"id": "redis", "name": "Redis", "status": "healthy", "detail": "ok"},
            {"id": "backend", "name": "Owner API", "status": "healthy", "detail": "ok"},
        ]

    monkeypatch.setattr(production_runtime, "_health_items", fake_health)
    monkeypatch.setenv("AIOS_PUBLIC_ORIGIN", "https://vip-e.net/")
    monkeypatch.setenv("AIOS_API_ORIGIN", "https://api.vip-e.net/")
    snapshot = await production_runtime._snapshot(object())
    assert snapshot.public_origin == "https://vip-e.net"
    assert snapshot.api_origin == "https://api.vip-e.net"
    assert snapshot.completion == 100


def test_production_runtime_origin_fallbacks_use_live_settings(monkeypatch):
    monkeypatch.delenv("AIOS_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("AIOS_API_ORIGIN", raising=False)
    monkeypatch.setattr(
        production_runtime.settings,
        "CORS_ORIGINS",
        ["http://localhost:3000", "https://vip-e.net", "https://ai.vip-e.net"],
    )
    monkeypatch.setattr(
        production_runtime.settings,
        "PORTAL_PUBLIC_API_ORIGIN",
        "https://api.vip-e.net/",
    )
    assert production_runtime._public_origin() == "https://vip-e.net"
    assert production_runtime._api_origin() == "https://api.vip-e.net"
