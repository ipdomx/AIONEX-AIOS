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
