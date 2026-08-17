"""Phase 36C automatic model-evidence refresh scheduling contracts."""
from __future__ import annotations

import time

import pytest

from app.core.config import settings
from app.services import operations_observer as observer_module


async def _pilot(_session):
    return {"auto_disarmed": 0}


async def _live(_session):
    return {"executions_marked_manual_review": 0, "pilots_auto_disarmed": 0}


async def _observation(_session):
    return None


async def _lifecycle(_session):
    return []


@pytest.mark.asyncio
async def test_model_refresh_scheduler_is_disabled_by_default_and_interval_bounded(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    published: list[list] = []

    async def fake_refresh(_session):
        calls.append("refresh")
        return {"notifications": ["model-alert"]}

    async def fake_publish(notifications):
        published.append(list(notifications))

    monkeypatch.setattr(observer_module, "reconcile_runtime_pilots", _pilot)
    monkeypatch.setattr(observer_module, "reconcile_stale_live_executions", _live)
    monkeypatch.setattr(observer_module, "record_observation_cycle", _observation)
    monkeypatch.setattr(observer_module, "run_account_lifecycle_alerts", _lifecycle)
    monkeypatch.setattr(observer_module, "refresh_launch_model_evidence", fake_refresh)
    monkeypatch.setattr(observer_module.communications, "publish_many", fake_publish)
    monkeypatch.setattr(settings, "OPERATIONS_OBSERVER_HEALTH_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(settings, "PROJECT_AI_MODEL_REFRESH_ENABLED", False)

    observer = observer_module.OperationsObserver()
    observer.last_lifecycle_alert_monotonic = time.monotonic()
    await observer.run_once()
    assert calls == []

    monkeypatch.setattr(settings, "PROJECT_AI_MODEL_REFRESH_ENABLED", True)
    monkeypatch.setattr(settings, "PROJECT_AI_MODEL_REFRESH_INTERVAL_SECONDS", 3600)
    await observer.run_once()
    assert calls == ["refresh"]
    assert ["model-alert"] in published
    first_refresh = observer.last_project_ai_model_refresh_monotonic
    assert first_refresh > 0

    await observer.run_once()
    assert calls == ["refresh"]
    assert observer.last_project_ai_model_refresh_monotonic == first_refresh
