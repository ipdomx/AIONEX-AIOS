"""Phase 36H scale/failover acceptance evidence helpers.

This module is deliberately network-free. It evaluates deterministic evidence
produced by isolated realtime load/failover tests and never activates SFU,
TURN, recording, public ports, or production migrations.
"""
from __future__ import annotations

from dataclasses import dataclass


class RealtimeScaleEvidenceError(ValueError):
    """Scale evidence is incomplete or violates the Phase 36H gate."""


@dataclass(frozen=True, slots=True)
class RealtimeScaleEvidence:
    requested_clients: int
    admitted_clients: int
    delivered_events: int
    cross_tenant_leaks: int
    duplicate_deliveries: int
    failed_deliveries: int
    node_failures: int
    recovered_clients: int
    stale_subscriptions: int
    p95_delivery_ms: float
    live_media_activated: bool = False
    production_mutated: bool = False

    def __post_init__(self) -> None:
        integers = {
            "requested_clients": self.requested_clients,
            "admitted_clients": self.admitted_clients,
            "delivered_events": self.delivered_events,
            "cross_tenant_leaks": self.cross_tenant_leaks,
            "duplicate_deliveries": self.duplicate_deliveries,
            "failed_deliveries": self.failed_deliveries,
            "node_failures": self.node_failures,
            "recovered_clients": self.recovered_clients,
            "stale_subscriptions": self.stale_subscriptions,
        }
        if any(value < 0 for value in integers.values()):
            raise RealtimeScaleEvidenceError("scale counters must be non-negative")
        if self.requested_clients < 1:
            raise RealtimeScaleEvidenceError("requested_clients must be positive")
        if self.admitted_clients > self.requested_clients:
            raise RealtimeScaleEvidenceError("admitted_clients cannot exceed requested_clients")
        if self.recovered_clients > self.admitted_clients:
            raise RealtimeScaleEvidenceError("recovered_clients cannot exceed admitted_clients")
        if self.p95_delivery_ms < 0:
            raise RealtimeScaleEvidenceError("p95_delivery_ms must be non-negative")

    def snapshot(self) -> dict[str, object]:
        return {
            "requested_clients": self.requested_clients,
            "admitted_clients": self.admitted_clients,
            "delivered_events": self.delivered_events,
            "cross_tenant_leaks": self.cross_tenant_leaks,
            "duplicate_deliveries": self.duplicate_deliveries,
            "failed_deliveries": self.failed_deliveries,
            "node_failures": self.node_failures,
            "recovered_clients": self.recovered_clients,
            "stale_subscriptions": self.stale_subscriptions,
            "p95_delivery_ms": self.p95_delivery_ms,
            "live_media_activated": self.live_media_activated,
            "production_mutated": self.production_mutated,
        }


def evaluate_part6a(evidence: RealtimeScaleEvidence) -> dict[str, object]:
    """Evaluate the source-only 36H.6A gate for 1000-client backplane/failover tests."""
    checks = {
        "at_least_1000_clients": evidence.requested_clients >= 1000,
        "all_clients_admitted": evidence.admitted_clients == evidence.requested_clients,
        "no_cross_tenant_leaks": evidence.cross_tenant_leaks == 0,
        "no_duplicate_deliveries": evidence.duplicate_deliveries == 0,
        "no_failed_deliveries": evidence.failed_deliveries == 0,
        "node_loss_exercised": evidence.node_failures >= 1,
        "all_clients_recovered": evidence.recovered_clients == evidence.admitted_clients,
        "no_stale_subscriptions": evidence.stale_subscriptions == 0,
        "bounded_p95_delivery": evidence.p95_delivery_ms <= 250.0,
        "live_media_remained_disabled": not evidence.live_media_activated,
        "production_remained_unchanged": not evidence.production_mutated,
    }
    return {
        "gate": "36H.6A",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": evidence.snapshot(),
        "claims": {
            "websocket_backplane_scale": "isolated_source_acceptance",
            "live_media_scale": "not_tested",
            "production_ready": False,
        },
    }


