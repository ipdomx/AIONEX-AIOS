"""Read-only Owner triage of ambiguous Identity Media executions.

This module deliberately has no retry, submit, cancel, or billing operations.
A missing provider job ID is *not* evidence that the provider did not bill.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdentityMediaExecution

_REVIEW_STATUS = "needs_review"
_KNOWN_ERROR_CATEGORIES = frozenset(
    {"provider_submission_ambiguous", "identity_media_worker_error", "provider_job_missing"}
)


def safe_recovery_review_row(record: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only constrained operator facts, never provider IDs or payloads."""
    if record["status"] != _REVIEW_STATUS:
        raise ValueError("only explicitly review-required records may be surfaced")
    provider_known = bool(str(record.get("provider_job_id") or "").strip())
    secondary_known = bool(str(record.get("secondary_provider_job_id") or "").strip())
    code = record.get("error_code")
    category = code if code in _KNOWN_ERROR_CATEGORIES else "unclassified"
    created_at = record.get("created_at")
    return {
        "execution_id": str(record["id"]),
        "operation": str(record["operation"]),
        "provider": str(record["provider"]),
        "status": _REVIEW_STATUS,
        "provider_state": str(record["provider_state"]),
        "attempts": max(0, int(record["attempts"] or 0)),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
        "error_category": category,
        "provider_reference_recorded": provider_known or secondary_known,
        "review_kind": (
            "recorded_provider_reference_requires_check"
            if provider_known or secondary_known
            else "no_provider_reference_manual_reconciliation"
        ),
        "automatic_replay_allowed": False,
        "actual_provider_charge_verified": False,
        "needs_external_provenance_review": True,
    }


async def owner_identity_media_recovery_snapshot(
    session: AsyncSession, *, limit: int = 50
) -> dict[str, Any]:
    """Classify durable review records without mutating DB or querying providers."""
    if not 1 <= limit <= 100:
        raise ValueError("review limit must be between 1 and 100")
    where_review = IdentityMediaExecution.status == _REVIEW_STATUS
    missing_provider_refs = and_(
        or_(
            IdentityMediaExecution.provider_job_id.is_(None),
            IdentityMediaExecution.provider_job_id == "",
        ),
        or_(
            IdentityMediaExecution.secondary_provider_job_id.is_(None),
            IdentityMediaExecution.secondary_provider_job_id == "",
        ),
    )
    total = int(
        await session.scalar(
            select(func.count(IdentityMediaExecution.id)).where(where_review)
        )
        or 0
    )
    missing = int(
        await session.scalar(
            select(func.count(IdentityMediaExecution.id)).where(
                where_review, missing_provider_refs
            )
        )
        or 0
    )
    if missing > total:
        raise ValueError("review count is inconsistent")
    rows = (
        await session.execute(
            select(
                IdentityMediaExecution.id,
                IdentityMediaExecution.operation,
                IdentityMediaExecution.provider,
                IdentityMediaExecution.status,
                IdentityMediaExecution.provider_state,
                IdentityMediaExecution.attempts,
                IdentityMediaExecution.created_at,
                IdentityMediaExecution.error_code,
                IdentityMediaExecution.provider_job_id,
                IdentityMediaExecution.secondary_provider_job_id,
            )
            .where(where_review)
            .order_by(IdentityMediaExecution.created_at.asc(), IdentityMediaExecution.id.asc())
            .limit(limit)
        )
    ).mappings().all()
    if len(rows) > total:
        raise ValueError("review rows exceed total count")
    return {
        "status": "review_required" if total else "no_review_records",
        "total_review_required": total,
        "no_provider_reference": missing,
        "provider_reference_recorded": total - missing,
        "shown": len(rows),
        "truncated": total > len(rows),
        "executions": [safe_recovery_review_row(dict(row)) for row in rows],
        "automatic_replay_allowed": False,
        "actual_provider_charges_verified": False,
        "operator_action": "independently_reconcile_provider_history_and_billing",
        "provider_job_ids_returned": False,
        "raw_credentials_returned": False,
        "customer_identity_or_storage_paths_returned": False,
        "read_only": True,
    }
