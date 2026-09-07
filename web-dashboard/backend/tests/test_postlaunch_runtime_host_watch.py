"""Post-launch host runtime watcher contracts."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/operations/docker-runtime-watch.py"
SPEC = importlib.util.spec_from_file_location("aionex_runtime_watch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


def component(*, restart: int = 0, healthy: bool = True, container_id: str = "abc") -> dict:
    return {
        "service": "backend",
        "number": "1",
        "container_id": container_id,
        "restart_count": restart,
        "status": "running" if healthy else "exited",
        "health": "healthy" if healthy else None,
        "healthy": healthy,
    }


def test_runtime_watch_baseline_restart_debounce_and_recovery() -> None:
    state, events = watch.reconcile({"version": 1, "components": {}}, {"backend:1": component()})
    assert events == []
    assert state["components"]["backend:1"]["expected"] is True

    state, events = watch.reconcile(state, {"backend:1": component(restart=1)})
    assert [item["event"] for item in events] == ["restart"]
    assert events[0]["restart_count"] == 1

    # First bad poll is deliberately suppressed.
    state, events = watch.reconcile(state, {"backend:1": component(restart=1, healthy=False)})
    assert events == []
    assert state["components"]["backend:1"]["bad_streak"] == 1

    state, events = watch.reconcile(state, {"backend:1": component(restart=1, healthy=False)})
    assert [item["event"] for item in events] == ["unhealthy"]
    assert state["components"]["backend:1"]["alerted_bad"] is True

    state, events = watch.reconcile(state, {"backend:1": component(restart=1, healthy=True)})
    assert [item["event"] for item in events] == ["recovered"]
    assert state["components"]["backend:1"]["alerted_bad"] is False


def test_runtime_watch_recreation_is_not_misreported_as_restart() -> None:
    state, _ = watch.reconcile({"version": 1, "components": {}}, {"backend:1": component()})
    state, events = watch.reconcile(
        state,
        {"backend:1": component(restart=0, healthy=True, container_id="replacement")},
    )
    assert events == []


def test_systemd_watch_is_host_side_and_does_not_mount_docker_socket_into_compose() -> None:
    service = (ROOT / "deploy/systemd/aionex-runtime-watch.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/aionex-runtime-watch.timer").read_text(encoding="utf-8")
    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text(encoding="utf-8")
    assert "docker-runtime-watch.py" in service
    assert "OnUnitActiveSec=60s" in timer
    assert "/var/run/docker.sock" not in compose
    assert "/run/docker.sock" not in compose

CAPACITY_SCRIPT = ROOT / "scripts/operations/host-capacity-guard.py"
CAPACITY_SPEC = importlib.util.spec_from_file_location("aionex_capacity_guard", CAPACITY_SCRIPT)
assert CAPACITY_SPEC is not None and CAPACITY_SPEC.loader is not None
capacity = importlib.util.module_from_spec(CAPACITY_SPEC)
CAPACITY_SPEC.loader.exec_module(capacity)


def _capacity_metrics(**overrides: float) -> dict[str, float]:
    values = {
        "cpu_pct": 20.0,
        "memory_pct": 15.0,
        "disk_pct": 40.0,
        "load_pct": 25.0,
        "network_pct": 5.0,
        "swap_pct": 1.0,
    }
    values.update(overrides)
    return values


def test_capacity_guard_warning_critical_recovery_and_dedupe() -> None:
    state = {"version": 1, "metrics": {}}

    # A single spike never pages the Owner.
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=72.0))
    assert events == []
    assert state["metrics"]["cpu_pct"]["warning_streak"] == 1

    # Three sustained warning observations create exactly one upgrade recommendation.
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=73.0))
    assert events == []
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=74.0))
    assert [item["event"] for item in events] == ["capacity_warning"]
    assert events[0]["metric"] == "cpu_pct"
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=76.0))
    assert events == []

    # Two critical samples escalate once, then dedupe while pressure persists.
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=87.0))
    assert events == []
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=89.0))
    assert [item["event"] for item in events] == ["capacity_critical"]
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=91.0))
    assert events == []

    # Recovery requires three safe samples and also notifies exactly once.
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=40.0))
    assert events == []
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=35.0))
    assert events == []
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=30.0))
    assert [item["event"] for item in events] == ["capacity_recovered"]
    state, events = capacity.reconcile_capacity(state, _capacity_metrics(cpu_pct=25.0))
    assert events == []


def test_capacity_guard_all_thresholds_are_conservative_percentages() -> None:
    assert capacity.THRESHOLDS == {
        "cpu_pct": (70.0, 85.0),
        "memory_pct": (75.0, 85.0),
        "disk_pct": (70.0, 85.0),
        "load_pct": (75.0, 100.0),
        "network_pct": (65.0, 80.0),
        "swap_pct": (20.0, 50.0),
    }
    for metric, (warning, critical) in capacity.THRESHOLDS.items():
        assert capacity.classify(metric, warning - 0.01) == "healthy"
        assert capacity.classify(metric, warning) == "warning"
        assert capacity.classify(metric, critical) == "critical"


def test_systemd_timer_runs_runtime_and_capacity_guards_host_side() -> None:
    service = (ROOT / "deploy/systemd/aionex-runtime-watch.service").read_text(encoding="utf-8")
    assert "docker-runtime-watch.py" in service
    assert "host-capacity-guard.py" in service
    assert "capacity-state.json" in service
    assert "--interface wan0" in service
