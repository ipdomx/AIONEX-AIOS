"""Source contract for FR-06C5D9B2A durable Realtime provider ownership."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "web-dashboard/backend/app/db/models.py"
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
MIGRATION = ROOT / "web-dashboard/backend/alembic/versions/20260920_0064_realtime_provider_resources.py"
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B2A-realtime-provider-resource-ledger.md"


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_provider_resource_ledger_source"]


def test_permanent_provider_registry_is_explicit_and_not_generic_cycle_reuse():
    models = MODELS.read_text()
    assert 'class RealtimeProviderResourceOwnership(Base):' in models
    assert '__tablename__ = "realtime_provider_resources"' in models
    block = models[models.index('class RealtimeProviderResourceOwnership'):models.index('class IdentityMediaExecution')]
    for field in (
        "organization_id", "resource_kind", "local_resource_id", "owner_incarnation",
        "admitted_generation", "admitted_operation_id", "ownership_nonce", "state",
        "provider_ref_sha256", "expires_at", "provider_started_at", "settled_at",
        "unresolved_reason",
    ):
        assert field in block
    assert "ForeignKey(" not in block
    assert "host_maintenance_work_cycles" not in block
    assert "uq_realtime_provider_resource_unfinished_local" in block
    assert "postgresql_where=text(\"state != 'settled'\")" in block


def test_migration_is_linear_permanent_and_source_only():
    text = MIGRATION.read_text()
    assert 'revision = "20260920_0064"' in text
    assert 'down_revision = "20260920_0063"' in text
    assert 'name = "realtime_provider_resources"' in text
    assert 'raise RuntimeError("Realtime provider ownership evidence cannot be discarded by downgrade")' in text
    for forbidden in ("realtime_rooms", "realtime_participants", "realtime_recordings", "livekit", "http://", "https://"):
        assert forbidden not in text.lower()


def test_registry_requires_commit_then_same_generation_before_provider_io():
    text = SERVICE.read_text()
    assert "await require_realtime_admission(session)" in text
    assert "authority.generation != owner.admitted_generation" in text
    assert "authority.operation_id != owner.admitted_operation_id" in text
    assert 'row.state = "submitted"' in text
    assert "session.commit(" not in text
    assert "automatic" not in text.lower()


def test_submitted_or_active_work_cannot_be_erased_as_not_started():
    text = SERVICE.read_text()
    assert 'row.state not in {"submitted", "active", "unresolved"}' in text
    assert 'row.state != "reserved" or row.provider_started_at is not None' in text
    assert 'row.state = "unresolved"' in text
    assert 'row.unresolved_reason = row.unresolved_reason or reason' in text


def test_plan_keeps_route_wiring_and_production_open():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B4"
    assert item["source_implementation_present"] is True
    assert item["provider_routes_wired"] is False
    assert item["intent_commits_before_provider_capability"] is True
    assert item["provider_start_rechecks_same_open_generation"] is True
    assert item["submitted_or_active_ambiguity_is_retained"] is True
    assert item["automatic_takeover"] is False
    assert item["automatic_retry"] is False
    assert item["one_unfinished_attempt_per_local_resource"] is True
    assert item["settled_history_retained"] is True
    assert item["explicit_retry_after_settlement_permitted"] is True
    assert item["production_database_migrated"] is False
    assert item["production_deployment_verified"] is False
    assert item["production_execution_performed"] is False
    assert item["session_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()


def test_backend_shipped_head_advances_to_0064():
    text = (ROOT / "web-dashboard/backend/tests/test_database_settings.py").read_text()
    assert 'frozenset({"20260920_0064"})' in text
    assert '("20260920_0063", False)' in text
    assert '("20260920_0064", True)' in text
