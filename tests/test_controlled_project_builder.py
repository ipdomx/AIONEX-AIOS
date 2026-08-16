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
        "schema_version": 2,
        "application_type": "web_application",
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
        "brand": {
            "primary": "#E11D48",
            "secondary": "#0EA5E9",
            "accent": "#F8FAFC",
            "surface": "#050816",
            "logo_concept": "A precise geometric project mark",
        },
        "architecture": {
            "frontend": "Responsive browser interface",
            "backend": "Local Python application API",
            "data": "SQLite persistence",
            "realtime": "No realtime runtime requested",
            "deployment": "Local governed delivery package only",
        },
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
    assert manifest["provider_role"] == "structured architecture and product specification only"
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



def test_builder_generates_functional_realtime_member_calling_archetype(tmp_path: Path) -> None:
    specification = _specification()
    specification.update(
        {
            "application_type": "realtime_communications",
            "title": "We Control",
            "tagline": "Private high quality calls between registered members.",
            "summary": "A governed realtime communications application for registered members with browser-native audio and video calling.",
            "audience": "Registered application members",
            "features": [
                "Registered member authentication",
                "Audio and video calls",
                "Member directory and signaling",
            ],
            "brand": {
                "primary": "#DC2626",
                "secondary": "#2563EB",
                "accent": "#FFFFFF",
                "surface": "#050505",
                "logo_concept": "A circular voice and video communication mark",
            },
            "architecture": {
                "frontend": "Responsive browser WebRTC interface",
                "backend": "Python same-origin signaling and member API",
                "data": "SQLite members sessions and signaling queue",
                "realtime": "WebRTC media with controlled same-origin signaling",
                "deployment": "HTTPS and audited STUN TURN required for public internet",
            },
        }
    )
    result = ControlledProjectBuilder(
        FakeTransport(specification),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="realtime",
        project="We Control",
        objective=(
            "تطبيق اتصالات مجانيه بين الأعضاء المسجلين صوت وصوره بجوده عاليه "
            "ويكون بتصميم احترافى ولا يكون قالب مجانى"
        ),
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "output",
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["application_type"] == "realtime_communications"
    assert manifest["tests"]["passed"] is True
    checks = manifest["tests"]["checks"]
    assert checks["webrtc_runtime_present"] is True
    assert checks["member_registration"] is True
    assert checks["member_authentication"] is True
    assert checks["member_directory"] is True
    assert checks["signaling_round_trip"] is True
    assert checks["csrf_enforced"] is True
    assert checks["external_relay_fail_closed"] is True
    source = result.output_directory / "source"
    assert {"logo.svg", "manifest.webmanifest", "runtime-config.json"}.issubset(
        {item.name for item in source.iterdir()}
    )
    app = (source / "app.js").read_text(encoding="utf-8")
    assert "RTCPeerConnection" in app
    assert "getUserMedia" in app
