from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app.services.telegram_worker import (
    TelegramBotAPI,
    _command_name,
    healthcheck,
    load_bot_token,
    parse_inbound_message,
)


def test_token_file_requires_private_regular_file(tmp_path: Path) -> None:
    token = tmp_path / "bot-token"
    token.write_text("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi", encoding="utf-8")
    token.chmod(0o600)
    assert load_bot_token(token).startswith("123456789:")

    token.chmod(0o644)
    with pytest.raises(ValueError, match="group/world"):
        load_bot_token(token)

    token.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(token)
    with pytest.raises(ValueError, match="missing or unsafe"):
        load_bot_token(link)


def test_token_never_appears_in_object_representation() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"
    api = TelegramBotAPI(token)
    try:
        assert token not in repr(api)
    finally:
        import asyncio

        asyncio.run(api.close())


def test_inbound_message_parsing_and_command_normalization() -> None:
    update = {
        "update_id": 42,
        "message": {
            "from": {"id": 1001},
            "chat": {"id": 1001, "type": "private"},
            "text": "/Status@AionexBot now",
        },
    }
    parsed = parse_inbound_message(update)
    assert parsed is not None
    assert parsed.update_id == 42
    assert parsed.user_id == 1001
    assert parsed.chat_type == "private"
    assert _command_name(parsed.text) == "status"
    assert parse_inbound_message({"update_id": 43, "message": {}}) is None


def test_healthcheck_rejects_missing_stale_and_stopped_state(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    assert healthcheck(path) == 1

    path.write_text(
        json.dumps({"status": "running", "checked_at_epoch": time.time()}),
        encoding="utf-8",
    )
    assert healthcheck(path) == 0

    path.write_text(
        json.dumps({"status": "running", "checked_at_epoch": time.time() - 300}),
        encoding="utf-8",
    )
    assert healthcheck(path) == 1

    path.write_text(
        json.dumps({"status": "stopped", "checked_at_epoch": time.time()}),
        encoding="utf-8",
    )
    assert healthcheck(path) == 1


def test_production_compose_keeps_telegram_optional_and_external_secret() -> None:
    repository = Path(__file__).resolve().parents[3]
    for compose_path in (
        repository / "web-dashboard/docker-compose.production.yml",
        repository / "deploy/production/docker-compose.production.yml",
    ):
        compose = compose_path.read_text(encoding="utf-8")
        assert "telegram-worker:" in compose
        assert 'profiles: ["telegram"]' in compose
        assert "app.services.telegram_worker" in compose
        assert "AIOS_TELEGRAM_BOT_TOKEN_HOST_FILE" in compose
        assert "/run/secrets/aionex/telegram-bot-token:ro" in compose
        assert "TELEGRAM_BOT_TOKEN=" not in compose


def test_entrypoint_copies_telegram_token_before_privilege_drop() -> None:
    repository = Path(__file__).resolve().parents[3]
    entrypoint = (
        repository / "web-dashboard/backend/scripts/docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    telegram_copy = entrypoint.index("telegram_token_source=")
    privilege_drop = entrypoint.index('exec gosu aionex "$@"')
    assert telegram_copy < privilege_drop
    assert "install -m 0400 -o aionex -g aionex" in entrypoint

class _FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_worker_exposes_whoami_but_rejects_unlisted_operations(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.telegram_worker import TelegramInboundMessage, TelegramOperationsWorker

    monkeypatch.setattr(settings, "AIOS_TELEGRAM_ALLOWED_USERS", [])
    api = _FakeTelegramAPI()
    worker = TelegramOperationsWorker(api)  # type: ignore[arg-type]
    audits: list[tuple[str, str]] = []

    async def fake_audit(message, command, status, reason):
        audits.append((command, status))

    monkeypatch.setattr(worker, "_audit", fake_audit)
    await worker._handle(TelegramInboundMessage(1, 1001, 1001, "private", "/whoami"))
    await worker._handle(TelegramInboundMessage(2, 1001, 1001, "private", "/status"))

    assert api.messages[0] == (1001, "Telegram user ID: 1001")
    assert "غير مصرح" in api.messages[1][1]
    assert audits == [("whoami", "completed"), ("status", "rejected")]


@pytest.mark.asyncio
async def test_allowlisted_status_command_uses_safe_handler(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.telegram_worker import TelegramInboundMessage, TelegramOperationsWorker

    monkeypatch.setattr(settings, "AIOS_TELEGRAM_ALLOWED_USERS", [1001])
    api = _FakeTelegramAPI()
    worker = TelegramOperationsWorker(api)  # type: ignore[arg-type]

    async def fake_status() -> str:
        return "safe-status"

    async def fake_audit(message, command, status, reason):
        return None

    monkeypatch.setattr(worker, "_status", fake_status)
    monkeypatch.setattr(worker, "_audit", fake_audit)
    await worker._handle(TelegramInboundMessage(3, 1001, 1001, "private", "/status"))
    assert api.messages == [(1001, "safe-status")]
