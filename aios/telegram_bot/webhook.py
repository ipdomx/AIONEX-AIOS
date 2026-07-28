from __future__ import annotations

import hmac
from dataclasses import dataclass

from .models import TelegramChatType, TelegramCommand


@dataclass(slots=True)
class TelegramUpdate:
    update_id: str
    telegram_user_id: str
    chat_id: str
    chat_type: TelegramChatType
    text: str


class TelegramWebhookService:
    def __init__(self, *, secret_token: str) -> None:
        if len(secret_token) < 16:
            raise ValueError("Telegram webhook secret is too short")
        self._secret_token = secret_token
        self._seen_updates: set[str] = set()

    def verify(self, supplied_secret: str) -> bool:
        return hmac.compare_digest(self._secret_token, supplied_secret)

    def accept(self, update: TelegramUpdate) -> TelegramCommand | None:
        if update.update_id in self._seen_updates:
            return None
        self._seen_updates.add(update.update_id)
        text = update.text.strip()
        if not text.startswith("/"):
            return None
        parts = text.split()
        return TelegramCommand(
            command_id=f"tg-{update.update_id}",
            telegram_user_id=update.telegram_user_id,
            chat_id=update.chat_id,
            chat_type=update.chat_type,
            command=parts[0],
            arguments=tuple(parts[1:]),
            metadata={"update_id": update.update_id},
        )
