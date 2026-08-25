from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import professional_evidence as runtime


def citation(i: int) -> dict[str, str]:
    return {
        "citation_id": f"source-{i}",
        "title": f"Evidence source {i}",
        "uri": f"https://evidence.invalid/{i}",
        "source_sha256": (f"{i:x}" * 64)[:64],
    }


def test_high_stakes_evidence_requires_two_sources_and_never_claims_certification() -> (
    None
):
    with pytest.raises(ValueError, match="at least 2"):
        runtime._normalize_citations([citation(1)], high_stakes=True)
    rows, digest = runtime._normalize_citations(
        [citation(1), citation(2)], high_stakes=True
    )
    assert len(rows) == 2 and len(digest) == 64
    assert all(
        profile["certified"] is False for profile in runtime.RESIDENCY_PROFILES.values()
    )


def test_case_snapshot_exposes_only_pseudonymous_subject_reference() -> None:
    now = datetime.now(UTC)
    item = SimpleNamespace(
        id="case-1",
        workspace_id=None,
        case_mode="clinical_high_stakes",
        purpose="Review evidence",
        subject_ref_hash="a" * 64,
        request_summary="Redacted professional question.",
        status="pending_review",
        residency_profile="country-locked",
        retention_until=now + timedelta(days=30),
        citations=[citation(1), citation(2)],
        assistance={"final_professional_decision": False},
        evidence_digest="b" * 64,
        human_review_required=True,
        autonomous_decision_allowed=False,
        review_version=1,
        closed_at=None,
        created_at=now,
        updated_at=now,
    )
    snapshot = runtime.case_snapshot(item)
    assert snapshot["human_review_required"] is True
    assert snapshot["autonomous_decision_allowed"] is False
    assert "subject_reference" not in snapshot
    assert snapshot["subject_ref_hash"] == "a" * 64
