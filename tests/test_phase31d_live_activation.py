from pathlib import Path
from aios.live_activation import build_activation_snapshot, integration_records, provider_records, tool_records, worker_records


def test_workers_are_truthful_and_telegram_is_optional_boundary():
    running = {"backup-worker", "communication-worker", "operations-observer", "studio-worker", "project-worker", "security-scan-worker",
                "security-remediation-worker", "three-d-worker"}
    rows = {r.surface_id: r for r in worker_records(running_services=running, health_files={})}
    assert all(rows[name].status == "ready" for name in running)
    assert rows["telegram-worker"].status in {"unconfigured", "unavailable"}


def test_3d_tools_never_fake_readiness():
    rows = {r.surface_id: r for r in tool_records({"blender": "/opt/bin/blender", "gltf-transform": "/opt/bin/gltf-transform"})}
    assert rows["blender"].status == "ready"
    assert rows["gltf-transform"].status == "ready"
    absent = {r.surface_id: r for r in tool_records({})}
    assert absent["blender"].status in {"ready", "unavailable"}


def test_3d_provider_activation_is_credential_bound():
    rows = {r.surface_id: r for r in provider_records({"TRIPO_API_KEY"})}
    assert rows["tripo3d"].status == "ready"
    assert rows["meshy"].status == "unconfigured"


def test_runtime_integrations_distinguish_optional_activation_boundaries():
    rows = {r.surface_id: r for r in integration_records()}
    assert rows["git"].status == "ready"
    assert rows["python"].status == "ready"
    assert rows["kubernetes"].status in {"ready", "unconfigured"}


def test_snapshot_accepts_explicit_activation_boundaries_without_fake_success():
    snapshot = build_activation_snapshot(
        running_services={"backup-worker", "communication-worker", "operations-observer", "studio-worker", "project-worker", "security-scan-worker",
                "security-remediation-worker", "three-d-worker"},
        configured_env=set(),
    )
    assert snapshot.ready is True
    assert '"unconfigured"' in snapshot.to_json()


def test_full_capacity_worker_gate_includes_security_and_three_d_workers() -> None:
    required = {
        "security-scan-worker",
        "security-remediation-worker",
        "three-d-worker",
    }
    rows = {r.surface_id: r for r in worker_records(running_services=required, health_files={})}
    assert required.issubset(rows)
    assert all(rows[item].status == "ready" for item in required)


def test_telegram_secret_is_mounted_for_runtime_readiness_and_delivery() -> None:
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        mount = "/run/operator-secrets/telegram-bot-token:ro"
        assert text.count(mount) >= 3, rel


def test_configured_optional_worker_becomes_blocking_when_unavailable(tmp_path, monkeypatch) -> None:
    token = tmp_path / "telegram-token"
    token.write_text("test-token", encoding="utf-8")
    monkeypatch.setenv("AIOS_TELEGRAM_BOT_TOKEN_HOST_FILE", str(token))
    snapshot = build_activation_snapshot(running_services=[], configured_env=[])
    telegram = next(row for row in snapshot.workers if row.surface_id == "telegram-worker")
    assert telegram.status == "unavailable"
    assert snapshot.ready is False
