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
