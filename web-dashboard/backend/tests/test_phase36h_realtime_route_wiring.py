from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import events
from app.services import communications

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_api_lifecycle_starts_realtime_after_redis_and_stops_before_redis(monkeypatch) -> None:
    calls: list[str] = []

    async def mark(name: str) -> None:
        calls.append(name)

    class Runtime:
        async def start(self) -> None:
            await mark("realtime_start")

        async def stop(self) -> None:
            await mark("realtime_stop")

    monkeypatch.setattr(events, "init_db", lambda: mark("db_start"))
    monkeypatch.setattr(events, "init_redis", lambda: mark("redis_start"))
    monkeypatch.setattr(events, "close_db", lambda: mark("db_stop"))
    monkeypatch.setattr(events, "close_redis", lambda: mark("redis_stop"))
    monkeypatch.setattr(events, "realtime_event_runtime", Runtime())

    await events.startup_event()
    await events.shutdown_event()

    assert calls == [
        "db_start",
        "redis_start",
        "realtime_start",
        "realtime_stop",
        "db_stop",
        "redis_stop",
    ]


@pytest.mark.asyncio
async def test_notification_publish_uses_distributed_runtime(monkeypatch) -> None:
    delivered: list[tuple[str, dict]] = []

    class Runtime:
        async def publish(self, tenant_id: str, event: dict) -> None:
            delivered.append((tenant_id, event))

    notification = SimpleNamespace(id="notice-1", organization_id="tenant-a")
    monkeypatch.setattr(communications, "realtime_event_runtime", Runtime())
    monkeypatch.setattr(
        communications,
        "notification_snapshot",
        lambda _notification: {"id": "notice-1"},
    )

    await communications.publish_realtime(notification)  # type: ignore[arg-type]

    assert delivered == [
        (
            "tenant-a",
            {"type": "notification.created", "notification": {"id": "notice-1"}},
        )
    ]


def test_production_realtime_route_no_longer_imports_process_local_ai_hub() -> None:
    websocket_source = (
        ROOT / "web-dashboard/backend/app/api/v1/endpoints/websocket.py"
    ).read_text(encoding="utf-8")
    communications_source = (
        ROOT / "web-dashboard/backend/app/services/communications.py"
    ).read_text(encoding="utf-8")
    runtime_source = (
        ROOT / "web-dashboard/backend/app/realtime/runtime.py"
    ).read_text(encoding="utf-8")

    assert "ai_realtime_hub" not in websocket_source
    assert "ai_realtime_hub" not in communications_source
    assert "RedisRealtimeBackplane" in runtime_source
    assert "DistributedRealtimeHub" in runtime_source
    assert "realtime_event_runtime.connect" in websocket_source
    assert "realtime_event_runtime.disconnect" in websocket_source
    assert "realtime_event_runtime.publish" in communications_source
