"""Source-only Phase 36H recording, retention, provenance, and Studio plans.

No provider SDK is imported and no network, filesystem, database, or Egress
mutation is performed here. Runtime activation is a later Phase 36H gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from app.realtime.sfu import LIVEKIT_EGRESS_AMD64_DIGEST, LIVEKIT_EGRESS_VERSION


class RecordingPolicyError(ValueError):
    """Recording policy or consent is invalid."""


class RecordingRuntimeDisabledError(RuntimeError):
    """A runtime recording mutation was attempted before activation."""


_ALLOWED_MEDIA = {"audio", "audio_video"}
_ALLOWED_FORMATS = {"mp4", "webm", "ogg"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _opaque(*parts: str, prefix: str) -> str:
    material = "\x00".join(parts)
    if not all(part.strip() for part in parts):
        raise RecordingPolicyError("recording identity inputs must be non-empty")
    return prefix + sha256(material.encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True, slots=True)
class ParticipantRecordingConsent:
    participant_id: str
    consented: bool
    consent_version: str
    consented_at: datetime | None

    def __post_init__(self) -> None:
        if not self.participant_id.strip():
            raise RecordingPolicyError("participant id is required")
        if len(self.consent_version.strip()) < 4:
            raise RecordingPolicyError("recording consent version is invalid")
        if self.consented and self.consented_at is None:
            raise RecordingPolicyError("consented participant requires consent timestamp")


@dataclass(frozen=True, slots=True)
class RecordingPolicy:
    retention_days: int = 30
    max_retention_days: int = 90
    output_format: str = "mp4"
    media_mode: str = "audio_video"
    require_all_participants: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.retention_days <= self.max_retention_days <= 365:
            raise RecordingPolicyError("recording retention bounds are invalid")
        if self.output_format not in _ALLOWED_FORMATS:
            raise RecordingPolicyError("unsupported recording output format")
        if self.media_mode not in _ALLOWED_MEDIA:
            raise RecordingPolicyError("unsupported recording media mode")
        if not self.require_all_participants:
            raise RecordingPolicyError("all-participant consent is mandatory")


@dataclass(frozen=True, slots=True)
class RecordingPlan:
    organization_fingerprint: str
    room_fingerprint: str
    provider_room_name: str
    recording_key: str
    output_format: str
    media_mode: str
    retention_until: datetime
    participant_count: int
    consent_count: int
    consent_digest_sha256: str
    provenance: tuple[dict[str, Any], ...]
    egress_runtime_enabled: bool = False

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "organization_fingerprint": self.organization_fingerprint,
            "room_fingerprint": self.room_fingerprint,
            "provider_room_name": self.provider_room_name,
            "recording_key": self.recording_key,
            "output_format": self.output_format,
            "media_mode": self.media_mode,
            "retention_until": self.retention_until.isoformat(),
            "participant_count": self.participant_count,
            "consent_count": self.consent_count,
            "consent_digest_sha256": self.consent_digest_sha256,
            "provenance": list(self.provenance),
            "egress_runtime_enabled": self.egress_runtime_enabled,
            "egress_version": LIVEKIT_EGRESS_VERSION,
            "egress_amd64_digest": LIVEKIT_EGRESS_AMD64_DIGEST,
            "raw_participant_ids_returned": False,
            "raw_consent_tokens_returned": False,
        }


@dataclass(frozen=True, slots=True)
class StudioRecordingIngestionPlan:
    organization_fingerprint: str
    recording_key: str
    title: str
    filename: str
    media_type: str
    asset_type: str
    retention_until: datetime
    provenance: tuple[dict[str, Any], ...]
    mutation_allowed: bool = False

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "organization_fingerprint": self.organization_fingerprint,
            "recording_key": self.recording_key,
            "title": self.title,
            "filename": self.filename,
            "media_type": self.media_type,
            "asset_type": self.asset_type,
            "retention_until": self.retention_until.isoformat(),
            "provenance": list(self.provenance),
            "mutation_allowed": self.mutation_allowed,
        }


class RecordingAuthority:
    """Pure planning authority; runtime mutations are fail-closed."""

    def plan_recording(
        self,
        *,
        organization_id: str,
        room_id: str,
        provider_room_name: str,
        consents: tuple[ParticipantRecordingConsent, ...],
        policy: RecordingPolicy,
        now: datetime | None = None,
    ) -> RecordingPlan:
        if not consents:
            raise RecordingPolicyError("recording requires at least one participant")
        participant_ids = [item.participant_id for item in consents]
        if len(set(participant_ids)) != len(participant_ids):
            raise RecordingPolicyError("duplicate participant consent entries are forbidden")
        missing = [item for item in consents if not item.consented or item.consented_at is None]
        if missing:
            raise RecordingPolicyError("all active participants must explicitly consent")
        ordered = sorted(consents, key=lambda item: item.participant_id)
        consent_material = "|".join(
            f"{item.participant_id}:{item.consent_version}:{item.consented_at.isoformat()}"
            for item in ordered
            if item.consented_at is not None
        )
        consent_digest = sha256(consent_material.encode("utf-8")).hexdigest()
        issued_at = now or _utcnow()
        recording_key = _opaque(organization_id, room_id, consent_digest, prefix="rec-")
        provenance = (
            {
                "kind": "realtime_recording_consent",
                "consent_digest_sha256": consent_digest,
                "participant_count": len(consents),
                "consent_count": len(consents),
                "consent_model": "all_active_participants_explicit",
            },
            {
                "kind": "realtime_recording_policy",
                "output_format": policy.output_format,
                "media_mode": policy.media_mode,
                "retention_days": policy.retention_days,
                "provider": "livekit-egress-candidate",
                "provider_runtime_enabled": False,
            },
        )
        return RecordingPlan(
            organization_fingerprint=sha256(organization_id.encode()).hexdigest(),
            room_fingerprint=sha256(room_id.encode()).hexdigest(),
            provider_room_name=provider_room_name,
            recording_key=recording_key,
            output_format=policy.output_format,
            media_mode=policy.media_mode,
            retention_until=issued_at + timedelta(days=policy.retention_days),
            participant_count=len(consents),
            consent_count=len(consents),
            consent_digest_sha256=consent_digest,
            provenance=provenance,
        )

    def plan_studio_ingestion(
        self,
        plan: RecordingPlan,
        *,
        title: str,
    ) -> StudioRecordingIngestionPlan:
        clean_title = title.strip()
        if not clean_title or len(clean_title) > 240:
            raise RecordingPolicyError("recording title is invalid")
        extension = plan.output_format
        media_type = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "ogg": "audio/ogg",
        }[extension]
        filename = f"{plan.recording_key}.{extension}"
        provenance = (
            *plan.provenance,
            {
                "kind": "studio_ingestion_plan",
                "recording_key": plan.recording_key,
                "retention_until": plan.retention_until.isoformat(),
                "source": "realtime-recording",
                "mutation_allowed": False,
            },
        )
        return StudioRecordingIngestionPlan(
            organization_fingerprint=plan.organization_fingerprint,
            recording_key=plan.recording_key,
            title=clean_title,
            filename=filename,
            media_type=media_type,
            asset_type="realtime_recording",
            retention_until=plan.retention_until,
            provenance=provenance,
        )

    async def start_egress(self, plan: RecordingPlan) -> None:
        del plan
        raise RecordingRuntimeDisabledError(
            "LiveKit Egress runtime is disabled until the Phase 36H activation gate"
        )

    async def ingest_into_studio(self, plan: StudioRecordingIngestionPlan) -> None:
        del plan
        raise RecordingRuntimeDisabledError(
            "Studio recording mutation is disabled until runtime acceptance"
        )
