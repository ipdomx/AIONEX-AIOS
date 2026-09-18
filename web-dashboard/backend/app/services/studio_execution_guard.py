"""Studio one-shot provenance, not a resource registry or a drain receipt.

An expired lease never authorizes replay. Caller transactions retain admission
and job locks through claim/start commit. Every guard explicitly keeps cleanup
unverified, including a successful function return.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import StudioJob

GUARD_KEY = "_execution_guard"
PROTOCOL = 1
PHASES = frozenset({"claimed", "executing", "returned", "unresolved"})


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def execution_guard(job: StudioJob) -> dict[str, Any] | None:
    if not isinstance(job.result_metadata, dict):
        return None
    guard = job.result_metadata.get(GUARD_KEY)
    if not isinstance(guard, dict) or set(guard) != {
        "protocol_version", "phase", "worker_incarnation",
        "admitted_generation", "cleanup_verified",
    }:
        return None
    if (
        type(guard["protocol_version"]) is not int
        or guard["protocol_version"] != PROTOCOL
        or not isinstance(guard["phase"], str) or guard["phase"] not in PHASES
        or not _uuid(guard["worker_incarnation"])
        or type(guard["admitted_generation"]) is not int
        or guard["admitted_generation"] < 7
        or guard["cleanup_verified"] is not False
    ):
        return None
    return dict(guard)


def set_phase(job: StudioJob, phase: str) -> None:
    guard = execution_guard(job)
    if guard is None or phase not in PHASES:
        raise ValueError("Studio execution provenance is invalid")
    job.result_metadata = {
        **job.result_metadata, GUARD_KEY: {**guard, "phase": phase},
    }


def pristine_conditions() -> tuple[ColumnElement[bool], ...]:
    """Filter before SKIP LOCKED so old ambiguous jobs cannot starve new work."""
    return (
        StudioJob.status == "queued", StudioJob.attempts == 0,
        StudioJob.max_attempts > 0, StudioJob.progress == 0,
        StudioJob.started_at.is_(None), StudioJob.completed_at.is_(None),
        StudioJob.cancelled_at.is_(None), StudioJob.lease_token.is_(None),
        StudioJob.error_code.is_(None), StudioJob.error_message.is_(None),
        StudioJob.safety_status == "pending",
        cast(StudioJob.safety_findings, JSONB) == [],
        cast(StudioJob.result_metadata, JSONB) == {},
        StudioJob.provider_mode == "provider_neutral",
        StudioJob.provider.is_(None), StudioJob.model.is_(None),
    )


def retry_has_no_execution_provenance(job: StudioJob) -> bool:
    """An explicit retry may only reset a never-started cancelled/failed row.

    Terminal status and an absent lease alone are not cleanup evidence. Any
    attempt, start, output, guard, moderation result or provider provenance blocks
    retry until a future evidence-based reconciliation contract exists.
    """
    return (
        type(job.attempts) is int and job.attempts == 0
        and job.started_at is None and job.lease_token is None
        and isinstance(job.result_metadata, dict) and not job.result_metadata
        and job.safety_status == "pending"
        and isinstance(job.safety_findings, list) and not job.safety_findings
        and job.provider_mode == "provider_neutral"
        and job.provider is None and job.model is None
    )
