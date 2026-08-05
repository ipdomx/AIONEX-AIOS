from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    previous_hash: str = ""
    event_hash: str = ""


class OwnerAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(
        self,
        *,
        event_id: str,
        actor_id: str,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        with self._lock:
            if any(event.event_id == event_id for event in self._events):
                raise ValueError(f"duplicate audit event: {event_id}")
            previous_hash = self._events[-1].event_hash if self._events else "GENESIS"
            created_at = datetime.now(timezone.utc)
            data = {
                "event_id": event_id,
                "actor_id": actor_id,
                "action": action,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "payload": payload or {},
                "created_at": created_at.isoformat(),
                "previous_hash": previous_hash,
            }
            event_hash = sha256(dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            event = AuditEvent(
                event_id=event_id,
                actor_id=actor_id,
                action=action,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=dict(payload or {}),
                created_at=created_at,
                previous_hash=previous_hash,
                event_hash=event_hash,
            )
            self._events.append(event)
            return event

    def list_events(self, *, subject_type: str | None = None, subject_id: str | None = None) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(
                event
                for event in self._events
                if (subject_type is None or event.subject_type == subject_type)
                and (subject_id is None or event.subject_id == subject_id)
            )

    def verify_chain(self) -> bool:
        with self._lock:
            previous_hash = "GENESIS"
            for event in self._events:
                data = {
                    "event_id": event.event_id,
                    "actor_id": event.actor_id,
                    "action": event.action,
                    "subject_type": event.subject_type,
                    "subject_id": event.subject_id,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                    "previous_hash": previous_hash,
                }
                expected = sha256(dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if event.previous_hash != previous_hash or event.event_hash != expected:
                    return False
                previous_hash = event.event_hash
            return True
