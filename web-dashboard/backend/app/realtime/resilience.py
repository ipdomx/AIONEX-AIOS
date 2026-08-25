"""Phase 36H.6C isolated TURN/recording failure and activation-readiness gates.

The module is deliberately provider-network-free. It evaluates bounded failure-path
and prerequisite evidence without opening media ports, starting LiveKit/Coturn/
Egress, applying production migrations, or reading raw provider credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from app.realtime.sfu import (
    COTURN_AMD64_DIGEST,
    LIVEKIT_EGRESS_AMD64_DIGEST,
    LIVEKIT_SERVER_AMD64_DIGEST,
)

_ALLOWED_ICE_SCHEMES = frozenset({"stun", "stuns", "turn", "turns"})
_ALLOWED_FAILURES = frozenset({"timeout", "connection_refused", "dns_failed", "auth_failed"})
_RETRYABLE_FAILURES = frozenset({"timeout", "connection_refused", "dns_failed"})


class RealtimeResilienceEvidenceError(ValueError):
    """36H.6C evidence is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class TurnPathAttempt:
    url: str
    outcome: str
    latency_ms: float
    selected: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url.strip())
        if parsed.scheme not in _ALLOWED_ICE_SCHEMES or not parsed.hostname:
            raise RealtimeResilienceEvidenceError("TURN path URL is invalid")
        if parsed.username or parsed.password or parsed.fragment:
            raise RealtimeResilienceEvidenceError("TURN path evidence must not embed credentials")
        if parsed.path not in {"", "/"}:
            raise RealtimeResilienceEvidenceError("TURN path URL must not contain a path")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if set(params) - {"transport"}:
            raise RealtimeResilienceEvidenceError("TURN path contains unsupported query parameters")
        if params.get("transport") not in {None, "udp", "tcp"}:
            raise RealtimeResilienceEvidenceError("TURN path transport is invalid")
        if self.outcome != "success" and self.outcome not in _ALLOWED_FAILURES:
            raise RealtimeResilienceEvidenceError("TURN path outcome is invalid")
        if self.latency_ms < 0:
            raise RealtimeResilienceEvidenceError("TURN path latency must be non-negative")
        if self.selected and self.outcome != "success":
            raise RealtimeResilienceEvidenceError("selected TURN path must be successful")


@dataclass(frozen=True, slots=True)
class TurnFailureEvidence:
    attempts: tuple[TurnPathAttempt, ...]
    relay_required: bool
    credentials_reference_only: bool
    cross_tenant_leaks: int = 0
    live_media_activated: bool = False
    production_mutated: bool = False

    def __post_init__(self) -> None:
        if len(self.attempts) < 2:
            raise RealtimeResilienceEvidenceError("TURN failover must exercise at least two paths")
        if self.cross_tenant_leaks < 0:
            raise RealtimeResilienceEvidenceError("cross-tenant leak count must be non-negative")

    def snapshot(self) -> dict[str, object]:
        return {
            "attempts": [
                {
                    "url": item.url,
                    "outcome": item.outcome,
                    "latency_ms": item.latency_ms,
                    "selected": item.selected,
                }
                for item in self.attempts
            ],
            "relay_required": self.relay_required,
            "credentials_reference_only": self.credentials_reference_only,
            "cross_tenant_leaks": self.cross_tenant_leaks,
            "live_media_activated": self.live_media_activated,
            "production_mutated": self.production_mutated,
        }


def evaluate_turn_failure_path(evidence: TurnFailureEvidence) -> dict[str, object]:
    selected_indexes = [index for index, item in enumerate(evidence.attempts) if item.selected]
    selected = evidence.attempts[selected_indexes[0]] if len(selected_indexes) == 1 else None
    selected_scheme = urlsplit(selected.url).scheme if selected is not None else None
    failures_before_selection = (
        evidence.attempts[: selected_indexes[0]] if selected_indexes else evidence.attempts
    )
    checks = {
        "relay_required": evidence.relay_required,
        "exactly_one_selected_path": len(selected_indexes) == 1,
        "fallback_exercised": bool(selected_indexes and selected_indexes[0] > 0),
        "selected_path_is_turn_relay": selected_scheme in {"turn", "turns"},
        "retryable_failures_only_before_selection": bool(failures_before_selection)
        and all(item.outcome in _RETRYABLE_FAILURES for item in failures_before_selection),
        "credentials_remained_reference_only": evidence.credentials_reference_only,
        "no_cross_tenant_leaks": evidence.cross_tenant_leaks == 0,
        "live_media_remained_disabled": not evidence.live_media_activated,
        "production_remained_unchanged": not evidence.production_mutated,
    }
    return {
        "gate": "36H.6C.turn-failure-path",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": evidence.snapshot(),
    }


