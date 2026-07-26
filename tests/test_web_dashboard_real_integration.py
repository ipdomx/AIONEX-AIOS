from pathlib import Path


def test_dashboard_bridge_file_exists() -> None:
    assert Path("web-dashboard/backend/app/integration/aios_bridge.py").exists()


def test_dashboard_router_registers_integration() -> None:
    router = Path("web-dashboard/backend/app/api/v1/router.py").read_text(encoding="utf-8")
    assert "integration.router" in router
    assert 'prefix="/integration"' in router


def test_dashboard_compose_mounts_aios_core() -> None:
    compose = Path("web-dashboard/docker-compose.yml").read_text(encoding="utf-8")
    assert "AIOS_REPO_ROOT=/workspace" in compose
    assert "PYTHONPATH=/workspace/src:/app" in compose
    assert "..:/workspace:ro" in compose
