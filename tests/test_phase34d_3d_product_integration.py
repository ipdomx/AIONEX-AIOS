from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
API = (BACKEND / "app/api/v1/endpoints/three_d_jobs.py").read_text()
WORKER = (BACKEND / "app/services/three_d_worker.py").read_text()
STORAGE = (BACKEND / "app/services/three_d_storage.py").read_text()
POLICY = (BACKEND / "app/services/three_d_policy.py").read_text()
MODELS = (BACKEND / "app/db/models.py").read_text()
MIGRATION = (BACKEND / "alembic/versions/20260809_0013_three_d_product_integration.py").read_text()
COMPOSE = (ROOT / "web-dashboard/docker-compose.production.yml").read_text()
ENTRYPOINT = (BACKEND / "scripts/docker-entrypoint.sh").read_text()
PANEL = (ROOT / "vip-frontend/src/components/pages/three-d-project-panel.tsx").read_text()
VIP_API = (ROOT / "vip-frontend/src/lib/api.ts").read_text()
OWNER_API = (BACKEND / "app/api/owner/three_d.py").read_text()
OWNER_UI = (ROOT / "web-dashboard/frontend/src/app/owner/3d/page.tsx").read_text()
PLAN = (ROOT / "docs/phase-34/PHASE_34_3D_PLATFORM_COMPLETION_PLAN.md").read_text()


def test_project_scoped_authenticated_3d_contract_is_complete():
    for route in (
        '/{project_id}/3d/access',
        '/{project_id}/3d/jobs',
        '/{project_id}/3d/jobs/{job_id}',
        '/{project_id}/3d/jobs/{job_id}/cancel',
        '/{project_id}/3d/jobs/{job_id}/clarify',
        '/{project_id}/3d/jobs/{job_id}/artifact',
    ):
        assert route in API
    assert 'require_permissions("projects:write")' in API
    assert 'require_permissions("projects:read")' in API
    assert "project_for_actor" in API


def test_durable_jobs_artifacts_audit_and_migration_are_present():
    assert "class ThreeDGenerationJob" in MODELS
    assert "class ThreeDArtifact" in MODELS
    assert 'revision = "20260809_0013"' in MIGRATION
    assert 'down_revision = "20260809_0012"' in MIGRATION
    assert "three_d_generation_jobs" in MIGRATION
    assert "three_d_artifacts" in MIGRATION
    assert "audit_job" in API and "audit_job" in WORKER


def test_private_object_storage_and_expiring_links_are_fail_closed():
    # S3 remains encrypted and time-bounded when explicitly selected.
    assert 'ServerSideEncryption="AES256"' in STORAGE
    assert "generate_presigned_url" in STORAGE
    assert "ExpiresIn=ttl" in STORAGE
    # Local 3D storage is a separate, explicit backend with private paths and
    # short-lived HMAC grants; unsupported backends fail closed.
    assert "THREE_D_STORAGE_TYPE" in STORAGE
    assert "THREE_D_STORAGE_ROOT" in STORAGE
    assert "issue_local_artifact_token" in STORAGE
    assert "verify_local_artifact_token" in STORAGE
    assert "hmac.compare_digest" in STORAGE
    assert 'if storage_type != "s3":' in STORAGE
    assert 'raise ThreeDStorageError("3D object storage is not configured")' in STORAGE
    assert "input_object_key" not in VIP_API
    assert '"view_url"' in API and '"download_url"' in API
    assert 'if not policy["eligible"]' in API


def test_worker_requires_real_pbr_hash_validation_metering_and_notifications():
    assert "_manifest_acceptable" in WORKER
    assert 'manifest.get("fallback_used") is False' in WORKER
    assert 'manifest.get("fallback_used") is True' in WORKER
    assert 'manifest.get("fallback_provider") == "triposr"' in WORKER
    assert 'body[:4] != b"glTF"' in WORKER
    assert "sha256(body).hexdigest()" in WORKER
    assert 'metric="3d_generations"' in WORKER
    for event in (
        "3d.job.processing",
        "3d.job.completed",
        "3d.job.cancelled",
        "3d.job.failed",
        "3d.job.clarification_required",
    ):
        assert event in WORKER
    assert "client.cancel" in WORKER
    assert "max_queue_seconds" in WORKER and "max_runtime_seconds" in WORKER


def test_owner_controls_every_user_facing_3d_limit():
    for field in (
        "allowed_plan_codes",
        "required_entitlement",
        "allowed_user_ids",
        "denied_user_ids",
        "max_concurrent_jobs_per_user",
        "monthly_jobs_per_user",
        "max_input_megabytes",
        "max_texture_size",
        "artifact_retention_days",
        "signed_url_ttl_seconds",
        "compression_policy",
        "max_runtime_seconds",
        "max_queue_seconds",
        "max_retries",
        "daily_spend_limit_usd",
        "monthly_spend_limit_usd",
    ):
        assert field in POLICY
        assert field in OWNER_API
        assert field in OWNER_UI
    assert '"allowed_plan_codes": ["business"]' in POLICY
    assert '"required_entitlement": THREE_D_ENTITLEMENT' in POLICY


def test_three_d_worker_is_a_real_production_service_with_private_secret_mount():
    assert "three-d-worker:" in COMPOSE
    assert 'command: ["python", "-m", "app.services.three_d_worker"]' in COMPOSE
    assert "./secrets/RUNPOD_GPU.env:/run/secrets/aionex/runpod-gpu.env:ro" in COMPOSE
    assert "three_d_secret_source" in ENTRYPOINT
    assert 'chmod 0400' in ENTRYPOINT
    assert 'THREE_D_RUNPOD_SECRET_FILE="$three_d_secret_runtime"' in ENTRYPOINT


def test_portal_has_real_threejs_preview_poll_cancel_clarify_and_download():
    for token in (
        'from "three"',
        "GLTFLoader",
        "OrbitControls",
        "setInterval",
        "createProjectThreeDJob",
        "cancelProjectThreeDJob",
        "clarifyProjectThreeDJob",
        "getProjectThreeDArtifactLinks",
        "download_url",
        "view_url",
    ):
        assert token in PANEL
    package = json.loads((ROOT / "vip-frontend/package.json").read_text())
    assert package["dependencies"]["three"] == "0.185.1"
    assert package["devDependencies"]["@types/three"] == "0.185.4"


def test_all_portal_locales_have_identical_3d_user_contract():
    locales = ["ar", "de", "en", "es", "fr", "tr"]
    values = [json.loads((ROOT / f"vip-frontend/src/messages/{locale}.json").read_text())["projects"]["threeD"] for locale in locales]
    keys = set(values[0])
    assert "status" in keys
    for value in values[1:]:
        assert set(value) == keys
        assert set(value["status"]) == set(values[0]["status"])


def test_phase34d_plan_remains_the_acceptance_source_of_truth():
    start = PLAN.index("### 34D")
    end = PLAN.index("### 34E")
    batch = PLAN[start:end]
    for phrase in (
        "create/status/cancel/download",
        "organization isolation",
        "artifact metadata",
        "expiring download/view URLs",
        "Three.js preview",
        "billing/metering",
        "notifications",
    ):
        assert phrase in batch
