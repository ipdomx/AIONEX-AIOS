from __future__ import annotations

from pathlib import Path

from aios.three_d_web import (
    ApprovalDecision,
    AssetKind,
    BrowserRunReceipt,
    BrowserSpec,
    BrowserSupport,
    EvidenceEntry,
    EvidenceKind,
    LifecycleInputs,
    PerformanceProfile,
    PerformanceSample,
    SceneAsset,
    SceneZone,
    ScenarioResult,
    ThreeDProjectLifecycle,
    ThreeDProjectPlanner,
    ViewportSpec,
)
from aios.three_d_web.visual_qa import checksum_bytes


def _blueprint(with_asset: bool = False):
    assets = (SceneAsset("world", AssetKind.GLTF, "world.gltf"),) if with_asset else ()
    zone_assets = ("world",) if with_asset else ()
    return ThreeDProjectPlanner().plan(
        project_id="demo-3d",
        title="Demo 3D",
        objective="Build a governed 3D experience",
        zones=(SceneZone("home", "Home", (0, 0, 0), 10, asset_ids=zone_assets),),
        assets=assets,
    )


def _runs():
    shot = EvidenceEntry("shot", EvidenceKind.SCREENSHOT, "evidence/shot.png", checksum_bytes(b"shot"))
    scenarios = (
        ScenarioResult("route-home", True),
        ScenarioResult("asset-world", True),
        ScenarioResult("interaction-primary", True),
        ScenarioResult("camera-follow-focus", True),
    )
    return (
        BrowserRunReceipt(BrowserSpec("chromium", "chromium", BrowserSupport.SUPPORTED), ViewportSpec("desktop", 1440, 900), (), (), scenarios, (shot,)),
        BrowserRunReceipt(BrowserSpec("chromium", "chromium", BrowserSupport.SUPPORTED), ViewportSpec("mobile", 390, 844, 3.0, True), (), (), scenarios, (shot,)),
    )


def _samples():
    return tuple(
        PerformanceSample(profile, 60, 16, 50, 100_000, 1_000_000, 1_000_000, 128)
        for profile in (PerformanceProfile.DESKTOP, PerformanceProfile.MOBILE, PerformanceProfile.LOW_POWER)
    )


def test_end_to_end_lifecycle_passes_when_all_governance_evidence_is_real(tmp_path: Path) -> None:
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(), project_root=tmp_path, browser_runs=_runs(), performance_samples=_samples(),
        production_build_passed=True, deployment_receipt="deploy-123", rollback_receipt="rollback-123",
        approval=ApprovalDecision(True, "super-owner"),
    ))
    assert result.passed and result.release_ready and result.release_gate.passed
    assert len(result.aggregate_sha256) == 64
    assert not result.remediation
    assert {item.stage.value for item in result.evidence} >= {"scaffold", "assets", "visual_qa", "performance_qa", "approval", "release"}


def test_lifecycle_inspects_registered_assets_and_generates_manifest(tmp_path: Path) -> None:
    (tmp_path / "world.gltf").write_text('{"asset":{"version":"2.0"},"meshes":[]}', encoding="utf-8")
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(True), project_root=tmp_path, browser_runs=_runs(), performance_samples=_samples(),
        production_build_passed=True, deployment_receipt="deploy", rollback_receipt="rollback",
        approval=ApprovalDecision(True, "owner"),
    ))
    assert result.passed
    assert len(result.asset_metadata) == 1
    assert result.asset_manifest is not None
    assert len(result.asset_manifest.aggregate_sha256) == 64


def test_lifecycle_fails_closed_without_browser_runs() -> None:
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(), project_root=Path("."), browser_runs=(), performance_samples=_samples(),
        production_build_passed=True, deployment_receipt="deploy", rollback_receipt="rollback",
        approval=ApprovalDecision(True, "owner"),
    ))
    assert not result.passed
    assert any("visual" in item.message.lower() or "desktop" in item.message.lower() for item in result.remediation)


def test_lifecycle_fails_closed_without_all_performance_profiles() -> None:
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(), project_root=Path("."), browser_runs=_runs(), performance_samples=_samples()[:1],
        production_build_passed=True, deployment_receipt="deploy", rollback_receipt="rollback",
        approval=ApprovalDecision(True, "owner"),
    ))
    assert not result.passed
    assert any("missing performance profiles" in item.message for item in result.remediation)


def test_lifecycle_requires_explicit_owner_approval() -> None:
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(), project_root=Path("."), browser_runs=_runs(), performance_samples=_samples(),
        production_build_passed=True, deployment_receipt="deploy", rollback_receipt="rollback",
        approval=ApprovalDecision(False, None, "awaiting owner review"),
    ))
    assert not result.release_ready
    assert any(item.stage.value == "approval" for item in result.remediation)


def test_lifecycle_requires_deploy_and_rollback_receipts() -> None:
    result = ThreeDProjectLifecycle().run(LifecycleInputs(
        blueprint=_blueprint(), project_root=Path("."), browser_runs=_runs(), performance_samples=_samples(),
        production_build_passed=True, deployment_receipt=None, rollback_receipt=None,
        approval=ApprovalDecision(True, "owner"),
    ))
    assert not result.passed
    assert "release evidence is missing" in result.release_gate.reasons


def test_approval_contract_is_truthful() -> None:
    try:
        ApprovalDecision(True, None).validate()
    except ValueError as exc:
        assert "approver" in str(exc)
    else:
        raise AssertionError("approval without approver must fail")
