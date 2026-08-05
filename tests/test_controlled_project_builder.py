from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aios.controlled_project_builder import (
    ControlledProjectBuildError,
    ControlledProjectBuilder,
)
from aios.organization import EngineeringOrganization


class FakeTransport:
    def __init__(self, specification: dict) -> None:
        self.specification = specification
        self.calls = 0

    async def __call__(self, payload: dict) -> dict:
        self.calls += 1
        return {
            "text": json.dumps(self.specification),
            "usage": {
                "input_tokens": 300,
                "output_tokens": 500,
                "total_tokens": 800,
            },
            "latency_ms": 120.0,
            "cost": 0.001075,
            "confidence": 1.0,
            "status": "completed",
            "actual_model": "gpt-5-mini",
            "reported_cost": None,
            "calculated_cost": 0.001075,
        }


def _specification() -> dict:
    return {
        "schema_version": 1,
        "title": "Governed Project Workspace",
        "tagline": "A transparent workflow for controlled project delivery.",
        "summary": (
            "This prototype organizes the project objective, workflow and retained "
            "evidence without claiming production deployment."
        ),
        "audience": "Project owners, reviewers and implementation teams",
        "features": [
            "Structured project overview",
            "Visible governed workflow",
            "Evidence and release boundaries",
        ],
        "sections": [
            {
                "id": "overview",
                "title": "Project overview",
                "body": "Understand the requested outcome and the intended audience.",
                "items": ["Objective summary", "Audience and value"],
            },
            {
                "id": "workflow",
                "title": "Governed workflow",
                "body": "Follow the controlled stages from intake through review.",
                "items": ["Council review", "Engineering delivery"],
            },
            {
                "id": "evidence",
                "title": "Evidence boundary",
                "body": "Inspect what is proven and what still requires implementation.",
                "items": ["Retained hashes", "Explicit limitations"],
            },
        ],
        "primary_action": "Review workflow",
        "secondary_action": "Inspect evidence",
        "limitations": [
            "No production deployment or external integration is claimed."
        ],
    }


def _planning(root: Path) -> Path:
    root.mkdir(parents=True)
    artifacts = root / "artifacts"
    artifacts.mkdir()
    blueprint = EngineeringOrganization().plan(
        "Demo Project", "Build a governed demonstration project"
    )
    records = []
    for deliverable in blueprint.deliverables:
        payload = {
            "department": deliverable.department,
            "model_output": {
                "summary": f"{deliverable.department} plan",
                "implementation_plan": ["Implement boundaries", "Verify evidence"],
                "risks": [{"risk": "Regression", "mitigation": "Retest"}],
            },
        }
        path = artifacts / f"{deliverable.department.lower()}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        records.append(
            {
                "department": deliverable.department,
                "path": f"artifacts/{path.name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "gpt-5-mini",
                "fallback_used": False,
                "artifacts": records,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_builder_creates_tested_executable_prototype_and_verified_archive(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(_specification())
    result = ControlledProjectBuilder(
        transport,  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="implementation",
        project="Demo Project",
        objective="Build a governed demonstration project",
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "output",
    )

    assert transport.calls == 1
    assert result.tests_passed is True
    assert result.rollback_tested is True
    assert result.archive_path.is_file()
    source = result.output_directory / "source"
    assert {path.name for path in source.iterdir()} == {
        "index.html",
        "styles.css",
        "app.js",
        "server.py",
        "README.md",
    }
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "controlled-full-stack-prototype"
    assert manifest["provider_role"] == "structured product specification only"
    assert manifest["executable_source_origin"] == "deterministic reviewed templates"
    assert manifest["tests"]["passed"] is True
    assert manifest["rollback_tested"] is True
    assert manifest["tests"]["checks"]["api_health"] is True
    assert manifest["tests"]["checks"]["api_create_read_delete"] is True
    assert manifest["tests"]["checks"]["sqlite_persistence"] is True
    assert manifest["fallback_used"] is False
    assert manifest["production_modified"] is False


def test_builder_rejects_provider_markup_before_writing_source(tmp_path: Path) -> None:
    specification = _specification()
    specification["tagline"] = "Unsafe <script> content"
    builder = ControlledProjectBuilder(
        FakeTransport(specification),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    )
    root = tmp_path / "output"
    with pytest.raises(ControlledProjectBuildError, match="forbidden"):
        builder.execute(
            execution_id="implementation",
            project="Demo Project",
            objective="Build a governed demonstration project",
            planning_directory=_planning(tmp_path / "planning"),
            output_root=root,
        )
    assert not (root / "implementation").exists()
    assert not (root / ".staging-implementation").exists()


def test_builder_rejects_insufficient_remaining_budget() -> None:
    with pytest.raises(ControlledProjectBuildError, match="remaining budget"):
        ControlledProjectBuilder(
            FakeTransport(_specification()),  # type: ignore[arg-type]
            model="gpt-5-mini",
            input_cost_per_million=0.25,
            output_cost_per_million=2.0,
            remaining_budget_usd=0.001,
        )


def test_builder_allows_one_provider_attempt_with_sufficient_output_budget() -> None:
    builder = ControlledProjectBuilder(
        FakeTransport(_specification()),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    )
    assert builder.MAX_OUTPUT_TOKENS == 3000
    assert builder.provider.retry.policy.max_attempts == 1


def test_builder_normalizes_long_copy_and_section_order() -> None:
    payload = _specification()
    payload["primary_action"] = "Review the complete governed project workflow and all retained evidence before continuing"
    payload["sections"] = [
        payload["sections"][2],
        payload["sections"][0],
        payload["sections"][1],
    ]
    validated = ControlledProjectBuilder._validate_spec(json.dumps(payload))
    assert len(validated["primary_action"]) <= 80
    assert [item["id"] for item in validated["sections"]] == [
        "overview",
        "workflow",
        "evidence",
    ]


def test_builder_never_normalizes_forbidden_content_into_acceptance() -> None:
    payload = _specification()
    payload["primary_action"] = "Open https://example.com and continue"
    with pytest.raises(ControlledProjectBuildError, match="forbidden content"):
        ControlledProjectBuilder._validate_spec(json.dumps(payload))
