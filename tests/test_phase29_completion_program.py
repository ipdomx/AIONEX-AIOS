from __future__ import annotations

from pathlib import Path

from aios.completion_program import (
    BATCHES,
    ENDPOINT_BATCH,
    FEATURES,
    MODULE_BATCH,
    OWNER_PAGE_BATCH,
    VIP_PAGE_BATCH,
    completion_program_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def test_completion_batches_are_ordered_unique_and_models_providers_are_last() -> None:
    assert [batch.sequence for batch in BATCHES] == list(range(1, len(BATCHES) + 1))
    assert len({batch.batch_id for batch in BATCHES}) == len(BATCHES)
    assert BATCHES[-1].batch_id == "29J"
    assert BATCHES[-1].status == "deferred"
    assert "Models and providers" in BATCHES[-1].title


def test_complete_batches_contain_only_verified_features() -> None:
    by_batch = {
        batch.batch_id: [feature for feature in FEATURES if feature.batch_id == batch.batch_id]
        for batch in BATCHES
    }
    assert all(by_batch.values())
    for batch in BATCHES:
        if batch.status == "complete":
            assert all(feature.status == "verified" for feature in by_batch[batch.batch_id])
        if batch.status == "deferred":
            assert all(feature.status == "deferred" for feature in by_batch[batch.batch_id])


def test_every_feature_has_acceptance_and_completed_features_have_evidence() -> None:
    assert len({feature.feature_id for feature in FEATURES}) == len(FEATURES)
    batch_ids = {batch.batch_id for batch in BATCHES}
    for feature in FEATURES:
        assert feature.batch_id in batch_ids
        assert feature.acceptance
        if feature.status == "verified":
            assert feature.evidence
            for relative in feature.evidence:
                assert (ROOT / relative).exists(), relative


def test_every_current_aios_module_is_registered_exactly_once() -> None:
    actual = {
        path.name
        for path in (ROOT / "src/aios").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert set(MODULE_BATCH) == actual
    assert MODULE_BATCH["models"] == "29J"
    assert MODULE_BATCH["providers"] == "29J"


def test_every_current_owner_page_is_registered_exactly_once() -> None:
    actual = {
        path.parent.name
        for path in (ROOT / "web-dashboard/frontend/src/app/owner").glob("*/page.tsx")
    }
    assert set(OWNER_PAGE_BATCH) == actual


def test_every_current_vip_page_is_registered_exactly_once() -> None:
    base = ROOT / "vip-frontend/src/app"
    actual = {str(path.relative_to(base)) for path in base.glob("**/page.tsx")}
    assert set(VIP_PAGE_BATCH) == actual


def test_every_current_backend_endpoint_is_registered_exactly_once() -> None:
    base = ROOT / "web-dashboard/backend/app/api/v1/endpoints"
    actual = {path.stem for path in base.glob("*.py") if path.stem != "__init__"}
    assert set(ENDPOINT_BATCH) == actual
    assert ENDPOINT_BATCH["ai_agents"] == "29J"
    assert ENDPOINT_BATCH["ai_providers"] == "29J"


def test_snapshot_is_truthful_and_points_to_next_non_provider_batch() -> None:
    snapshot = completion_program_snapshot()
    assert snapshot["current_batch"] == "29I"
    assert snapshot["models_providers_batch"] == "29J"
    assert snapshot["completion"] < 100
    assert snapshot["verified_features"] == 22
    assert snapshot["deferred_features"] == 1
    assert len(snapshot["batches"]) == 10
