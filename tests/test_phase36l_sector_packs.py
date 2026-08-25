from __future__ import annotations

import json
from pathlib import Path

from aios.sector_packs import (
    REFERENCE_SECTOR_PACKS,
    SectorEntity,
    SectorField,
    SectorWorkflow,
    build_sector_reference,
    compose_custom_sector,
)


def _aquaculture_pack():
    return compose_custom_sector(
        key="aquaculture-operations",
        title="Aquaculture Operations",
        objective=(
            "Build an aquaculture operations web app and API for ponds, stock batches, "
            "water readings, feed events, harvest planning, and audit reporting."
        ),
        audience="Farm operators, technicians, managers, and auditors",
        roles=("operator", "technician", "manager", "auditor"),
        entities=(
            SectorEntity(
                "pond",
                "Pond",
                (SectorField("reference", "string"), SectorField("status", "string")),
            ),
            SectorEntity(
                "stock_batch",
                "Stock batch",
                (
                    SectorField("pond_ref", "string"),
                    SectorField("species", "string"),
                    SectorField("quantity", "integer"),
                ),
            ),
            SectorEntity(
                "water_reading",
                "Water reading",
                (
                    SectorField("pond_ref", "string"),
                    SectorField("metric", "string"),
                    SectorField("value", "number"),
                    SectorField("recorded_at", "datetime"),
                ),
            ),
            SectorEntity(
                "harvest_plan",
                "Harvest plan",
                (
                    SectorField("batch_ref", "string"),
                    SectorField("status", "string"),
                    SectorField("scheduled_at", "datetime", False),
                ),
            ),
        ),
        workflows=(
            SectorWorkflow(
                "Record water quality",
                "technician records a reading",
                ("validate pond", "record measurement", "retain audit event"),
            ),
            SectorWorkflow(
                "Plan harvest",
                "manager prepares a harvest",
                ("review batch state", "record plan", "approve schedule"),
            ),
        ),
    )


def test_reference_sector_registry_covers_all_required_36l_families() -> None:
    keys = {item.key for item in REFERENCE_SECTOR_PACKS}
    assert {
        "retail-supermarket",
        "restaurant-hospitality",
        "pharmacy",
        "school-university",
        "government-public-service",
        "logistics",
        "manufacturing",
        "real-estate",
        "professional-services",
    } <= keys
    assert len(keys) == len(REFERENCE_SECTOR_PACKS)
    for pack in REFERENCE_SECTOR_PACKS:
        pack.validate()
        spec = pack.specification()
        assert spec["schema_version"] == 3
        assert spec["application_type"] == "universal_application"
        assert len(spec["domain_blueprint"]["entities"]) >= 3
        assert len(spec["domain_blueprint"]["workflows"]) >= 3


def test_pharmacy_and_government_packs_remain_human_authority_bounded() -> None:
    packs = {item.key: item for item in REFERENCE_SECTOR_PACKS}
    pharmacy = packs["pharmacy"]
    assert "licensed-pharmacist-review" in pharmacy.external_gates
    assert any("does not diagnose" in item.lower() for item in pharmacy.safety_boundaries)
    government = packs["government-public-service"]
    assert "authorized-human-public-decision" in government.external_gates
    assert any("autonomously" in item.lower() and "public-authority" in item.lower() for item in government.safety_boundaries)


def test_unlisted_sector_uses_same_composer_without_registry_code_fork(tmp_path: Path) -> None:
    pack = _aquaculture_pack()
    assert pack.key not in {item.key for item in REFERENCE_SECTOR_PACKS}
    receipt = build_sector_reference(pack, tmp_path / "custom")
    assert receipt.tests["passed"] is True
    assert receipt.entity_count == 4
    assert receipt.workflow_count == 2
    source = receipt.output_directory / "source"
    assert (source / "DOMAIN_BLUEPRINT.json").is_file()
    assert (source / "targets/api/app.py").is_file()
    assert (source / "targets/domain/schema.sql").is_file()
    assert (source / "targets/cli/main.py").is_file()


def test_all_reference_sectors_build_and_pass_local_end_to_end(tmp_path: Path) -> None:
    receipts = [
        build_sector_reference(pack, tmp_path / "references")
        for pack in REFERENCE_SECTOR_PACKS
    ]
    assert len(receipts) == len(REFERENCE_SECTOR_PACKS)
    assert all(item.tests["passed"] is True for item in receipts)
    assert all(item.file_count >= 12 for item in receipts)
    for receipt in receipts:
        saved = json.loads(
            (receipt.output_directory / "SECTOR_RECEIPT.json").read_text(encoding="utf-8")
        )
        assert saved["domain_sha256"] == receipt.domain_sha256
        assert saved["tests"]["checks"]["api_health"] is True
        assert saved["tests"]["checks"]["api_create_read_delete"] is True
        assert saved["tests"]["checks"]["sqlite_persistence"] is True
        assert saved["tests"]["checks"]["domain_blueprint_integrity"] is True
