"""Phase 36C explicit Production runner selection and rollback boundary."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.project_execution import (
    ProjectExecutionConfigurationError,
    ProjectPlanningRunner,
)
from app.services.project_execution_worker import (
    ProjectExecutionWorker,
    resolve_project_execution_runner,
)


ROOT = Path(__file__).resolve().parents[3]


class FakePhase36CRunner:
    def run(self, **_kwargs):
        return {"success": True, "provider": "multi-provider"}


def test_runner_selector_defaults_to_legacy_and_worker_uses_it(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_RUNNER_MODE", "legacy")
    selected = resolve_project_execution_runner()
    assert isinstance(selected, ProjectPlanningRunner)
    worker = ProjectExecutionWorker()
    assert isinstance(worker.runner, ProjectPlanningRunner)


def test_phase36c_mode_fails_closed_without_live_runtime_arm(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROJECT_EXECUTION_RUNNER_MODE", "phase36c")
    monkeypatch.setattr(settings, "PROJECT_AI_LIVE_RUNTIME_ENABLED", False)
    with pytest.raises(ProjectExecutionConfigurationError, match="live-runtime arm gate"):
        resolve_project_execution_runner()
    with pytest.raises(ProjectExecutionConfigurationError, match="live-runtime arm gate"):
        ProjectExecutionWorker()


def test_phase36c_mode_accepts_only_an_explicit_injected_runner() -> None:
    runner = FakePhase36CRunner()
    selected = resolve_project_execution_runner(mode="phase36c", phase36c_runner=runner)
    assert selected is runner
    worker = ProjectExecutionWorker(runner=runner)
    assert worker.runner is runner


def test_unknown_runner_mode_fails_closed() -> None:
    with pytest.raises(ProjectExecutionConfigurationError, match="unsupported ProjectExecution runner mode"):
        resolve_project_execution_runner(mode="unexpected")


def test_production_compose_pins_legacy_runner_in_both_sources() -> None:
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "PROJECT_EXECUTION_RUNNER_MODE: legacy" in text
        assert "PROJECT_EXECUTION_RUNNER_MODE: phase36c" not in text
        assert 'PROJECT_AI_LIVE_RUNTIME_ENABLED: "false"' in text
