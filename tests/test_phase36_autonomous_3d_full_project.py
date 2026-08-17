from pathlib import Path

import pytest

from aios.three_d_web import PerformanceProfile, PerformanceSample, ThreeDRuntimeScaffoldBuilder
from aios.three_d_web.performance import PerformanceGate
from aios.three_d_web.contracts import SceneZone, ThreeDProjectPlanner


ROOT = Path(__file__).resolve().parents[1]


def test_full_3d_mode_is_wired_from_user_api_to_project_worker() -> None:
    endpoint = (ROOT / "web-dashboard/backend/app/api/v1/endpoints/project_executions.py").read_text()
    worker = (ROOT / "web-dashboard/backend/app/services/project_execution_worker.py").read_text()
    runner = (ROOT / "web-dashboard/backend/app/services/project_execution.py").read_text()
    ui = (ROOT / "vip-frontend/src/components/pages/projects-client.tsx").read_text()
    client = (ROOT / "vip-frontend/src/lib/api.ts").read_text()

    assert '"3d_full"' in endpoint
    assert "access_snapshot(session, actor, lock_policy=True)" in endpoint
    assert "project_for_actor(session, actor, project_id, write=True)" in endpoint
    assert "prepare_three_d_assets" in worker
    assert 'payload.get("execution_mode") == "3d_full"' in worker
    assert "ThreeDWebDeliveryBuilder().build" in runner
    assert 'execution_mode != "3d_full"' in runner
    assert "attach_three_d_delivery" in runner
    assert 'startProjectExecution(project.id, "3d_full")' in ui
    assert '"provider_neutral" | "full" | "3d_full"' in client


def test_dedicated_project_worker_contains_real_build_and_browser_runtime() -> None:
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile").read_text()
    requirements = (ROOT / "web-dashboard/backend/requirements-project-worker.txt").read_text()
    entrypoint = (ROOT / "web-dashboard/backend/scripts/docker-entrypoint.sh").read_text()
    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text()
    deploy = (ROOT / "deploy/production/docker-compose.production.yml").read_text()

    assert "FROM runtime AS project-worker" in dockerfile
    for token in ("nodejs", "npm", "chromium", "chromium-chromedriver", "xvfb", "mesa-gl"):
        assert token in dockerfile
    assert "selenium==4.46.0" in requirements
    assert 'project_npm_cache="${PROJECT_EXECUTION_NPM_CACHE:-}"' in entrypoint
    assert 'install -d -m 0700 -o aionex -g aionex "$project_npm_cache"' in entrypoint
    for text in (compose, deploy):
        section = text.split("project-worker:", 1)[1]
        assert "target: project-worker" in section
        assert "aionex-aios-project-worker:local" in section
        assert "project_npm_cache_data:/var/lib/aionex/project-npm-cache" in section


def test_runtime_scaffold_is_locked_self_contained_and_instrumented() -> None:
    blueprint = ThreeDProjectPlanner().plan(
        project_id="phase36-3d",
        title="Phase 36",
        objective="A complete autonomous interactive 3D web project.",
        zones=(SceneZone("hero", "Hero", (0, 0, 0), 5),),
    )
    files = ThreeDRuntimeScaffoldBuilder().build(blueprint).as_mapping()
    assert "package-lock.json" in files
    assert "src/scene/RuntimeProbe.tsx" in files
    assert "src/runtime/profile.ts" in files
    assert "aionex_profile" in files["src/runtime/profile.ts"]
    assert 'profile==="low_power"&&asset.lazy' in files["src/scene/AssetModel.tsx"]
    assert "zone.mobileScale" in files["src/scene/Zone.tsx"]
    assert "__AIOS_3D_READY__" in files["src/scene/RuntimeProbe.tsx"]
    assert "__AIOS_3D_METRICS__" in files["src/scene/RuntimeProbe.tsx"]
    assert "Environment preset" not in files["src/scene/World.tsx"]
    assert "data-zone-id" in files["src/overlays/ContentOverlay.tsx"]


def test_software_browser_timing_is_evidence_not_fake_device_performance() -> None:
    sample = PerformanceSample(
        profile=PerformanceProfile.DESKTOP,
        fps=1.0,
        frame_time_ms=999.0,
        draw_calls=4,
        triangles=500,
        asset_bytes=1024,
        bundle_bytes=1024,
        gpu_memory_mb=16,
        timing_measurement_authoritative=False,
    )
    result = PerformanceGate().evaluate(sample)
    assert result.passed is True

    oversized = PerformanceSample(
        profile=PerformanceProfile.DESKTOP,
        fps=120.0,
        frame_time_ms=8.0,
        draw_calls=4,
        triangles=500,
        asset_bytes=1024,
        bundle_bytes=9 * 1024 * 1024,
        gpu_memory_mb=16,
        timing_measurement_authoritative=False,
    )
    failed = PerformanceGate().evaluate(oversized)
    assert failed.passed is False
    assert any(item.metric == "bundle_bytes" for item in failed.violations)


def test_autonomous_text_to_3d_adapter_is_bounded_and_fail_closed() -> None:
    source = (ROOT / "web-dashboard/backend/app/services/three_d_project_delivery.py").read_text()
    for token in (
        '"model": _TRIPO_MODEL_VERSION',
        '"prompt": _bounded_provider_prompt(prompt)',
        '"face_limit"',
        '"texture": True',
        '"pbr": True',
        "TripoTextToModelClient",
        "_public_https_url",
        "PROJECT_3D_AUTOGEN_ASSET_COUNT",
        "https://openapi.tripo3d.ai/v3",
        "/generation/text-to-model",
        "/account/balance",
        "18 * 1024 * 1024",
        'payload[:4] != b"glTF"',
        'model_payload_suffixes = {".glb", ".gltf"}',
        'low_power_lazy_assets_use_procedural_proxies',
        'low-power-asset-streaming',
        'PROJECT_3D_TRIPO_CREDITS_PER_ASSET',
        'autonomous_asset_generation_status',
        'insufficient_credit',
    ):
        assert token in source
    assert "TRIPO_API_KEY" in source
    assert "content_base64" not in source


def test_full_3d_result_is_exposed_without_secret_or_signed_provider_url() -> None:
    endpoint = (ROOT / "web-dashboard/backend/app/api/v1/endpoints/project_executions.py").read_text()
    types = (ROOT / "vip-frontend/src/types/index.ts").read_text()
    assert '"three_d_web"' in endpoint
    assert "autonomous_asset_generation_used" in types
    assert "asset_providers" in types
    assert "build_manifest_sha256" in types
    assert "autonomous_asset_generation_status" in types
    assert "autonomous_asset_generation_degraded" in types
    assert "threeDAutogenDegraded" in (ROOT / "vip-frontend/src/components/pages/projects-client.tsx").read_text()
    assert "model_url" not in types
