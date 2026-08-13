from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.auth import UserRecord
from app.services import user_telegram_auth
from app.services.telegram_worker import TelegramInboundMessage
from app.services.user_telegram_worker import UserTelegramWorker


def test_link_code_is_high_entropy_and_persisted_as_digest_only() -> None:
    code = user_telegram_auth._new_code()
    assert len(code) == 16
    assert code.isalnum()
    digest = user_telegram_auth._code_digest(code)
    assert digest != code
    assert len(digest) == 64


@pytest.mark.asyncio
async def test_super_owner_is_forced_to_use_protected_owner_bot() -> None:
    actor = UserRecord(
        id="owner-test",
        email="owner@example.com",
        name="Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="owner-org",
        organization_name="Owner",
        organization_plan="enterprise",
        permissions=["*"],
        auth_version=0,
    )
    with pytest.raises(HTTPException) as raised:
        await user_telegram_auth.issue_link_challenge(None, actor)  # type: ignore[arg-type]
    assert raised.value.status_code == 403


class _FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_user_bot_rejects_non_private_chat_before_account_access(
    monkeypatch,
) -> None:
    api = _FakeTelegramAPI()
    worker = UserTelegramWorker(api)  # type: ignore[arg-type]
    audits: list[tuple[str, str | None]] = []

    async def audit(_message, _command, status, reason, **_kwargs):
        audits.append((status, reason))

    monkeypatch.setattr(worker, "_audit", audit)
    await worker._handle(
        TelegramInboundMessage(
            update_id=999001,
            user_id=710000003,
            chat_id=-100123456789,
            chat_type="supergroup",
            text="/me",
        )
    )
    assert api.messages
    assert "private chat" in api.messages[0][1]
    assert audits == [("rejected", "non-private-chat")]


def test_user_bot_capabilities_follow_current_role_and_plan_context() -> None:
    worker = UserTelegramWorker(_FakeTelegramAPI())  # type: ignore[arg-type]
    free_actor = SimpleNamespace(
        role="Free User",
        permissions=["projects:read", "billing:read"],
    )
    higher_actor = SimpleNamespace(
        role="Owner",
        permissions=["projects:read", "billing:read", "notifications:read"],
    )
    free_context = {
        "plan": SimpleNamespace(name="Free", code="free"),
        "entitlements": ["projects.core"],
    }
    higher_context = {
        "plan": SimpleNamespace(name="Business", code="business"),
        "entitlements": ["projects.core", "3d.generation"],
    }

    free_help = worker._help(free_actor, free_context)
    higher_help = worker._help(higher_actor, higher_context)
    assert "/projects" in free_help
    assert "/notifications" not in free_help
    assert "/notifications" in higher_help

    free_capabilities = worker._capabilities(free_actor, free_context)
    higher_capabilities = worker._capabilities(higher_actor, higher_context)
    assert "Plan: Free" in free_capabilities
    assert "projects.core" in free_capabilities
    assert "3d.generation" not in free_capabilities
    assert "Plan: Business" in higher_capabilities
    assert "3d.generation" in higher_capabilities

    with pytest.raises(PermissionError):
        worker._require_permission(free_actor.permissions, "notifications:read")
