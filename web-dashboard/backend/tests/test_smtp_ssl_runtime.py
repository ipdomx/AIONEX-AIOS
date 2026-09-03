from types import SimpleNamespace

from app.api.owner import control_plane
from app.services import communications


class _SMTPSSL:
    calls: list[tuple[str, int, int, bool]] = []
    logins: list[tuple[str, object]] = []
    sent = 0
    started_tls = False

    def __init__(self, host: str, port: int, *, timeout: int, context: object) -> None:
        type(self).calls.append((host, port, timeout, context is not None))

    def __enter__(self) -> "_SMTPSSL":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def ehlo(self) -> tuple[int, bytes]:
        return 250, b"ok"

    def starttls(self, **_kwargs: object) -> None:
        type(self).started_tls = True

    def login(self, user: str, password: object) -> tuple[int, bytes]:
        type(self).logins.append((user, password))
        return 235, b"ok"

    def send_message(self, _message: object) -> dict[str, tuple[int, bytes]]:
        type(self).sent += 1
        return {}


def _plain_smtp_forbidden(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("plain SMTP must not be used when SMTP_SSL is enabled")


def _configure_ssl(monkeypatch) -> None:
    _SMTPSSL.calls.clear()
    _SMTPSSL.logins.clear()
    _SMTPSSL.sent = 0
    _SMTPSSL.started_tls = False
    for module in (communications, control_plane):
        monkeypatch.setattr(module.settings, "SMTP_HOST", "smtp.example.test")
        monkeypatch.setattr(module.settings, "SMTP_PORT", 465)
        monkeypatch.setattr(module.settings, "SMTP_USER", "smtp-user")
        monkeypatch.setattr(module.settings, "SMTP_PASSWORD", "smtp-password")
        monkeypatch.setattr(module.settings, "SMTP_SSL", True)
        monkeypatch.setattr(module.settings, "SMTP_TLS", False)
        monkeypatch.setattr(module.smtplib, "SMTP_SSL", _SMTPSSL)
        monkeypatch.setattr(module.smtplib, "SMTP", _plain_smtp_forbidden)


def test_communication_email_uses_implicit_tls_when_configured(monkeypatch) -> None:
    _configure_ssl(monkeypatch)
    monkeypatch.setattr(
        communications,
        "channel_state",
        lambda _channel: {"ready": True},
    )
    notification = SimpleNamespace(
        id="notification-ssl",
        title="TLS contract",
        message="No network email is sent by this test.",
    )

    result = communications._send_email("user@example.test", notification)  # type: ignore[arg-type]

    assert result == "smtp:notification-ssl"
    assert _SMTPSSL.calls == [("smtp.example.test", 465, 15, True)]
    assert _SMTPSSL.logins == [("smtp-user", "smtp-password")]
    assert _SMTPSSL.sent == 1
    assert _SMTPSSL.started_tls is False


def test_owner_test_email_uses_implicit_tls_when_configured(monkeypatch) -> None:
    _configure_ssl(monkeypatch)

    result = control_plane._send_owner_test_email("owner@example.test")

    assert result == {
        "recipient": "owner@example.test",
        "provider": "smtp.example.test",
    }
    assert _SMTPSSL.calls == [("smtp.example.test", 465, 10, True)]
    assert _SMTPSSL.logins == [("smtp-user", "smtp-password")]
    assert _SMTPSSL.sent == 1
    assert _SMTPSSL.started_tls is False
