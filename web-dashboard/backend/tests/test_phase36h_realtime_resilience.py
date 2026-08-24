from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from app.realtime.resilience import (
    LiveMediaPrerequisiteEvidence,
    RecordingFailoverAttempt,
    RecordingFailoverEvidence,
    TurnFailureEvidence,
    TurnPathAttempt,
    evaluate_live_media_prerequisites,
    evaluate_part6c,
    evaluate_recording_failover,
    evaluate_turn_failure_path,
)


def _recording_attempt(attempt: int, outcome: str, artifacts: int) -> RecordingFailoverAttempt:
    digest = sha256(b"all-participant-consent").hexdigest()
    provenance = sha256(b"recording-provenance").hexdigest()
    return RecordingFailoverAttempt(
        attempt=attempt,
        outcome=outcome,
        consent_digest_sha256=digest,
        recording_key="rec-" + sha256(b"tenant-room-consent").hexdigest()[:40],
        retention_until=datetime(2026, 9, 24, tzinfo=UTC),
        provenance_sha256=provenance,
        artifact_count=artifacts,
    )


def test_turn_failure_path_uses_relay_fallback_without_auth_bypass() -> None:
    evidence = TurnFailureEvidence(
        attempts=(
            TurnPathAttempt("stun://stun.invalid:3478", "timeout", 50.0),
            TurnPathAttempt("turn://turn.invalid:3478?transport=udp", "connection_refused", 65.0),
            TurnPathAttempt("turns://turn.invalid:5349?transport=tcp", "success", 72.0, True),
        ),
        relay_required=True,
        credentials_reference_only=True,
    )
    result = evaluate_turn_failure_path(evidence)
    assert result["passed"] is True

    auth_bypass = TurnFailureEvidence(
        attempts=(
            TurnPathAttempt("turn://turn.invalid:3478?transport=udp", "auth_failed", 20.0),
            TurnPathAttempt("turns://turn.invalid:5349?transport=tcp", "success", 25.0, True),
        ),
        relay_required=True,
        credentials_reference_only=True,
    )
    assert evaluate_turn_failure_path(auth_bypass)["passed"] is False


def test_recording_failover_preserves_consent_retention_provenance_and_one_artifact() -> None:
    evidence = RecordingFailoverEvidence(
        attempts=(
            _recording_attempt(1, "worker_failed", 0),
            _recording_attempt(2, "completed", 1),
        ),
        duplicate_active_recordings=0,
        consent_preserved=True,
        retention_preserved=True,
        provenance_preserved=True,
        studio_ingestion_plans=1,
    )
    result = evaluate_recording_failover(evidence)
    assert result["passed"] is True

    duplicate = RecordingFailoverEvidence(
        attempts=evidence.attempts,
        duplicate_active_recordings=1,
        consent_preserved=True,
        retention_preserved=True,
        provenance_preserved=True,
        studio_ingestion_plans=1,
    )
    assert evaluate_recording_failover(duplicate)["passed"] is False


def test_live_media_prerequisites_are_source_safe_but_production_blocked() -> None:
    evidence = LiveMediaPrerequisiteEvidence(
        source_db_head="20260824_0041",
        production_db_revision="20260823_0039",
        source_images_digest_bound=True,
        secret_references_only=True,
        disabled_compose_profile=True,
        kubernetes_replicas_zero=True,
        public_media_ports_open=0,
        livekit_running=False,
        coturn_running=False,
        egress_running=False,
        provider_credentials_validated=False,
        public_turn_reachability_validated=False,
        sfu_soak_passed=False,
        recording_runtime_acceptance_passed=False,
    )
    result = evaluate_live_media_prerequisites(evidence)
    assert result["source_safe"] is True
    assert result["activation_ready"] is False
    assert "production_schema_applied" in result["blocking_reasons"]
    assert "public_turn_reachability_validated" in result["blocking_reasons"]


def test_part6c_passes_isolated_failure_gates_but_never_claims_production_ready() -> None:
    turn = TurnFailureEvidence(
        attempts=(
            TurnPathAttempt("turn://turn.invalid:3478?transport=udp", "timeout", 40.0),
            TurnPathAttempt("turns://turn.invalid:5349?transport=tcp", "success", 55.0, True),
        ),
        relay_required=True,
        credentials_reference_only=True,
    )
    recording = RecordingFailoverEvidence(
        attempts=(_recording_attempt(1, "worker_failed", 0), _recording_attempt(2, "completed", 1)),
        duplicate_active_recordings=0,
        consent_preserved=True,
        retention_preserved=True,
        provenance_preserved=True,
        studio_ingestion_plans=1,
    )
    prereq = LiveMediaPrerequisiteEvidence(
        source_db_head="20260824_0041",
        production_db_revision="20260823_0039",
        source_images_digest_bound=True,
        secret_references_only=True,
        disabled_compose_profile=True,
        kubernetes_replicas_zero=True,
        public_media_ports_open=0,
        livekit_running=False,
        coturn_running=False,
        egress_running=False,
        provider_credentials_validated=False,
        public_turn_reachability_validated=False,
        sfu_soak_passed=False,
        recording_runtime_acceptance_passed=False,
    )
    result = evaluate_part6c(turn=turn, recording=recording, prerequisites=prereq)
    assert result["passed"] is True
    assert result["claims"]["production_activation_ready"] is False
    assert result["claims"]["production_ready"] is False
