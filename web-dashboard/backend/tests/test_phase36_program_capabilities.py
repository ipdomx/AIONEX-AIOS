from __future__ import annotations

import pytest

from app.api.v1.endpoints.capabilities import phase36_capabilities


@pytest.mark.asyncio
async def test_phase36_public_capability_snapshot_is_truthful_and_non_secret() -> None:
    payload = await phase36_capabilities()
    assert payload["authoritative"] is True
    assert payload["minimum_concurrent_users"] == 1000
    assert payload["current_batch"] == "36E"
    batch_statuses = {batch["batch_id"]: batch["status"] for batch in payload["batches"]}
    assert batch_statuses["36B"] == "complete"
    assert batch_statuses["36C"] == "complete"
    assert batch_statuses["36D"] == "complete"
    assert batch_statuses["36E"] == "in_progress"
    batch36d = next(batch for batch in payload["batches"] if batch["batch_id"] == "36D")
    assert {item["capability_id"] for item in batch36d["capabilities"]} == {"creative-asset-graph", "media-render-transcode", "object-storage-media"}
    assert all(item["maturity"] == "runtime_verified" for item in batch36d["capabilities"])
    assert payload["completion"] < 100
    assert payload["production_ready_capabilities"] < payload["total_capabilities"]
    rendered = repr(payload).lower()
    for forbidden in ("api_key", "password", "authorization", "credential_value"):
        assert forbidden not in rendered
