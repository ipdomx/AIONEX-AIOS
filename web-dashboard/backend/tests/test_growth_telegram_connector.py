from __future__ import annotations

import io
import json

import pytest

from app.services import growth_telegram_connector as telegram


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        telegram.ADMIN_TOKEN_FILE_ENV, "/run/operator-secrets/telegram-admin-test"
    )
    monkeypatch.setenv(
        telegram.USER_TOKEN_FILE_ENV, "/run/operator-secrets/telegram-user-test"
    )

    tokens = {
        "/run/operator-secrets/telegram-admin-test": "111111:admin-test-secret",
        "/run/operator-secrets/telegram-user-test": "222222:user-test-secret",
    }
    monkeypatch.setattr(telegram, "_read_token", lambda path: tokens[path])


def test_telegram_probe_uses_get_me_only_and_redacts_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    seen: list[str] = []

    def opener(request, timeout=20):
        assert timeout == 20
        assert request.get_method() == "GET"
        assert request.full_url.endswith("/getMe")
        assert "sendMessage" not in request.full_url
        seen.append(request.full_url)
        payload = {
            "ok": True,
            "result": {
                "id": 987654321,
                "is_bot": True,
                "first_name": "Hidden Bot",
                "username": "hidden_bot_name",
            },
        }
        return io.BytesIO(json.dumps(payload).encode())

    evidence = telegram.probe_telegram_bots_read_only(opener=opener)
    assert len(seen) == 2
    assert evidence["provider"] == "telegram"
    assert evidence["capability"] == "account.read"
    assert evidence["scope"] == "owner_bots"
    assert evidence["validation_mode"] == "read_only"
    assert evidence["bot_credentials_count"] == 2
    assert evidence["verified_bot_count"] == 2
    assert evidence["provider_call_allowed"] is True
    assert evidence["mutation_allowed"] is False
    assert evidence["send_allowed"] is False
    assert evidence["spend_allowed"] is False
    rendered = repr(evidence)
    assert "admin-test-secret" not in rendered
    assert "user-test-secret" not in rendered
    assert "987654321" not in rendered
    assert "hidden_bot_name" not in rendered


def test_telegram_rejects_non_allowlisted_secret_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(telegram.ADMIN_TOKEN_FILE_ENV, "/tmp/admin-token")
    monkeypatch.setenv(
        telegram.USER_TOKEN_FILE_ENV, "/run/operator-secrets/telegram-user-test"
    )
    with pytest.raises(
        telegram.TelegramReadOnlyValidationError,
        match="telegram-token-file-not-allowlisted",
    ):
        telegram.probe_telegram_bots_read_only()


def test_telegram_rejects_non_bot_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def opener(request, timeout=20):
        assert timeout == 20
        payload = {"ok": True, "result": {"id": 1, "is_bot": False}}
        return io.BytesIO(json.dumps(payload).encode())

    with pytest.raises(
        telegram.TelegramReadOnlyValidationError,
        match="telegram-api-result-not-bot",
    ):
        telegram.probe_telegram_bots_read_only(opener=opener)


def test_safe_output_contains_no_credentials_or_identity(capsys) -> None:
    evidence = {
        "bot_credentials_count": 2,
        "verified_bot_count": 2,
        "credential_refs": [
            telegram.ADMIN_CREDENTIAL_REF,
            telegram.USER_CREDENTIAL_REF,
        ],
    }
    telegram._print_safe_evidence(evidence)
    output = capsys.readouterr().out
    assert "AIOS_TELEGRAM_READ_ONLY_VALIDATION_OK" in output
    assert telegram.ADMIN_CREDENTIAL_REF not in output
    assert telegram.USER_CREDENTIAL_REF not in output
    assert "admin-test-secret" not in output
    assert "user-test-secret" not in output
    assert "mutation_allowed=false" in output
    assert "send_allowed=false" in output
    assert "spend_allowed=false" in output
