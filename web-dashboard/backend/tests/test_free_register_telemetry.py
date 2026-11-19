"""Device telemetry must never block free registration (production, 2026-11-19)."""

from app.api.v1.endpoints.auth import FreeRegisterRequest


def _payload(telemetry: object) -> dict:
    return {
        "username": "probe_user",
        "email": "probe@example.com",
        "password": "a-long-password-123",
        "name": "Probe User",
        "birth_date": "1990-01-01",
        "country_code": "EG",
        "phone_number": "+201000000000",
        "consent_accepted": True,
        "consent_version": "2026-11",
        "telemetry": telemetry,
    }


def test_invalid_telemetry_signals_are_dropped_not_rejected() -> None:
    data = FreeRegisterRequest.model_validate(
        _payload(
            {
                "timezone": "Asia/Riyadh",
                "screen_width": 390.5,
                "platform": "x" * 400,
                "rtt_ms": -1,
                "unknown_signal": "ignored",
            }
        )
    )
    dumped = data.telemetry.model_dump(exclude_none=True)
    assert dumped == {"timezone": "Asia/Riyadh"}


def test_non_object_telemetry_becomes_empty() -> None:
    data = FreeRegisterRequest.model_validate(_payload("not-an-object"))
    assert data.telemetry.model_dump(exclude_none=True) == {}
