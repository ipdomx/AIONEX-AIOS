from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .auth import TelegramIdentityService
from .models import TelegramCommand, TelegramCommandState


CommandHandler = Callable[[str, tuple[str, ...]], str]


class TelegramCommandRouter:
    def __init__(self, identities: TelegramIdentityService) -> None:
        self._identities = identities
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, command: str, handler: CommandHandler) -> None:
        normalized = self._normalize(command)
        if normalized in self._handlers:
            raise ValueError(f"command already registered: {normalized}")
        self._handlers[normalized] = handler

    def dispatch(self, request: TelegramCommand) -> TelegramCommand:
        try:
            identity = self._identities.require_active(request.telegram_user_id)
        except PermissionError:
            request.state = TelegramCommandState.REJECTED
            request.response_text = "Unauthorized Telegram identity."
            request.completed_at = datetime.now(timezone.utc)
            return request

        request.state = TelegramCommandState.AUTHORIZED
        handler = self._handlers.get(self._normalize(request.command))
        if handler is None:
            request.state = TelegramCommandState.REJECTED
            request.response_text = "Unknown command."
            request.completed_at = datetime.now(timezone.utc)
            return request

        request.state = TelegramCommandState.EXECUTING
        try:
            request.response_text = handler(identity.owner_id, request.arguments)
            request.state = TelegramCommandState.COMPLETED
        except Exception as exc:  # boundary converts failures into safe bot responses
            request.response_text = f"Command failed: {type(exc).__name__}"
            request.state = TelegramCommandState.FAILED
        request.completed_at = datetime.now(timezone.utc)
        return request

    @staticmethod
    def _normalize(command: str) -> str:
        value = command.strip().lower()
        if value.startswith("/"):
            value = value[1:]
        return value.split("@", 1)[0]
