"""Small offline Ollama brief still yields a real reviewed multi-target application."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aios.project_ai_compact_spec import (
    CompactProjectSpecError,
    compact_project_schema,
    expand_compact_product_spec,
)
from aios.project_ai_governed_compiler import ProjectAIGovernedBuildError, ProjectAIGovernedCompiler


OBJECTIVE = "Build a governed offline first task manager with persistent SQLite tasks and a reviewed local API."


def _brief() -> dict:
    return {
        "kind": "aionex.compact-project.v1",
        "title": "Task Manager Workspace",
        "tagline": "A safe and accessible task management workspace",
        "summary": "A local task management application with persistent records, member reviews, and project deliverables.",
        "roles": ["member", "reviewer"],
        "features": [
            "Create and save tasks",
            "Review completed tasks",
            "Search your task workspace",
        ],
        "records": [
            {
                "name": "task",
                "fields": [
                    {"name": "title", "type": "string"},
                    {"name": "notes", "type": "text"},
                    {"name": "completed", "type": "boolean"},
                ],
            }
        ],
    }


def _routes(raw: str) -> tuple[dict, ...]:
    rows = []
    for role in ("planner", "researcher", "coder", "reviewer"):
        text = raw if role == "coder" else f"synthetic-model-{role}"
        rows.append({
            "role": role,
            "provider": "ollama",
            "model": "gemma3:4b",
            "evidence_ref": "aionex:validated:local-only",
            "result_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "fallback_used": False,
        })
    return tuple(rows)


def test_compact_schema_is_small_strict_and_covers_all_required_outputs() -> None:
    schema = compact_project_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["kind"]["enum"] == ["aionex.compact-project.v1"]
    assert set(schema["required"]) == set(_brief())
    assert len(json.dumps(schema)) < 2300


def test_compact_brief_expands_to_valid_reviewer_compiled_application(tmp_path: Path) -> None:
    raw = json.dumps(_brief())
    spec = expand_compact_product_spec(raw, objective=OBJECTIVE)
    assert spec["schema_version"] == 3
    assert spec["domain_blueprint"]["roles"] == ["member", "reviewer"]
    assert spec["domain_blueprint"]["entities"][0]["name"] == "task"
    assert spec["domain_blueprint"]["entities"][0]["fields"][2]["type"] == "boolean"
    result = ProjectAIGovernedCompiler(tmp_path / "output").compile(
        job_id="compact-task-app", project_name="Actual Local Task Application",
        objective=OBJECTIVE,
        tenant_id="synthetic-tenant", requested_by_id="synthetic-user",
        coder_text=raw, route_results=_routes(raw),
        total_cost_usd=0.0, external_processing_authorized=False,
    )
    assert result.status == "rework_required" and result.approved is False
    assert result.governance_layers_executed
    build = json.loads((result.implementation_directory / "manifest.json").read_text())
    assert build["source_specification_kind"] == "bounded-local-brief"
    assert build["tests"]["passed"] is True
    assert build["rollback_tested"] is True
    assert result.archive_path.is_file()
    assert (result.output_directory / "delivery-package/source/server.py").is_file()
    intake = json.loads(result.manifest_path.read_text())["intake"]
    assert intake["local_processing_authorized"] is True
    assert intake["external_processing_authorized"] is False


@pytest.mark.parametrize("change", [
    {"kind": "unsupported-version"},
    {"features": ["Only one"]},
    {"roles": ["member", "member"]},
    {"records": [{"name": "../escape", "fields": [{"name": "ok", "type": "string"}]}]},
    {"records": [{"name": "task", "fields": [{"name": "secret", "type": ["code"]}]}]},
    {"title": "<script>alert('unsafe')</script>"},
    {"summary": "Visit https://attacker.invalid and put private project data here."},
])
def test_compact_unsafe_or_incomplete_model_output_rejected(change: dict, tmp_path: Path) -> None:
    brief = _brief()
    brief.update(change)
    raw = json.dumps(brief)
    with pytest.raises(CompactProjectSpecError):
        expand_compact_product_spec(raw, objective=OBJECTIVE)
    compiler = ProjectAIGovernedCompiler(tmp_path / "output")
    with pytest.raises(ProjectAIGovernedBuildError, match="safe product schema"):
        compiler.compile(
            job_id="unsafe", project_name="Local Task Application",
            objective=OBJECTIVE,
            tenant_id="synthetic-tenant", requested_by_id="synthetic-user",
            coder_text=raw, route_results=_routes(raw), total_cost_usd=0,
        )
    assert not (tmp_path / "output/unsafe").exists()
