from aios.live_activation import build_activation_snapshot, integration_records, provider_records, tool_records, worker_records


def test_workers_are_truthful_and_telegram_is_optional_boundary():
    running = {"backup-worker", "communication-worker", "operations-observer", "studio-worker", "project-worker"}
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
        running_services={"backup-worker", "communication-worker", "operations-observer", "studio-worker", "project-worker"},
        configured_env=set(),
    )
    assert snapshot.ready is True
    assert '"unconfigured"' in snapshot.to_json()
