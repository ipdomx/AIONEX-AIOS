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


async def _provider_credit(_session):
    return []


async def _runtime_alerts(_session):
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
    monkeypatch.setattr(observer_module, "run_provider_credit_alerts", _provider_credit)
    monkeypatch.setattr(observer_module, "run_runtime_owner_alerts", _runtime_alerts)
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

def _compose_service_block(compose: str, service: str) -> str:
    lines = compose.splitlines()
    marker = f"  {service}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"compose service {service!r} is missing") from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            end = index
            break
    return "\n".join(lines[start + 1 : end])


def test_production_operations_observer_keeps_model_evidence_fresh_without_arming_live_runtime() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = (repo_root / relative).read_text(encoding="utf-8")
        observer = _compose_service_block(compose, "operations-observer")
        assert 'PROJECT_AI_MODEL_REFRESH_ENABLED: "true"' in observer
        assert 'PROJECT_AI_LIVE_RUNTIME_ENABLED: "true"' not in observer
        assert 'AIOS_TELEGRAM_BOT_TOKEN_FILE: /run/operator-secrets/telegram-bot-token' in observer
        assert '/run/operator-secrets/telegram-bot-token:ro' in observer

    dashboard_compose = (repo_root / "web-dashboard/docker-compose.production.yml").read_text(encoding="utf-8")
    assert 'PROJECT_AI_LIVE_RUNTIME_ENABLED: "false"' in dashboard_compose

    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = (repo_root / relative).read_text(encoding="utf-8")
        assert "${AIOS_ENV_FILE:-.env}" not in compose
        assert "${AIOS_ENV_FILE:-.env.production}" in compose
