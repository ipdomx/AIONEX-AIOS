from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TelegramChatType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramCommandState(str, Enum):
    RECEIVED = "received"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(slots=True)
class TelegramIdentity:
    telegram_user_id: str
    owner_id: str
    username: str | None = None
    display_name: str | None = None
    linked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True


@dataclass(slots=True)
class TelegramCommand:
    command_id: str
    telegram_user_id: str
    chat_id: str
    chat_type: TelegramChatType
    command: str
    arguments: tuple[str, ...] = ()
    state: TelegramCommandState = TelegramCommandState.RECEIVED
    response_text: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)
