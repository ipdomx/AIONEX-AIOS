"""FCM errors with a known outcome must not leave a delivery "uncertain".

Found by the native app's emulator test (2026-11-23): a reinstalled app left a
dead token behind; FCM answered UnregisteredError, the worker treated it as an
uncertain outcome and the delivery stayed "processing".
"""

from __future__ import annotations

import sys
import types

import pytest

from app.services import communications


def _install_fake_firebase(monkeypatch: pytest.MonkeyPatch, error_name: str | None) -> None:
    error_type = type(error_name or "Unused", (Exception,), {})

    def send(_message, app=None):  # noqa: ARG001 - mirrors firebase_admin.messaging.send
        if error_name is None:
            return "projects/aios/messages/1"
        raise error_type("provider said no")

    messaging = types.SimpleNamespace(
        send=send,
        Message=lambda **kwargs: kwargs,
        Notification=lambda **kwargs: kwargs,
    )
    credentials = types.SimpleNamespace(Certificate=lambda value: value)
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin.get_app = lambda name: object()  # type: ignore[attr-defined]
    firebase_admin.initialize_app = lambda *args, **kwargs: object()  # type: ignore[attr-defined]
    firebase_admin.credentials = credentials  # type: ignore[attr-defined]
    firebase_admin.messaging = messaging  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firebase_admin", firebase_admin)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", credentials)
    monkeypatch.setitem(sys.modules, "firebase_admin.messaging", messaging)
    monkeypatch.setattr(communications, "channel_state", lambda channel: {"ready": True})
    monkeypatch.setattr(communications, "_firebase_app", None)


def _message() -> communications.NotificationMessageData:
    return communications.NotificationMessageData(
        id="n1", title="Title", message="Body", event_key="test.event", severity="info"
    )


@pytest.mark.parametrize("error_name", ["UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"])
def test_dead_or_foreign_token_is_a_final_rejection(monkeypatch, error_name):
    _install_fake_firebase(monkeypatch, error_name)
    with pytest.raises(communications._DefiniteDeliveryRejection) as caught:
        communications._send_push("token", _message())
    assert caught.value.code == f"push-{error_name}"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    "error_name", ["PermissionDeniedError", "UnauthenticatedError", "QuotaExceededError", "UnavailableError"]
)
def test_permission_and_quota_errors_are_retryable_rejections(monkeypatch, error_name):
    _install_fake_firebase(monkeypatch, error_name)
    with pytest.raises(communications._DefiniteDeliveryRejection) as caught:
        communications._send_push("token", _message())
    assert caught.value.retryable is True


def test_unknown_errors_stay_uncertain(monkeypatch):
    _install_fake_firebase(monkeypatch, "SomethingNewError")
    with pytest.raises(communications.CommunicationError) as caught:
        communications._send_push("token", _message())
    assert not isinstance(caught.value, communications._DefiniteDeliveryRejection)


def test_success_returns_the_provider_message_id(monkeypatch):
    _install_fake_firebase(monkeypatch, None)
    assert communications._send_push("token", _message()) == "projects/aios/messages/1"
