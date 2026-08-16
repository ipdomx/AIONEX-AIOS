from __future__ import annotations

import importlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_RUNTIME_MODULES = (
    "aios.api_gateway",
    "aios.autonomy_governance",
    "aios.cognitive",
    "aios.controlled_project_builder",
    "aios.controlled_research",
    "aios.distributed_runtime",
    "aios.engineering_platform",
    "aios.full_project_cycle",
    "aios.gateway",
    "aios.government",
    "aios.hr",
    "aios.intelligence",
    "aios.knowledge_learning",
    "aios.meetings_access",
    "aios.mission_control",
    "aios.notifications",
    "aios.payments",
    "aios.plugin_sdk",
    "aios.plugins",
    "aios.release_candidate",
    "aios.security_platform",
    "aios.self_evolution",
    "aios.stable_release",
    "aios.workers",
    "aios.workforce_health",
)


FULL_CYCLE_STAGES = {
    "intake",
    "cognitive_review",
    "constitutional_review",
    "research_verification",
    "wisdom_deliberation",
    "government_review",
    "ministry_routing",
    "workforce_execution",
    "engineering_review",
    "security_review",
    "integration_review",
    "release_review",
    "completed",
}


PORTAL_EXECUTION_KEYS = {
    "title",
    "description",
    "confirm",
    "start",
    "starting",
    "startError",
    "runningNotice",
    "approved",
    "rework",
    "failed",
    "download",
    "downloadError",
    "approve",
    "approving",
    "approvalConfirm",
    "approvalError",
    "ownerApprovalRequired",
    "ownerApproved",
    "newCycle",
    "governanceTitle",
    "governanceComplete",
    "governancePending",
    "researchTitle",
    "researchSummary",
    "workforceTitle",
    "workforceSummary",
    "stage",
}


def test_all_platform_capabilities_are_importable_from_the_single_src_package() -> None:
    legacy = ROOT / "aios"
    assert not legacy.exists() or not list(legacy.rglob("*.py")), (
        "runtime modules must not be split between legacy aios/ and src/aios/"
    )
    for module in REQUIRED_RUNTIME_MODULES:
        imported = importlib.import_module(module)
        assert imported is not None, module


def test_full_cycle_declares_every_required_institutional_stage() -> None:
    from aios.full_project_cycle import FullProjectCycle

    stages = {stage for stage, _ in FullProjectCycle.STAGES}
    assert stages == FULL_CYCLE_STAGES
    progress = [value for _, value in FullProjectCycle.STAGES]
    assert progress == sorted(progress)
    assert progress[-1] == 100


def test_live_backend_connects_full_cycle_builder_worker_and_owner_workforce() -> None:
    runner = (
        ROOT / "web-dashboard/backend/app/services/project_execution.py"
    ).read_text(encoding="utf-8")
    worker = (
        ROOT / "web-dashboard/backend/app/services/project_execution_worker.py"
    ).read_text(encoding="utf-8")
    owner = (
        ROOT / "web-dashboard/backend/app/api/owner/control_plane.py"
    ).read_text(encoding="utf-8")
    endpoint = (
        ROOT
        / "web-dashboard/backend/app/api/v1/endpoints/project_executions.py"
    ).read_text(encoding="utf-8")

    assert "ControlledWebResearch" in runner
    assert "ControlledProjectBuilder" in runner
    assert "FullProjectCycle" in runner
    assert 'execution_id="prototype"' in runner
    assert 'execution_id="cycle"' in runner
    assert 'mode: Literal["full", "planning", "provider_neutral", "3d_full"]' in endpoint
    assert 'provider_neutral = data.mode == "provider_neutral"' in endpoint
    assert (
        'if not provider_neutral and data.confirm_external_processing is not True'
        in endpoint
    )
    assert "download_project_execution" in endpoint
    assert "approve_project_execution" in endpoint
    assert "owner-approval.json" in endpoint
    assert "stage_callback" in worker
    assert 'domain="digital-workforce"' in worker
    assert 'OwnerControlRecord.domain == "digital-workforce"' in owner


def test_normal_user_portal_has_complete_localized_full_cycle_contract() -> None:
    locales = ("ar", "en", "fr", "de", "es", "tr")
    reference_stage_keys: set[str] | None = None
    for locale in locales:
        payload = json.loads(
            (ROOT / f"vip-frontend/src/messages/{locale}.json").read_text(
                encoding="utf-8"
            )
        )
        execution = payload["projects"]["execution"]
        assert PORTAL_EXECUTION_KEYS.issubset(execution), locale
        stage_keys = set(execution["stage"])
        assert FULL_CYCLE_STAGES.issubset(stage_keys), locale
        assert {
            "provider_model_validation",
            "external_research",
            "provider_execution",
            "implementation_specification",
            "implementation_generation",
            "implementation_tests",
            "rollback_verification",
        }.issubset(stage_keys), locale
        if reference_stage_keys is None:
            reference_stage_keys = stage_keys
        else:
            assert stage_keys == reference_stage_keys, locale

    api = (ROOT / "vip-frontend/src/lib/api.ts").read_text(encoding="utf-8")
    page = (
        ROOT / "vip-frontend/src/components/pages/projects-client.tsx"
    ).read_text(encoding="utf-8")
    assert 'mode: "provider_neutral" | "full" | "3d_full" = "full"' in api
    assert 'confirm_external_processing: mode === "full" || mode === "3d_full"' in api
    assert 'provider: "AIOS governed AI runtime"' in page
    assert 'budget: "0.05"' in page
    assert "downloadProjectExecution" in api
    assert "approveProjectExecution" in api
    assert "approveExecution" in page
    assert "ownerApprovalPending" in page
    assert "all_governance_layers_executed" in page
    assert "workforce" in page


def test_production_worker_mounts_single_source_and_retained_evidence() -> None:
    compose = (
        ROOT / "web-dashboard/docker-compose.production.yml"
    ).read_text(encoding="utf-8")
    assert 'profiles: ["ai-execution"]' in compose
    assert "PYTHONPATH: /workspace/src:/app" in compose
    assert "PROJECT_EXECUTION_OUTPUT_ROOT: /var/lib/aionex/project-executions" in compose
    assert "/run/secrets/aionex/project-openai.env:ro" in compose
    assert "/run/references/phase22b/local-qwen3-8b:ro" in compose
