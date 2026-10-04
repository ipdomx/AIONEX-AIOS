from __future__ import annotations

import json
from pathlib import Path

import pytest

from aios.universal_project_builder import augment_universal_project, infer_project_profile


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests/fixtures/fr18_phase29_acceptance_matrix.json"


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _specification() -> dict:
    return {
        "title": "FR18 Acceptance",
        "tagline": "Bounded deterministic source acceptance.",
        "summary": "Synthetic acceptance input for project-builder source generation.",
        "audience": "AIONEX reviewers",
        "features": ["source generation", "truthful external gates", "retained evidence"],
        "brand": {
            "primary": "#112233",
            "secondary": "#445566",
            "accent": "#778899",
            "surface": "#FFFFFF",
            "logo_concept": "A simple governed project mark",
        },
        "architecture": {
            "frontend": "Local generated source",
            "backend": "Local generated source",
            "data": "Local generated source",
            "realtime": "Not requested",
            "deployment": "Not performed",
        },
        "domain_blueprint": {
            "roles": ["member"],
            "entities": [
                {
                    "name": "record",
                    "label": "Record",
                    "fields": [{"name": "title", "type": "string", "required": True}],
                }
            ],
            "workflows": [
                {
                    "name": "Create record",
                    "trigger": "member request",
                    "steps": ["validate", "store"],
                }
            ],
        },
        "sections": [],
        "primary_action": "Review",
        "secondary_action": "Inspect",
        "limitations": ["No production deployment is claimed."],
    }


def _generated_files(objective: str) -> dict[str, str]:
    return augment_universal_project(
        {"README.md": "# FR18 acceptance\n"},
        "FR18 Acceptance",
        objective,
        _specification(),
        {"manifest_sha256": "a" * 64},
    )


def _family(family_id: str) -> dict:
    return next(item for item in _matrix()["families"] if item["id"] == family_id)


def test_matrix_declares_truthful_acceptance_boundary() -> None:
    matrix = _matrix()
    assert matrix["batch_id"] == "FR-18"
    assert matrix["sub_batch"] == "FR-18A"
    boundary = matrix["truth_boundary"]
    assert boundary == {
        "generated_source_is_production_execution": False,
        "generic_simulation_family_accepted": False,
        "platform_store_deployment_accepted": False,
        "provider_neutral_snapshot_is_full_governed_execution": False,
        "source_mobile_generation_allowed": True,
        "owner_governance_preserved": True,
    }


@pytest.mark.parametrize(
    "family_id",
    [
        "web_api",
        "data",
        "bot",
        "desktop",
        "browser_extension",
        "commerce",
        "source_mobile",
        "iot_bounded_simulator",
        "robotics_bounded_simulator",
    ],
)
def test_accepted_builder_family_routes_and_generates_declared_source(
    family_id: str,
) -> None:
    family = _family(family_id)
    assert family["status"].startswith("accepted_")
    profile = infer_project_profile(family["objective"])
    assert set(family["expected_targets"]).issubset(profile.targets)
    assert set(family["required_external_gates"]).issubset(profile.external_gates)

    files = _generated_files(family["objective"])
    generated_profile = json.loads(files["PROJECT_PROFILE.json"])
    assert generated_profile["production_claim"] is False
    assert set(family["expected_targets"]).issubset(generated_profile["targets"])
    assert set(family["required_external_gates"]).issubset(
        generated_profile["external_gates"]
    )
    for required in family["required_files"]:
        assert required in files
        assert files[required].strip()

    assert "Generated source contains no embedded production credential." in files["SECURITY.md"]
    assert (
        "Live provider, store, signing, payment and hardware actions remain external gates."
        in files["SECURITY.md"]
    )


def test_source_mobile_is_source_only_and_keeps_store_gates() -> None:
    family = _family("source_mobile")
    files = _generated_files(family["objective"])
    profile = json.loads(files["PROJECT_PROFILE.json"])
    assert {"android-source", "ios-source", "react-native"}.issubset(profile["capabilities"])
    assert {"mobile-store-signing", "apple-google-store-credentials"}.issubset(
        profile["external_gates"]
    )
    assert profile["production_claim"] is False
    assert "platform signing/store publication is not" in family["boundary"]


