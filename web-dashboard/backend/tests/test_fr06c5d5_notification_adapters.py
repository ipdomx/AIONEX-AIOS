"""Provider-boundary proof uses synthetic clients only; no external sends."""

from __future__ import annotations

import smtplib
from typing import Any

import httpx
import pytest

from app.services import communications


def message_data() -> communications.NotificationMessageData:
    return communications.NotificationMessageData(
        id="synthetic-notification",
        title="Synthetic subject",
        message="Synthetic body",
        event_key="synthetic.event",
        severity="info",
    )


class FakeSMTP:
    def __init__(
        self,
        *,
        send_error: BaseException | None = None,
        refused: dict[str, tuple[int, bytes]] | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.send_error = send_error
        self.refused = refused or {}
        self.close_error = close_error
        self.events: list[str] = []

    def __enter__(self) -> FakeSMTP:
        self.events.append("enter")
        return self

    def __exit__(self, *_args: object) -> bool:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error
        return False

    def ehlo(self) -> None:
        self.events.append("ehlo")

    def send_message(self, _message: object) -> dict[str, tuple[int, bytes]]:
        self.events.append("send")
        if self.send_error is not None:
            raise self.send_error
        return self.refused


def configure_smtp(monkeypatch: pytest.MonkeyPatch, client: FakeSMTP) -> None:
    monkeypatch.setattr(communications, "channel_state", lambda _channel: {"ready": True})
    monkeypatch.setattr(communications.settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(communications.settings, "SMTP_PORT", 465)
    monkeypatch.setattr(communications.settings, "SMTP_SSL", True)
    monkeypatch.setattr(communications.settings, "SMTP_TLS", False)
    monkeypatch.setattr(communications.settings, "SMTP_USER", None)
    monkeypatch.setattr(communications.settings, "SMTP_FROM_EMAIL", "sender@example.test")
    monkeypatch.setattr(communications.smtplib, "SMTP_SSL", lambda *_args, **_kwargs: client)


@pytest.mark.parametrize("response_code,retryable", [(450, True), (550, False)])
def test_smtp_all_recipient_refusal_is_classified_only_after_close(
    monkeypatch: pytest.MonkeyPatch, response_code: int, retryable: bool
) -> None:
    client = FakeSMTP(
        send_error=smtplib.SMTPRecipientsRefused(
            {"recipient@example.test": (response_code, b"synthetic rejection")}
        )
    )
    configure_smtp(monkeypatch, client)
    with pytest.raises(communications._DefiniteDeliveryRejection) as caught:
        communications._send_email("recipient@example.test", message_data())
    assert caught.value.retryable is retryable
    assert str(caught.value) == "smtp-all-recipients-refused"
    assert client.events[-2:] == ["send", "close"]


def test_smtp_partial_refusal_does_not_claim_no_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSMTP(refused={"recipient@example.test": (550, b"synthetic")})
    configure_smtp(monkeypatch, client)
    with pytest.raises(communications.NotificationDispatchUncertain):
        communications._send_email("recipient@example.test", message_data())
    assert client.events[-1] == "close"


@pytest.mark.parametrize("refusal_first", [False, True])
def test_smtp_close_error_overrides_any_safe_rejection(
    monkeypatch: pytest.MonkeyPatch, refusal_first: bool
) -> None:
    client = FakeSMTP(
        send_error=(
            smtplib.SMTPRecipientsRefused({"recipient@example.test": (450, b"synthetic")})
            if refusal_first
            else None
        ),
        close_error=communications.ProviderNotConfigured("synthetic-close-error"),
    )
    configure_smtp(monkeypatch, client)
    with pytest.raises(
        communications.NotificationDispatchUncertain,
        match="smtp-client-cleanup-unconfirmed",
    ):
        communications._send_email("recipient@example.test", message_data())
    assert client.events[-1] == "close"


def test_smtp_success_requires_completed_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSMTP()
    configure_smtp(monkeypatch, client)
    assert communications._send_email(
        "recipient@example.test", message_data()
    ) == "smtp:synthetic-notification"
    assert client.events[-2:] == ["send", "close"]


class FakeTelegram:
    def __init__(
        self, response: httpx.Response, *, close_error: BaseException | None = None
    ) -> None:
        self.response = response
        self.close_error = close_error
        self.events: list[str] = []

    async def send_message_response(self, chat_id: int, text: str) -> httpx.Response:
        assert chat_id == 123
        assert text == "Synthetic subject\n\nSynthetic body"
        self.events.append("send")
        return self.response

    async def close(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


def configure_telegram(monkeypatch: pytest.MonkeyPatch, client: FakeTelegram) -> None:
    monkeypatch.setattr(
        communications, "telegram_scope_state", lambda _scope: {"ready": True}
    )
    monkeypatch.setattr(communications, "load_bot_token", lambda _path: "synthetic-token")
    monkeypatch.setattr(communications, "TelegramBotAPI", lambda _token: client)


@pytest.mark.asyncio
async def test_telegram_documented_flood_rejection_is_settled_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeTelegram(
        httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "parameters": {"retry_after": 17}},
        )
    )
    configure_telegram(monkeypatch, client)
    with pytest.raises(communications._DefiniteDeliveryRejection) as caught:
        await communications._send_telegram("123", message_data())
    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 17
    assert client.events == ["send", "close"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (429, {"error": "rate-limited"}),
        (429, {"ok": False, "error_code": "429", "parameters": {"retry_after": 17}}),
        (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": True}}),
        (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}),
        (500, {"ok": False, "error_code": 500}),
        (200, {"ok": True}),
        (200, {"ok": True, "result": {"message_id": True}}),
        (200, {"ok": True, "result": {"message_id": 0}}),
        (200, {"ok": True, "result": {"message_id": 77}}),
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": 124}, "date": 1700000000}}),
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": "123"}, "date": 1700000000}}),
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": 123}}}),
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": 123}, "date": True}}),
        (200, {"ok": True, "result": {"message_id": 77, "chat": {"id": 123}, "date": 0}}),
        (200, {"ok": True, "error_code": 429, "result": {"message_id": 77, "chat": {"id": 123}, "date": 1700000000}}),
    ],
)
async def test_telegram_unproven_response_remains_uncertain(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: dict[str, Any]
) -> None:
    client = FakeTelegram(httpx.Response(status, json=payload))
    configure_telegram(monkeypatch, client)
    with pytest.raises(communications.NotificationDispatchUncertain):
        await communications._send_telegram("123", message_data())
    assert client.events == ["send", "close"]


