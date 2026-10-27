"""Full executable Phase36C compiler -> real tests/archive -> Phase28 governance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from aios.full_project_cycle import FullProjectCycle, FullProjectCycleValidationError
from aios.project_ai_governed_compiler import (
    ProjectAIGovernedBuildError,
    ProjectAIGovernedCompiler,
)
from tests.test_controlled_project_builder import _specification


OBJECTIVE = "Build a governed project workspace with a persistent local API and reviewed deliverable."
PROJECT = "Actual Governed Product"


def _case() -> tuple[str, tuple[dict, ...]]:
    raw = json.dumps(_specification())
    roles = []
    for role in ("planner", "researcher", "coder", "reviewer"):
        roles.append({
            "role": role,
            "provider": "ollama",
            "model": "qwen3-local",
            "evidence_ref": "phase36c:validated-model:fixture",
            "result_sha256": hashlib.sha256(
                (raw if role == "coder" else f"model:{role}:model-only").encode()
            ).hexdigest(),
            "fallback_used": False,
        })
    return raw, tuple(roles)


def _run(tmp_path: Path, *, raw: str | None = None, roles: tuple[dict, ...] | None = None):
    text, original_roles = _case()
    return ProjectAIGovernedCompiler(tmp_path / "output").compile(
        job_id="cycle-123",
        project_name=PROJECT,
        objective=OBJECTIVE,
        tenant_id="synthetic-tenant",
        requested_by_id="synthetic-member",
        coder_text=text if raw is None else raw,
        route_results=original_roles if roles is None else roles,
        total_cost_usd=0.001,
    )


def test_model_bounded_json_produces_real_runnable_source_tests_and_all_governance(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.governance_layers_executed is True
    assert result.status == "rework_required" and result.approved is False
    assert "research verification failed" in result.blocking_findings
    assert len(result.workforce) == 6
    assert result.delivery_package["contains_executable_product"] is True
    assert result.governance["research_verified"] is False
    assert result.release_review["approved"] is False
    assert result.engineering_review["approved"] is True
    assert result.application_type == "universal_application"
    assert result.implementation_capabilities["persistence"] is True
    assert result.archive_path.is_file()
    assert result.manifest_path.is_file()
    files = result.output_directory / "delivery-package/source"
    assert files.is_dir()
    assert (files / "server.py").is_file()
    assert (files / "index.html").is_file()
    assert (result.implementation_directory / "TEST_REPORT.json").is_file()
    tests = json.loads((result.implementation_directory / "TEST_REPORT.json").read_text())
    assert tests["passed"] is True
    implementation = json.loads((result.implementation_directory / "manifest.json").read_text())
    assert implementation["rollback_tested"] is True
    assert implementation["provider"] == "aionex-project-ai"
    assert implementation["raw_response_stored"] is False
    full = json.loads(result.manifest_path.read_text())
    assert full["proof"]["all_governance_layers_executed"] is True
    assert full["proof"]["all_six_departments_reviewed"] is True
    assert full["proof"]["model_claims_used_as_execution_proof"] is False
    assert full["source_planning"]["provider"] == "aionex-project-ai"
    assert full["source_planning"]["model"] == "qwen3-local"
    assert full["intake"]["local_processing_authorized"] is True
    assert full["intake"]["external_processing_authorized"] is False


def test_tampered_coder_output_refused_before_any_files(tmp_path: Path) -> None:
    spec, roles = _case()
    with pytest.raises(ProjectAIGovernedBuildError, match="not bound"):
        _run(tmp_path, raw=spec + " ", roles=roles)
    assert not (tmp_path / "output/cycle-123").exists()


def test_forged_missing_route_or_model_fallback_refused(tmp_path: Path) -> None:
    _, rows = _case()
    with pytest.raises(ProjectAIGovernedBuildError, match="four distinct"):
        _run(tmp_path, roles=rows[:3])
    fallback_rows = tuple({**item, "fallback_used": True} if item["role"] == "coder" else item for item in rows)
    with pytest.raises(ProjectAIGovernedBuildError, match="separate governance"):
        _run(tmp_path, roles=fallback_rows)


def test_arbitrary_model_markup_rejected_without_executable_files(tmp_path: Path) -> None:
    malicious = _specification()
    malicious["tagline"] = "<script>alert('unsafe')</script>"
    data = json.dumps(malicious)
    _, original = _case()
    rows = tuple({**x, "result_sha256": hashlib.sha256(data.encode()).hexdigest()} if x["role"] == "coder" else x for x in original)
    with pytest.raises(ProjectAIGovernedBuildError, match="safe product schema"):
        _run(tmp_path, raw=data, roles=rows)
    assert not (tmp_path / "output/cycle-123").exists()


def test_phase28_new_provenance_never_accepts_unaudited_plan(tmp_path: Path) -> None:
    result = _run(tmp_path)
    planning = result.planning_directory
    manifest_path = planning / "manifest.json"
    old = json.loads(manifest_path.read_text())
    old["route_evidence"] = []
    manifest_path.write_text(json.dumps(old))
    with pytest.raises(FullProjectCycleValidationError, match="route provenance"):
        FullProjectCycle._validate_planning_source(planning)


def test_replay_does_not_replace_previous_project_build(tmp_path: Path) -> None:
    first = _run(tmp_path)
    with pytest.raises(FileExistsError, match="earlier"):
        _run(tmp_path)
    assert first.manifest_path.is_file()
    assert first.archive_path.is_file()


def test_remote_model_requires_explicit_owner_authorized_processing_before_build(tmp_path: Path) -> None:
    spec, rows = _case()
    remote = tuple(
        {**row, "provider": "openai", "model": "gpt-model"}
        for row in rows
    )
    with pytest.raises(ProjectAIGovernedBuildError, match="explicit processing"):
        _run(tmp_path, raw=spec, roles=remote)
    assert not (tmp_path / "output/cycle-123").exists()
    result = ProjectAIGovernedCompiler(tmp_path / "output").compile(
        job_id="cycle-123", project_name=PROJECT, objective=OBJECTIVE,
        tenant_id="synthetic-tenant", requested_by_id="synthetic-member",
        coder_text=spec, route_results=remote,
        total_cost_usd=0.001,
        external_processing_authorized=True,
    )
    assert result.governance_layers_executed is True
    full = json.loads(result.manifest_path.read_text())
    assert full["intake"]["external_processing_authorized"] is True
    assert full["intake"]["local_processing_authorized"] is False
    assert result.approved is False  # Missing verified external research, no automatic Owner approval.


def test_research_is_not_implicitly_authorized_by_local_model_output(tmp_path: Path) -> None:
    result = _run(tmp_path)
    content = json.loads(result.manifest_path.read_text())
    assert content["research_verification"]["external_fact_claims_verified"] is False
    assert content["proof"]["model_claims_used_as_execution_proof"] is False
    assert result.release_review["owner_approved"] is False
    assert "research verification failed" in result.blocking_findings


def test_planning_only_generates_six_chief_reviewed_departments_and_download(tmp_path: Path) -> None:
    spec, rows = _case()
    planned = ProjectAIGovernedCompiler(tmp_path / "plans").plan_only(
        job_id="planning-01", project_name=PROJECT, objective=OBJECTIVE,
        tenant_id="synthetic-tenant", requested_by_id="synthetic-member",
        route_results=rows, total_cost_usd=0,
    )
    assert planned.planning_approved
    assert planned.department_count == 6
    assert planned.readiness_score >= 0.9
    assert planned.package["contains_executable_product"] is False
    manifest = json.loads(planned.manifest_path.read_text())
    assert manifest["approved"] is False
    assert manifest["all_governance_layers_executed"] is False
    package = planned.output_directory / "delivery-package"
    plan_path = package / "engineering-plan.json"
    plan = json.loads(plan_path.read_text())
    assert plan["planning_approved"] is True
    assert all(not d["implementation_tests_passed"] for d in plan["departments"])
    assert hashlib.sha256(plan_path.read_bytes()).hexdigest() == manifest["planning_sha256"]
    assert (package / "README.md").is_file()
    with pytest.raises(FileExistsError, match="earlier governed planning"):
        ProjectAIGovernedCompiler(tmp_path / "plans").plan_only(
            job_id="planning-01", project_name=PROJECT, objective=OBJECTIVE,
            tenant_id="synthetic-tenant", requested_by_id="synthetic-member",
            route_results=rows, total_cost_usd=0,
        )


def test_planning_only_blocks_unauthorized_external_provider_and_invalid_roles(tmp_path: Path) -> None:
    _, roles = _case()
    remote = tuple({**x, "provider": "openai"} for x in roles)
    compiler = ProjectAIGovernedCompiler(tmp_path / "plans")
    with pytest.raises(ProjectAIGovernedBuildError, match="explicit processing"):
        compiler.plan_only(
            job_id="planning-01", project_name=PROJECT, objective=OBJECTIVE,
            tenant_id="synthetic-tenant", requested_by_id="synthetic-member",
            route_results=remote, total_cost_usd=0.0001,
        )
    with pytest.raises(ProjectAIGovernedBuildError, match="four distinct"):
        compiler.plan_only(
            job_id="planning-01", project_name=PROJECT, objective=OBJECTIVE,
            tenant_id="synthetic-tenant", requested_by_id="synthetic-member",
            route_results=roles[:2], total_cost_usd=0,
        )
    assert not (tmp_path / "plans/planning-01").exists()