def test_bounded_simulators_are_not_promoted_to_generic_simulation_acceptance() -> None:
    matrix = _matrix()
    iot = _family("iot_bounded_simulator")
    robotics = _family("robotics_bounded_simulator")
    generic = _family("generic_simulation")

    assert "physical-hardware-validation" in infer_project_profile(iot["objective"]).external_gates
    assert (
        "robotics-hardware-and-runtime-validation"
        in infer_project_profile(robotics["objective"]).external_gates
    )

    observed = infer_project_profile(generic["objective"])
    assert tuple(generic["observed_current_targets"]) == observed.targets
    assert generic["status"] == "gap_generic_family_not_implemented"
    assert generic["must_not_be_counted_as_accepted"] is True
    assert generic["missing_target"] not in observed.targets
    assert "iot" not in observed.targets
    assert "robotics" not in observed.targets
    assert matrix["truth_boundary"]["generic_simulation_family_accepted"] is False


def test_phase29_legacy_boundaries_and_owner_governance_are_preserved() -> None:
    phase29f = (
        ROOT / "docs/phase-29/PHASE_29F_PROJECTS_WORKFORCE_KNOWLEDGE_COMPLETION.md"
    ).read_text(encoding="utf-8")
    phase29h = (
        ROOT / "docs/phase-29/PHASE_29H_PRODUCTION_STUDIO_MOBILE_DELIVERY_COMPLETION.md"
    ).read_text(encoding="utf-8")
    phase29i = (
        ROOT / "docs/phase-29/PHASE_29I_PLUGINS_DISTRIBUTED_INTEGRATIONS_COMPLETION.md"
    ).read_text(encoding="utf-8")
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text(encoding="utf-8"))

    assert "provider-neutral snapshots cannot be promoted to an approved release" in phase29f
    assert "Apple signing and App Store publication remain an explicit external" in phase29h
    assert "no IPA or store-publication claim is made" in phase29h
    assert "Missing credentials report `unconfigured`" in phase29i
    assert "never a false green state" in phase29i

    owner = plan["owner_decisions"]
    assert any(
        "تطبيقات المنصة المستقلة وتوقيعها ونشرها بالمتاجر" in item
        for item in owner["deferred"]
    )
    assert "بناء المستخدم مصدر مشروع تطبيق يبقى وظيفة منشئ المشاريع" in owner[
        "defer_scope_note"
    ]


def test_legacy_contract_evidence_paths_are_real() -> None:
    for item in _matrix()["legacy_contracts"]:
        evidence = ROOT / item["evidence"]
        assert evidence.is_file(), item["id"]


def test_core_business_tool_governance_markers_are_not_dropped() -> None:
    phase29c = (
        ROOT / "docs/phase-29/PHASE_29C_IDENTITY_TENANCY_COMPLETION.md"
    ).read_text(encoding="utf-8")
    phase29d = (
        ROOT / "docs/phase-29/PHASE_29D_BILLING_PAYMENTS_COMPLETION.md"
    ).read_text(encoding="utf-8")
    phase29e = (
        ROOT / "docs/phase-29/PHASE_29E_COMMUNICATIONS_GOVERNANCE_COMPLETION.md"
    ).read_text(encoding="utf-8")
    phase29g = (
        ROOT / "docs/phase-29/PHASE_29G_OPERATIONS_SECURITY_RECOVERY_RELEASE_COMPLETION.md"
    ).read_text(encoding="utf-8")

    assert "organizations, workspaces, sessions, passkeys" in phase29c
    assert "Super Owner assignment and wildcard permission mutation remain protected" in phase29c
    assert "plans and subscription periods" in phase29d
    assert "required sandbox or live credentials" in phase29d
    assert "private support requests and retained conversations" in phase29e
    assert "Missing provider configuration produces `unconfigured`, not a false success" in phase29e
    assert "explicit Owner approval" in phase29g
    assert "unimplemented host/container mutation is never reported as successful" in phase29g