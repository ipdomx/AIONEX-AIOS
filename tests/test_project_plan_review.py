from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aios.organization import EngineeringOrganization
from aios.project_plan_review import GovernedProjectPlanReviewer


def _planning(root: Path, *, missing_steps: bool = False) -> Path:
    root.mkdir(parents=True)
    artifacts = root / "artifacts"
    artifacts.mkdir()
    blueprint = EngineeringOrganization().plan("Demo", "Build a governed realtime application")
    records = []
    for deliverable in blueprint.deliverables:
        payload = {
            "schema_version": 1,
            "department": deliverable.department,
            "schema_valid": True,
            "model_output": {
                "summary": f"{deliverable.department} reviewed plan",
                "implementation_plan": (
                    ["one"] if missing_steps and deliverable.department == "Backend" else ["design", "implement", "verify"]
                ),
                "risks": [{"risk": "Regression", "mitigation": "Test and rollback"}],
            },
        }
        path = artifacts / f"{deliverable.department.lower()}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        records.append(
            {
                "department": deliverable.department,
                "path": f"artifacts/{path.name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "schema_valid": True,
                "acceptance_coverage": 1.0,
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "openai",
                "fallback_used": False,
                "artifacts": records,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_governed_plan_review_approves_complete_six_department_plan(tmp_path: Path) -> None:
    result = GovernedProjectPlanReviewer().review(
        project="Demo",
        objective="Build a governed realtime application",
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "evidence",
        requested_by_id="user-1",
    )
    assert result.approved is True
    assert result.blocking_findings == ()
    assert result.payload["chief_engineer"]["approved"] is True
    assert result.payload["wisdom"]["selected"] == "implement-reviewed-plan"
    assert result.payload["government"]["verdict"] == "approved"
    assert len(result.payload["ministry_routing"]) == 6
    assert result.payload["implementation_started"] is False


def test_governed_plan_review_rejects_incomplete_department_before_build(tmp_path: Path) -> None:
    result = GovernedProjectPlanReviewer().review(
        project="Demo",
        objective="Build a governed realtime application",
        planning_directory=_planning(tmp_path / "planning", missing_steps=True),
        output_root=tmp_path / "evidence",
        requested_by_id="user-1",
    )
    assert result.approved is False
    assert any("Backend" in item for item in result.blocking_findings)
    assert result.payload["wisdom"]["selected"] == "rework-plan"
    assert result.payload["implementation_started"] is False


def test_governed_plan_review_blocks_unsupported_mobile_builder_before_implementation(tmp_path: Path) -> None:
    result = GovernedProjectPlanReviewer().review(
        project="Mobile Demo",
        objective="Build a native iOS and Android mobile app for registered members",
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "evidence",
        requested_by_id="user-1",
    )
    assert result.approved is False
    assert result.payload["application_type"] == "mobile_application"
    assert any("does not yet support mobile_application" in item for item in result.blocking_findings)
    assert result.payload["implementation_started"] is False
