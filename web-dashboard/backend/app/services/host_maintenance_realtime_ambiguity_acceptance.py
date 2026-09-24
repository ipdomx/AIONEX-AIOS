"""Source-only Realtime ambiguity acceptance before any Production 0064 rollout.

D9B4 is a read-only acceptance boundary for crash/cancellation/provider ambiguity.
It consumes the durable D9B3A drain snapshot and refuses acceptance while any
submitted/unresolved/active provider ownership, expired session ownership, or
legacy ambiguous recording start remains. It performs no provider I/O, no cleanup,
no settlement, no retry, no adoption and no admission transition.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.host_maintenance_admission import SessionFactory
from app.services.host_maintenance_realtime_drain import (
    RealtimeDrainSnapshot,
    measure_realtime_drain,
)


class RealtimeAmbiguityAcceptanceBlocked(RuntimeError):
    """Realtime provider ambiguity is still present and blocks rollout."""


@dataclass(frozen=True, slots=True)
class RealtimeAmbiguityAcceptance:
    """A sanitized source-only acceptance result for ambiguous Realtime state."""

    drain: RealtimeDrainSnapshot
    submitted_provider_ids: tuple[str, ...]
    active_provider_ids: tuple[str, ...]
    unresolved_provider_ids: tuple[str, ...]
    expired_unsettled_session_ids: tuple[str, ...]
    legacy_ambiguous_recording_ids: tuple[str, ...]
    ambiguity_free: bool
    source_acceptance_passed: bool
    provider_io_performed: bool = False
    automatic_settlement: bool = False
    automatic_retry: bool = False
    automatic_adoption: bool = False
    production_database_migrated: bool = False
    migration_0064_rollout_allowed: bool = False
    provider_drain_verified: bool = False
    full_host_closure: bool = False

    @property
    def blocker_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.submitted_provider_ids:
            reasons.append("provider_io_submitted_not_reconciled")
        if self.active_provider_ids:
            reasons.append("provider_resource_active_not_terminal")
        if self.unresolved_provider_ids:
            reasons.append("provider_ambiguity_unresolved")
        if self.expired_unsettled_session_ids:
            reasons.append("expired_participant_session_not_settled")
        if self.legacy_ambiguous_recording_ids:
            reasons.append("legacy_ambiguous_recording_start")
        if self.drain.known_blocker_count:
            reasons.append("durable_realtime_blockers_present")
        return tuple(dict.fromkeys(reasons))


async def evaluate_realtime_ambiguity_acceptance(
    *, session_factory: SessionFactory
) -> RealtimeAmbiguityAcceptance:
    """Evaluate ambiguity blockers without mutating DB, files, admission or provider."""
    drain = await measure_realtime_drain(session_factory=session_factory)
    submitted = tuple(
        item.id for item in drain.provider_resources if item.state == "submitted"
    )
    active = tuple(
        item.id for item in drain.provider_resources if item.state == "active"
    )
    unresolved = drain.unresolved_provider_ids
    expired_sessions = drain.expired_unsettled_session_ids
    legacy_ambiguous = drain.legacy_ambiguous_recording_ids
    ambiguity_free = not (
        submitted
        or active
        or unresolved
        or expired_sessions
        or legacy_ambiguous
        or drain.known_blocker_count
    )
    result = RealtimeAmbiguityAcceptance(
        drain=drain,
        submitted_provider_ids=submitted,
        active_provider_ids=active,
        unresolved_provider_ids=unresolved,
        expired_unsettled_session_ids=expired_sessions,
        legacy_ambiguous_recording_ids=legacy_ambiguous,
        ambiguity_free=ambiguity_free,
        source_acceptance_passed=ambiguity_free,
    )
    if not ambiguity_free:
        raise RealtimeAmbiguityAcceptanceBlocked(
            ",".join(result.blocker_reasons) or "realtime_ambiguity_blocked"
        )
    return result
