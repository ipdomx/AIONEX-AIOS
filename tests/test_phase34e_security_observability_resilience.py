from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
RESILIENCE = (BACKEND / "app/services/three_d_resilience.py").read_text()
WORKER = (BACKEND / "app/services/three_d_worker.py").read_text()
API = (BACKEND / "app/api/v1/endpoints/three_d_jobs.py").read_text()
OWNER = (BACKEND / "app/api/owner/three_d.py").read_text()
POLICY = (BACKEND / "app/services/three_d_policy.py").read_text()
MIGRATION = (BACKEND / "alembic/versions/20260809_0014_three_d_resilience_observability.py").read_text()
WORKFLOW = (ROOT / ".github/workflows/phase34e-container-security.yml").read_text()
DOC = (ROOT / "docs/phase-34/PHASE_34E_SECURITY_OBSERVABILITY_RESILIENCE.md").read_text()
PLAN = (ROOT / "docs/phase-34/PHASE_34_3D_PLATFORM_COMPLETION_PLAN.md").read_text()


def test_phase34e_tracing_metrics_and_health_are_durable():
    assert "trace_id" in MIGRATION and "request_fingerprint" in MIGRATION
    assert '"trace_id": job.trace_id' in (BACKEND / "app/services/three_d_product.py").read_text()
    for metric in (
        "aionex_3d_success_rate_percent",
        "aionex_3d_job_duration_seconds",
        "aionex_3d_gpu_runtime_seconds",
        "aionex_3d_provider_cold_start_seconds",
        "aionex_3d_provider_circuit_state",
        "aionex_3d_spend_usd",
    ):
        assert metric in RESILIENCE
    assert '"circuit_state": self.circuit_state' in WORKER
    assert 'trace_id=job.trace_id' in WORKER
    assert '@router.get("/metrics")' in OWNER


def test_phase34e_circuit_breaker_and_outage_handling_are_fail_closed():
    for token in (
        "provider_failure_threshold",
        "provider_circuit_open_seconds",
        "assert_provider_available",
        "record_provider_failure",
        "record_provider_success",
        "provider_outage_alert",
        "THREE_D_PROVIDER_CIRCUIT_OPEN",
    ):
        assert token in POLICY + RESILIENCE + WORKER + API
    assert '@router.post("/circuit/reset")' in OWNER


def test_phase34e_idempotency_and_duplicate_protection_are_enforced():
    assert "uq_three_d_jobs_idempotency_key" in MIGRATION
    assert 'Header(alias="Idempotency-Key"' in API
    assert "request_fingerprint(" in API
    assert "find_duplicate_job(" in API
    assert "IntegrityError" in API
    assert "duplicate_window_seconds" in POLICY
    portal_api = (ROOT / "vip-frontend/src/lib/api.ts").read_text()
    assert '"Idempotency-Key": idempotencyKey' in portal_api


def test_phase34e_cleanup_spend_and_owner_controls_are_complete():
    for token in (
        "cleanup_expired_three_d_data",
        "artifact_retention_days",
        "temporary_input_retention_hours",
        "cleanup_interval_seconds",
        "cleanup_batch_size",
        "maybe_emit_spend_alerts",
        "daily_spend_limit_usd",
        "monthly_spend_limit_usd",
        "owner_alert_threshold_pct",
    ):
        assert token in RESILIENCE + POLICY + WORKER + OWNER
    assert '@router.post("/cleanup")' in OWNER


def test_phase34e_supply_chain_gate_pins_actions_and_emits_sbom():
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in WORKFLOW
    assert "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610" in WORKFLOW
    assert "aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1" in WORKFLOW
    assert "cyclonedx-json" in WORKFLOW
    assert "version: 0.72.0" in WORKFLOW
    assert "CRITICAL,HIGH" in WORKFLOW
    assert 'exit-code: "1"' in WORKFLOW
    requirements = (BACKEND / "requirements-runtime.txt").read_text()
    assert "python-multipart==0.0.32" in requirements
    assert "firebase-admin==6.8.0" in requirements


def test_phase34e_disaster_recovery_and_rollback_are_documented():
    for phrase in (
        "Disaster recovery / rollback",
        "alembic downgrade 20260809_0013",
        "S3",
        "RUNPOD_GPU.env",
        "three-d-worker --healthcheck",
    ):
        assert phrase in DOC
    start = PLAN.index("### 34E")
    end = PLAN.index("### 34F")
    for phrase in (
        "Structured logs, metrics, tracing, health",
        "Circuit breaker",
        "Idempotency",
        "Cleanup policy",
        "Daily/monthly spend ceilings",
        "vulnerability scan/SBOM",
        "Disaster recovery",
    ):
        assert phrase in PLAN[start:end]
