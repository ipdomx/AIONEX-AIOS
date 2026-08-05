from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TelegramMessage:
    chat_id: str
    text: str
    parse_mode: str | None = None
    disable_notification: bool = False


@dataclass(slots=True)
class TelegramDelivery:
    chat_id: str
    message_id: str
    accepted: bool


class TelegramTransport(Protocol):
    def send_message(self, token: str, message: TelegramMessage) -> TelegramDelivery: ...

    def set_webhook(self, token: str, url: str, secret_token: str) -> bool: ...

    def delete_webhook(self, token: str) -> bool: ...


class TelegramBotClient:
    def __init__(self, *, token: str, transport: TelegramTransport) -> None:
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._transport = transport

    def send(self, message: TelegramMessage) -> TelegramDelivery:
        if not message.chat_id or not message.text.strip():
            raise ValueError("chat_id and text are required")
        return self._transport.send_message(self._token, message)

    def configure_webhook(self, *, url: str, secret_token: str) -> None:
        if not url.startswith("https://"):
            raise ValueError("Telegram webhook must use HTTPS")
        if len(secret_token) < 16:
            raise ValueError("Telegram webhook secret is too short")
        if not self._transport.set_webhook(self._token, url, secret_token):
            raise RuntimeError("Telegram rejected webhook configuration")

    def remove_webhook(self) -> None:
        if not self._transport.delete_webhook(self._token):
            raise RuntimeError("Telegram rejected webhook removal")