@dataclass(frozen=True, slots=True)
class RecordingFailoverAttempt:
    attempt: int
    outcome: str
    consent_digest_sha256: str
    recording_key: str
    retention_until: datetime
    provenance_sha256: str
    artifact_count: int

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise RealtimeResilienceEvidenceError("recording attempt number must be positive")
        if self.outcome not in {"worker_failed", "completed"}:
            raise RealtimeResilienceEvidenceError("recording failover outcome is invalid")
        for field in (self.consent_digest_sha256, self.provenance_sha256):
            if len(field) != 64 or any(ch not in "0123456789abcdef" for ch in field.lower()):
                raise RealtimeResilienceEvidenceError("recording evidence digest must be SHA-256")
        if not self.recording_key.startswith("rec-"):
            raise RealtimeResilienceEvidenceError("recording key is not opaque")
        if self.artifact_count < 0:
            raise RealtimeResilienceEvidenceError("recording artifact count must be non-negative")
        if self.outcome == "worker_failed" and self.artifact_count != 0:
            raise RealtimeResilienceEvidenceError("failed recording attempt must not publish an artifact")
        if self.outcome == "completed" and self.artifact_count != 1:
            raise RealtimeResilienceEvidenceError("completed recording attempt must publish exactly one artifact")


@dataclass(frozen=True, slots=True)
class RecordingFailoverEvidence:
    attempts: tuple[RecordingFailoverAttempt, ...]
    duplicate_active_recordings: int
    consent_preserved: bool
    retention_preserved: bool
    provenance_preserved: bool
    studio_ingestion_plans: int
    live_egress_activated: bool = False
    production_mutated: bool = False

    def __post_init__(self) -> None:
        if len(self.attempts) < 2:
            raise RealtimeResilienceEvidenceError("recording failover requires at least two attempts")
        if self.duplicate_active_recordings < 0 or self.studio_ingestion_plans < 0:
            raise RealtimeResilienceEvidenceError("recording failover counters must be non-negative")

    def snapshot(self) -> dict[str, object]:
        return {
            "attempts": [
                {
                    "attempt": item.attempt,
                    "outcome": item.outcome,
                    "consent_digest_sha256": item.consent_digest_sha256,
                    "recording_key": item.recording_key,
                    "retention_until": item.retention_until.isoformat(),
                    "provenance_sha256": item.provenance_sha256,
                    "artifact_count": item.artifact_count,
                }
                for item in self.attempts
            ],
            "duplicate_active_recordings": self.duplicate_active_recordings,
            "consent_preserved": self.consent_preserved,
            "retention_preserved": self.retention_preserved,
            "provenance_preserved": self.provenance_preserved,
            "studio_ingestion_plans": self.studio_ingestion_plans,
            "live_egress_activated": self.live_egress_activated,
            "production_mutated": self.production_mutated,
        }


def evaluate_recording_failover(evidence: RecordingFailoverEvidence) -> dict[str, object]:
    failed = [item for item in evidence.attempts if item.outcome == "worker_failed"]
    completed = [item for item in evidence.attempts if item.outcome == "completed"]
    first = evidence.attempts[0]
    invariant_identity = all(
        item.recording_key == first.recording_key
        and item.consent_digest_sha256 == first.consent_digest_sha256
        and item.retention_until == first.retention_until
        and item.provenance_sha256 == first.provenance_sha256
        for item in evidence.attempts
    )
    checks = {
        "worker_failure_exercised": len(failed) >= 1,
        "exactly_one_completed_recovery": len(completed) == 1,
        "single_final_artifact": sum(item.artifact_count for item in evidence.attempts) == 1,
        "no_duplicate_active_recordings": evidence.duplicate_active_recordings == 0,
        "recording_identity_preserved": invariant_identity,
        "consent_preserved": evidence.consent_preserved,
        "retention_preserved": evidence.retention_preserved,
        "provenance_preserved": evidence.provenance_preserved,
        "studio_ingestion_plan_preserved": evidence.studio_ingestion_plans == 1,
        "live_egress_remained_disabled": not evidence.live_egress_activated,
        "production_remained_unchanged": not evidence.production_mutated,
    }
    return {
        "gate": "36H.6C.recording-failover",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": evidence.snapshot(),
    }


