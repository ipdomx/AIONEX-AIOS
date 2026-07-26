from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .channels import CommunicationChannel


class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class MessageState(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OutboundMessage:
    message_id: str
    recipient_id: str
    channel: CommunicationChannel
    subject: str
    body: str
    priority: MessagePriority = MessagePriority.NORMAL
    project_id: str | None = None
    organization_id: str | None = None
    state: MessageState = MessageState.QUEUED
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, state: MessageState) -> None:
        allowed = {
            MessageState.QUEUED: {MessageState.SENT, MessageState.FAILED, MessageState.CANCELLED},
            MessageState.SENT: {MessageState.DELIVERED, MessageState.FAILED},
            MessageState.DELIVERED: set(),
            MessageState.FAILED: {MessageState.QUEUED, MessageState.CANCELLED},
            MessageState.CANCELLED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid message transition: {self.state.value} -> {state.value}")
        self.state = state
        self.updated_at = datetime.now(timezone.utc)


class MessageStore:
    def __init__(self) -> None:
        self._messages: dict[str, OutboundMessage] = {}

    def add(self, message: OutboundMessage) -> OutboundMessage:
        if not message.message_id.strip() or not message.recipient_id.strip():
            raise ValueError("message_id and recipient_id are required")
        if not message.body.strip():
            raise ValueError("message body is required")
        if message.message_id in self._messages:
            raise ValueError(f"duplicate message_id: {message.message_id}")
        self._messages[message.message_id] = message
        return message

    def get(self, message_id: str) -> OutboundMessage:
        try:
            return self._messages[message_id]
        except KeyError as exc:
            raise LookupError(f"message not found: {message_id}") from exc

    def list_for_recipient(self, recipient_id: str) -> list[OutboundMessage]:
        return [item for item in self._messages.values() if item.recipient_id == recipient_id]

    def list_by_state(self, state: MessageState) -> list[OutboundMessage]:
        return [item for item in self._messages.values() if item.state is state]