@dataclass(frozen=True, slots=True)
class RealtimeScaleRuntimeEvidence:
    """Isolated PostgreSQL/Redis evidence for the 36H.6B gate."""

    requested_admissions: int
    admitted_grants: int
    consumed_grants: int
    connected_participants: int
    admission_rejections: int
    tenant_count: int
    room_count: int
    node_failures: int
    failed_node_participants: int
    reaped_presences: int
    recovered_presences: int
    stale_redis_subscribers: int
    redis_delivered_events: int
    redis_cross_tenant_leaks: int
    redis_duplicate_deliveries: int
    redis_failed_deliveries: int
    p95_admission_ms: float
    p95_redis_delivery_ms: float
    live_media_activated: bool = False
    production_mutated: bool = False

    def __post_init__(self) -> None:
        counters = (
            self.requested_admissions,
            self.admitted_grants,
            self.consumed_grants,
            self.connected_participants,
            self.admission_rejections,
            self.tenant_count,
            self.room_count,
            self.node_failures,
            self.failed_node_participants,
            self.reaped_presences,
            self.recovered_presences,
            self.stale_redis_subscribers,
            self.redis_delivered_events,
            self.redis_cross_tenant_leaks,
            self.redis_duplicate_deliveries,
            self.redis_failed_deliveries,
        )
        if any(value < 0 for value in counters):
            raise RealtimeScaleEvidenceError("runtime scale counters must be non-negative")
        if self.requested_admissions < 1 or self.tenant_count < 1 or self.room_count < 1:
            raise RealtimeScaleEvidenceError("runtime scale request/tenant/room counts must be positive")
        if self.p95_admission_ms < 0 or self.p95_redis_delivery_ms < 0:
            raise RealtimeScaleEvidenceError("runtime latency values must be non-negative")

    def snapshot(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def evaluate_part6b(evidence: RealtimeScaleRuntimeEvidence) -> dict[str, object]:
    """Evaluate isolated real PostgreSQL/Redis admission and failover evidence."""

    checks = {
        "at_least_1000_admissions": evidence.requested_admissions >= 1000,
        "all_grants_admitted": evidence.admitted_grants == evidence.requested_admissions,
        "all_grants_consumed": evidence.consumed_grants == evidence.requested_admissions,
        "all_participants_connected": evidence.connected_participants == evidence.requested_admissions,
        "no_admission_rejections": evidence.admission_rejections == 0,
        "multi_tenant_exercised": evidence.tenant_count >= 10,
        "one_room_per_tenant": evidence.room_count == evidence.tenant_count,
        "node_loss_exercised": evidence.node_failures >= 1,
        "failed_node_presence_reaped": evidence.reaped_presences == evidence.failed_node_participants,
        "all_failed_node_presence_recovered": evidence.recovered_presences == evidence.failed_node_participants,
        "no_stale_redis_subscribers": evidence.stale_redis_subscribers == 0,
        "redis_delivery_complete": evidence.redis_delivered_events == evidence.requested_admissions,
        "no_redis_cross_tenant_leaks": evidence.redis_cross_tenant_leaks == 0,
        "no_redis_duplicate_deliveries": evidence.redis_duplicate_deliveries == 0,
        "no_redis_failed_deliveries": evidence.redis_failed_deliveries == 0,
        "bounded_admission_p95": evidence.p95_admission_ms <= 2000.0,
        "bounded_redis_delivery_p95": evidence.p95_redis_delivery_ms <= 500.0,
        "live_media_remained_disabled": not evidence.live_media_activated,
        "production_remained_unchanged": not evidence.production_mutated,
    }
    return {
        "gate": "36H.6B",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": evidence.snapshot(),
        "claims": {
            "postgres_admission_scale": "isolated_runtime_acceptance",
            "redis_backplane_scale": "isolated_runtime_acceptance",
            "live_media_scale": "not_tested",
            "production_ready": False,
        },
    }