@dataclass(frozen=True, slots=True)
class LiveMediaPrerequisiteEvidence:
    source_db_head: str
    production_db_revision: str
    source_images_digest_bound: bool
    secret_references_only: bool
    disabled_compose_profile: bool
    kubernetes_replicas_zero: bool
    public_media_ports_open: int
    livekit_running: bool
    coturn_running: bool
    egress_running: bool
    provider_credentials_validated: bool
    public_turn_reachability_validated: bool
    sfu_soak_passed: bool
    recording_runtime_acceptance_passed: bool
    production_mutated: bool = False

    def __post_init__(self) -> None:
        if self.public_media_ports_open < 0:
            raise RealtimeResilienceEvidenceError("public media port count must be non-negative")


def _includes_realtime_schema(revision: str) -> bool:
    try:
        sequence = int(revision.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return False
    return sequence >= 41


def evaluate_live_media_prerequisites(evidence: LiveMediaPrerequisiteEvidence) -> dict[str, object]:
    source_checks = {
        "source_schema_available": _includes_realtime_schema(evidence.source_db_head),
        "immutable_images_bound": evidence.source_images_digest_bound,
        "secret_references_only": evidence.secret_references_only,
        "disabled_compose_profile": evidence.disabled_compose_profile,
        "kubernetes_replicas_zero": evidence.kubernetes_replicas_zero,
        "production_remained_unchanged": not evidence.production_mutated,
    }
    runtime_checks = {
        "production_schema_applied": _includes_realtime_schema(evidence.production_db_revision),
        "public_media_ports_available": evidence.public_media_ports_open > 0,
        "livekit_running": evidence.livekit_running,
        "coturn_running": evidence.coturn_running,
        "egress_running": evidence.egress_running,
        "provider_credentials_validated": evidence.provider_credentials_validated,
        "public_turn_reachability_validated": evidence.public_turn_reachability_validated,
        "sfu_soak_passed": evidence.sfu_soak_passed,
        "recording_runtime_acceptance_passed": evidence.recording_runtime_acceptance_passed,
    }
    blockers = [name for name, passed in runtime_checks.items() if not passed]
    return {
        "gate": "36H.6C.live-media-prerequisites",
        "source_safe": all(source_checks.values()),
        "activation_ready": all(source_checks.values()) and all(runtime_checks.values()),
        "source_checks": source_checks,
        "runtime_checks": runtime_checks,
        "blocking_reasons": blockers,
        "candidate_images": {
            "livekit_server_amd64_digest": LIVEKIT_SERVER_AMD64_DIGEST,
            "coturn_amd64_digest": COTURN_AMD64_DIGEST,
            "egress_amd64_digest": LIVEKIT_EGRESS_AMD64_DIGEST,
        },
    }


def evaluate_part6c(
    *,
    turn: TurnFailureEvidence,
    recording: RecordingFailoverEvidence,
    prerequisites: LiveMediaPrerequisiteEvidence,
) -> dict[str, object]:
    turn_result = evaluate_turn_failure_path(turn)
    recording_result = evaluate_recording_failover(recording)
    prereq_result = evaluate_live_media_prerequisites(prerequisites)
    passed = bool(turn_result["passed"] and recording_result["passed"] and prereq_result["source_safe"])
    return {
        "gate": "36H.6C",
        "passed": passed,
        "turn_failure_path": turn_result,
        "recording_failover": recording_result,
        "live_media_prerequisites": prereq_result,
        "claims": {
            "turn_failure_path": "isolated_evidence_acceptance",
            "recording_failover": "isolated_evidence_acceptance",
            "live_media_runtime": "not_tested",
            "production_activation_ready": bool(prereq_result["activation_ready"]),
            "production_ready": False,
        },
    }
