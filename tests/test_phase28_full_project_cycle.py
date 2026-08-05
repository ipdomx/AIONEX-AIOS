from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aios.full_project_cycle import (
    FullProjectCycle,
    FullProjectCycleValidationError,
)
from aios.organization import EngineeringOrganization


def _write_planning(root: Path, *, tests_passed: bool = False) -> Path:
    root.mkdir(parents=True)
    artifacts_dir = root / "artifacts"
    artifacts_dir.mkdir()
    blueprint = EngineeringOrganization().plan(
        "Demo Project", "Build a governed demonstration project"
    )
    records = []
    for deliverable in blueprint.deliverables:
        security_reviewed = deliverable.department not in {
            "Backend",
            "Security",
            "DevOps",
        } or tests_passed
        model_output = {
            "schema_version": 1,
            "department": deliverable.department,
            "summary": f"Validated {deliverable.department} delivery plan.",
            "implementation_plan": [
                f"Implement {deliverable.department} boundaries.",
                f"Verify {deliverable.department} acceptance evidence.",
            ],
            "technical_evidence": [
                {
                    "criterion": criterion,
                    "evidence": f"Evidence for {criterion}.",
                    "verification": f"Verify {criterion} deterministically.",
                }
                for criterion in deliverable.acceptance_criteria
            ],
            "risks": [
                {
                    "risk": f"{deliverable.department} regression",
                    "mitigation": "Retain rollback evidence and re-run verification.",
                }
            ],
            "tests_passed": tests_passed,
            "security_reviewed": security_reviewed,
        }
        wrapper = {
            "schema_version": 1,
            "execution_id": "cloud",
            "project": "Demo Project",
            "objective": "Build a governed demonstration project",
            "provider": "openai",
            "model": "gpt-5-mini",
            "department": deliverable.department,
            "model_output": model_output,
            "schema_valid": True,
            "acceptance_coverage": 1.0,
            "attempts": 1,
            "attempt_errors": [],
            "metrics": {},
        }
        path = artifacts_dir / f"{deliverable.department.lower()}.json"
        path.write_text(json.dumps(wrapper), encoding="utf-8")
        records.append(
            {
                "department": deliverable.department,
                "path": f"artifacts/{path.name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "schema_valid": True,
                "acceptance_coverage": 1.0,
                "attempts": 1,
                "errors": [],
                "metrics": {},
            }
        )
    manifest = {
        "schema_version": 1,
        "execution_id": "cloud",
        "provider": "openai",
        "model": "gpt-5-mini",
        "fallback_used": False,
        "production_modified": False,
        "requests_count": 6,
        "calculated_cost": 0.005,
        "artifacts": records,
        "review": {
            "approved": tests_passed,
            "readiness_score": 1.0 if tests_passed else 0.82,
            "blocking_findings": [] if tests_passed else ["tests have not passed"],
            "rework_plan": [] if tests_passed else ["execute department tests"],
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root



def _research_evidence() -> dict:
    first = "https://standards.example.org/current"
    second = "https://guidance.example.net/latest"
    return {
        "provider": "openai",
        "model": "gpt-5-mini",
        "research_question": "Which current constraints affect the project?",
        "summary": "Independent current evidence supports a controlled implementation.",
        "verified_facts": [
            {
                "claim": "The current standard requires retained evidence.",
                "source_urls": [first],
                "confidence": 0.94,
            },
            {
                "claim": "The current guidance requires a release review.",
                "source_urls": [second],
                "confidence": 0.91,
            },
        ],
        "risks": ["External requirements may change after the research date."],
        "unknowns": ["The final deployment jurisdiction is not selected."],
        "recommended_constraints": ["Repeat research before production release."],
        "sources": [
            {
                "url": first,
                "title": "Current standard",
                "domain": "standards.example.org",
            },
            {
                "url": second,
                "title": "Current guidance",
                "domain": "guidance.example.net",
            },
        ],
        "input_tokens": 600,
        "output_tokens": 400,
        "total_tokens": 1000,
        "calculated_cost": 0.01095,
        "tool_cost": 0.01,
        "total_duration": 1.0,
        "search_calls": 1,
        "request_count": 1,
        "raw_prompt_stored": False,
        "raw_response_stored": False,
        "authorization_header_stored": False,
        "fallback_used": False,
        "production_modified": False,
    }

def test_full_cycle_runs_every_governance_and_workforce_layer(tmp_path: Path) -> None:
    planning = _write_planning(tmp_path / "planning")
    stages = []
    result = FullProjectCycle().execute(
        execution_id="cycle-1",
        project="Demo Project",
        objective="Build a governed demonstration project",
        planning_directory=planning,
        output_root=tmp_path / "cycles",
        tenant_id="tenant-1",
        requested_by_id="user-1",
        stage_callback=lambda stage, progress: stages.append((stage, progress)),
    )

    assert result["success"] is True
    assert result["approved"] is False
    assert result["status"] == "rework_required"
    assert len(result["workforce"]) == 6
    assert all("training" in worker for worker in result["workforce"])
    assert all(worker["failure_count"] == 1 for worker in result["workforce"])
    assert result["governance"]["research_verified"] is False
    assert "research verification failed" in result["blocking_findings"]
    assert result["governance"]["councils_verdict"] == "approved"
    assert stages[0] == ("intake", 5)
    assert stages[-1] == ("completed", 100)

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["proof"]["all_governance_layers_executed"] is True
    assert manifest["proof"]["workforce_evaluated"] is True
    assert manifest["proof"]["model_claims_used_as_execution_proof"] is False
    assert manifest["delivery_package"]["contains_executable_product"] is False
    assert Path(result["report_path"]).is_file()


def test_full_cycle_never_promotes_model_test_claims_to_rollback_proof(
    tmp_path: Path,
) -> None:
    planning = _write_planning(tmp_path / "planning", tests_passed=True)
    result = FullProjectCycle().execute(
        execution_id="cycle-2",
        project="Demo Project",
        objective="Build a governed demonstration project",
        planning_directory=planning,
        output_root=tmp_path / "cycles",
    )

    assert result["approved"] is False
    assert any("rollback" in blocker for blocker in result["blocking_findings"])
    assert result["model_claims_used_as_execution_proof"] is False


def test_full_cycle_rejects_tampered_planning_artifact(tmp_path: Path) -> None:
    planning = _write_planning(tmp_path / "planning")
    artifact = next((planning / "artifacts").iterdir())
    artifact.write_text("{}", encoding="utf-8")
    with pytest.raises(FullProjectCycleValidationError, match="hash mismatch"):
        FullProjectCycle().execute(
            execution_id="cycle-3",
            project="Demo Project",
            objective="Build a governed demonstration project",
            planning_directory=planning,
            output_root=tmp_path / "cycles",
        )


def test_full_cycle_rejects_unsafe_execution_id(tmp_path: Path) -> None:
    planning = _write_planning(tmp_path / "planning")
    with pytest.raises(ValueError, match="unsafe"):
        FullProjectCycle().execute(
            execution_id="../escape",
            project="Demo Project",
            objective="Build a governed demonstration project",
            planning_directory=planning,
            output_root=tmp_path / "cycles",
        )


def _write_implementation(tmp_path: Path, planning: Path) -> Path:
    from aios.controlled_project_builder import ControlledProjectBuilder
    from tests.test_controlled_project_builder import FakeTransport, _specification

    result = ControlledProjectBuilder(
        FakeTransport(_specification()),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="prototype",
        project="Demo Project",
        objective="Build a governed demonstration project",
        planning_directory=planning,
        output_root=tmp_path / "implementation",
    )
    return result.output_directory


def test_full_cycle_approves_tested_prototype_and_activates_workforce(
    tmp_path: Path,
) -> None:
    planning = _write_planning(tmp_path / "planning")
    implementation = _write_implementation(tmp_path, planning)
    result = FullProjectCycle().execute(
        execution_id="cycle-implementation",
        project="Demo Project",
        objective="Build a governed demonstration project",
        planning_directory=planning,
        implementation_directory=implementation,
        research_evidence=_research_evidence(),
        output_root=tmp_path / "cycles",
    )

    assert result["approved"] is True
    assert result["blocking_findings"] == []
    assert result["delivery_package"]["contains_executable_product"] is True
    assert result["delivery_package"]["executable_scope"] == (
        "controlled-full-stack-web-prototype"
    )
    assert all(worker["employment_state"] == "active" for worker in result["workforce"])
    assert all(worker["failure_count"] == 0 for worker in result["workforce"])
    package = Path(result["output_directory"]) / "delivery-package"
    assert (package / "prototype-project-prototype.zip").is_file()
    assert (package / "prototype-TEST_REPORT.json").is_file()


def test_full_cycle_withholds_backend_claim_beyond_prototype_scope(
    tmp_path: Path,
) -> None:
    planning = _write_planning(tmp_path / "planning")
    implementation = _write_implementation(tmp_path, planning)
    result = FullProjectCycle().execute(
        execution_id="cycle-backend-scope",
        project="Demo Project",
        objective=(
            "Build a production backend API with authentication, database, payments, "
            "mobile applications and third-party integrations."
        ),
        planning_directory=planning,
        implementation_directory=implementation,
        research_evidence=_research_evidence(),
        output_root=tmp_path / "cycles",
    )

    assert result["approved"] is False
    assert any(
        "production-deployment runtime capability" in item
        for item in result["blocking_findings"]
    )
    assert any("payments runtime capability" in item for item in result["blocking_findings"])
    assert any("mobile runtime capability" in item for item in result["blocking_findings"])
    assert result["model_claims_used_as_execution_proof"] is False


def test_full_cycle_rejects_tampered_implementation_source(tmp_path: Path) -> None:
    planning = _write_planning(tmp_path / "planning")
    implementation = _write_implementation(tmp_path, planning)
    (implementation / "source" / "app.js").write_text("tampered", encoding="utf-8")
    with pytest.raises(FullProjectCycleValidationError, match="hash mismatch"):
        FullProjectCycle().execute(
            execution_id="cycle-tampered-implementation",
            project="Demo Project",
            objective="Build a governed demonstration project",
            planning_directory=planning,
            implementation_directory=implementation,
            output_root=tmp_path / "cycles",
        )
