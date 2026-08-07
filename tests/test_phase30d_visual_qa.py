from __future__ import annotations

import pytest

from aios.three_d_web.visual_qa import (
    BrowserAcceptancePlanner,
    BrowserRunReceipt,
    BrowserSpec,
    BrowserSupport,
    ConsoleRecord,
    DEFAULT_SCENARIOS,
    EvidenceEntry,
    EvidenceKind,
    EvidenceManifestBuilder,
    ScenarioResult,
    ViewportSpec,
    VisualQAGate,
    WebGLErrorRecord,
    checksum_bytes,
)


def _evidence(evidence_id: str, kind: EvidenceKind, *, viewport: str, browser: str) -> EvidenceEntry:
    return EvidenceEntry(
        evidence_id=evidence_id,
        kind=kind,
        path=f"evidence/{browser}/{viewport}/{evidence_id}.json" if kind != EvidenceKind.SCREENSHOT else f"evidence/{browser}/{viewport}/{evidence_id}.png",
        sha256=checksum_bytes(evidence_id.encode()),
        viewport_id=viewport,
        browser_id=browser,
    )


def _run(*, mobile: bool, browser_id: str = "chromium", support: BrowserSupport = BrowserSupport.SUPPORTED, reason: str | None = None, console=(), webgl=(), scenario_pass=True) -> BrowserRunReceipt:
    viewport = ViewportSpec("mobile" if mobile else "desktop", 390 if mobile else 1440, 844 if mobile else 900, 2.0 if mobile else 1.0, mobile)
    browser = BrowserSpec(browser_id, browser_id, support, reason)
    scenarios = tuple(ScenarioResult(item.scenario_id, scenario_pass) for item in DEFAULT_SCENARIOS)
    evidence = (_evidence("shot", EvidenceKind.SCREENSHOT, viewport=viewport.viewport_id, browser=browser_id),)
    return BrowserRunReceipt(browser, viewport, tuple(console), tuple(webgl), scenarios, evidence)


def test_acceptance_plan_covers_desktop_mobile_and_core_3d_smokes() -> None:
    plan = BrowserAcceptancePlanner().plan()
    assert any(not viewport.mobile for viewport in plan["viewports"])
    assert any(viewport.mobile for viewport in plan["viewports"])
    kinds = {scenario.kind for scenario in plan["scenarios"]}
    assert {EvidenceKind.ROUTE, EvidenceKind.INTERACTION, EvidenceKind.CAMERA, EvidenceKind.ASSET}.issubset(kinds)


def test_plan_rejects_duplicate_scenario_ids() -> None:
    duplicate = (DEFAULT_SCENARIOS[0], DEFAULT_SCENARIOS[0])
    with pytest.raises(ValueError):
        BrowserAcceptancePlanner().plan(scenarios=duplicate)


def test_visual_gate_passes_clean_supported_desktop_and_mobile_runs() -> None:
    verdict = VisualQAGate().evaluate((_run(mobile=False), _run(mobile=True)))
    assert verdict.passed is True
    assert verdict.violations == ()


def test_visual_gate_fails_closed_on_console_webgl_and_failed_scenario() -> None:
    dirty = _run(
        mobile=False,
        console=(ConsoleRecord("error", "uncaught runtime error"),),
        webgl=(WebGLErrorRecord("CONTEXT_LOST_WEBGL", "context lost"),),
        scenario_pass=False,
    )
    verdict = VisualQAGate().evaluate((dirty, _run(mobile=True)))
    assert verdict.passed is False
    assert any(item.startswith("console-error:") for item in verdict.violations)
    assert any(item.startswith("webgl-error:") for item in verdict.violations)
    assert any(item.startswith("scenario-failed:") for item in verdict.violations)


def test_unsupported_browser_state_is_explicit_and_not_reported_as_pass() -> None:
    unsupported = _run(mobile=False, browser_id="legacy", support=BrowserSupport.UNSUPPORTED, reason="WebGL2 unavailable")
    verdict = VisualQAGate().evaluate((unsupported, _run(mobile=True)))
    assert verdict.passed is False
    assert any("browser-legacy-unsupported:WebGL2 unavailable" == item for item in verdict.violations)


def test_unsupported_browser_requires_reason() -> None:
    with pytest.raises(ValueError):
        BrowserSpec("legacy", "legacy", BrowserSupport.UNSUPPORTED).validate()


def test_evidence_paths_are_traversal_safe() -> None:
    bad = EvidenceEntry("bad", EvidenceKind.SCREENSHOT, "../escape.png", "0" * 64)
    with pytest.raises(ValueError):
        bad.validate()


def test_evidence_manifest_is_deterministic() -> None:
    desktop = _run(mobile=False)
    mobile = _run(mobile=True)
    builder = EvidenceManifestBuilder()
    first = builder.build((desktop, mobile))
    second = builder.build((mobile, desktop))
    assert first.aggregate_sha256 == second.aggregate_sha256
    assert first.to_json() == second.to_json()


def test_browser_run_receipt_passed_reflects_runtime_errors() -> None:
    assert _run(mobile=False).passed is True
    assert _run(mobile=False, console=(ConsoleRecord("error", "boom"),)).passed is False
    assert _run(mobile=False, webgl=(WebGLErrorRecord("INVALID_OPERATION", "bad op"),)).passed is False