@pytest.mark.asyncio
async def test_telegram_valid_acknowledgement_returns_no_recipient_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeTelegram(
        httpx.Response(200, json={"ok": True, "result": {"message_id": 77, "chat": {"id": 123}, "date": 1700000000}})
    )
    configure_telegram(monkeypatch, client)
    receipt = await communications._send_telegram("123", message_data())
    assert receipt == "telegram:owner:synthetic-notification:77"
    assert "123" not in receipt
    assert client.events == ["send", "close"]


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_telegram_close_error_never_becomes_no_send_or_safe_retry(
    monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    response = (
        httpx.Response(200, json={"ok": True, "result": {"message_id": 77, "chat": {"id": 123}, "date": 1700000000}})
        if accepted
        else httpx.Response(
            429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 17}}
        )
    )
    client = FakeTelegram(
        response, close_error=communications.ProviderNotConfigured("synthetic-close")
    )
    configure_telegram(monkeypatch, client)
    with pytest.raises(
        communications.NotificationDispatchUncertain,
        match="telegram-client-cleanup-unconfirmed",
    ):
        await communications._send_telegram("123", message_data())
    assert client.events[-1] == "close"


def configure_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(communications, "channel_state", lambda _channel: {"ready": True})
    monkeypatch.setattr(communications.settings, "WHATSAPP_API_BASE", "https://graph.example")
    monkeypatch.setattr(communications.settings, "WHATSAPP_PHONE_NUMBER_ID", "123456")
    monkeypatch.setattr(communications.settings, "WHATSAPP_ACCESS_TOKEN", "synthetic-token")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (500, {"error": "temporary"}),
        (429, {"error": "rate-limited"}),
        (400, {"error": "request rejected"}),
        (200, {"messages": []}),
        (200, {"messages": [{"id": None}]}),
        (200, {"messages": [{"id": ""}]}),
        (200, {"messages": [{"id": "synthetic-id"}], "error": {"code": 1}}),
    ],
)
async def test_whatsapp_unproven_result_remains_uncertain(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: dict[str, Any]
) -> None:
    configure_whatsapp(monkeypatch)
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, json=payload))
    with pytest.raises(communications.NotificationDispatchUncertain):
        await communications._send_whatsapp(
            "971501234567", message_data(), transport=transport
        )


@pytest.mark.asyncio
async def test_whatsapp_network_failure_is_not_classified_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_whatsapp(monkeypatch)

    def lose_response(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic acknowledgement loss", request=request)

    with pytest.raises(httpx.ReadTimeout):
        await communications._send_whatsapp(
            "971501234567", message_data(), transport=httpx.MockTransport(lose_response)
        )


@pytest.mark.asyncio
async def test_whatsapp_close_failure_is_always_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_whatsapp(monkeypatch)

    class Client:
        async def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"messages": [{"id": "synthetic-id"}]})

        async def aclose(self) -> None:
            raise communications.ProviderNotConfigured("synthetic-close")

    monkeypatch.setattr(communications.httpx, "AsyncClient", lambda **_kwargs: Client())
    with pytest.raises(
        communications.NotificationDispatchUncertain,
        match="whatsapp-client-cleanup-unconfirmed",
    ):
        await communications._send_whatsapp("971501234567", message_data())
