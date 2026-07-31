from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from phonenumbers import PhoneNumberType

from app.api.v1.endpoints.auth import FreeRegisterRequest
from app.services import firebase_phone

REPO_ROOT = Path(__file__).resolve().parents[3]
PHONE = "+971501234567"


def _service_account(project_id: str = "aionex-test") -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": "test-key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        "client_email": f"firebase-adminsdk@{project_id}.iam.gserviceaccount.com",
    }


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    credential_path = tmp_path / "firebase-admin.json"
    credential_path.write_text(json.dumps(_service_account()), encoding="utf-8")
    values = {
        "FIREBASE_PROJECT_ID": "aionex-test",
        "FIREBASE_WEB_API_KEY": "browser-api-key",
        "FIREBASE_AUTH_DOMAIN": "aionex-test.firebaseapp.com",
        "FIREBASE_APP_ID": "1:123:web:test",
        "FIREBASE_STORAGE_BUCKET": "aionex-test.firebasestorage.app",
        "FIREBASE_MESSAGING_SENDER_ID": "123",
        "FIREBASE_MEASUREMENT_ID": "G-TEST",
        "FIREBASE_ADMIN_CREDENTIALS_JSON": str(credential_path),
        "FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS": "900",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return credential_path


def test_public_configuration_contains_only_browser_safe_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credential_path = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(firebase_phone, "_get_firebase_app", lambda: object())

    result = firebase_phone.firebase_public_configuration()

    assert result["enabled"] is True
    assert result["admin_verification_ready"] is True
    assert result["web_config"]["projectId"] == "aionex-test"
    serialized = json.dumps(result)
    assert str(credential_path) not in serialized
    assert "private_key" not in serialized
    assert "client_email" not in serialized


def test_mismatched_service_account_disables_public_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credential_path = _configure(monkeypatch, tmp_path)
    credential_path.write_text(
        json.dumps(_service_account("different-project")),
        encoding="utf-8",
    )

    result = firebase_phone.firebase_public_configuration()

    assert result["enabled"] is False
    assert result["admin_verification_ready"] is False
    assert result["web_config"]["projectId"] == "aionex-test"


@pytest.mark.asyncio
async def test_recent_firebase_phone_token_is_bound_to_exact_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    monkeypatch.setattr(firebase_phone, "_canonical_mobile_number", lambda value: value)
    monkeypatch.setattr(
        firebase_phone,
        "_verify_id_token_sync",
        lambda token: {
            "uid": "firebase-user-1",
            "phone_number": PHONE,
            "auth_time": now,
            "firebase": {"sign_in_provider": "phone"},
        },
    )

    result = await firebase_phone.verify_firebase_phone_id_token("x" * 200, PHONE)

    assert result == {
        "verified": True,
        "provider": "firebase",
        "line_type": "mobile",
        "line_type_source": "libphonenumber",
        "phone_number": PHONE,
        "verified_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
        "firebase_uid": "firebase-user-1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "token_phone"),
    [("password", PHONE), ("phone", "+971509999999")],
)
async def test_firebase_token_rejects_wrong_provider_or_number(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    token_phone: str,
) -> None:
    monkeypatch.setattr(firebase_phone, "_canonical_mobile_number", lambda value: value)
    monkeypatch.setattr(
        firebase_phone,
        "_verify_id_token_sync",
        lambda token: {
            "uid": "firebase-user-1",
            "phone_number": token_phone,
            "auth_time": int(datetime.now(UTC).timestamp()),
            "firebase": {"sign_in_provider": provider},
        },
    )

    with pytest.raises(HTTPException) as exc:
        await firebase_phone.verify_firebase_phone_id_token("x" * 200, PHONE)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_firebase_token_must_be_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS", "900")
    monkeypatch.setattr(firebase_phone, "_canonical_mobile_number", lambda value: value)
    monkeypatch.setattr(
        firebase_phone,
        "_verify_id_token_sync",
        lambda token: {
            "uid": "firebase-user-1",
            "phone_number": PHONE,
            "auth_time": int(datetime.now(UTC).timestamp()) - 901,
            "firebase": {"sign_in_provider": "phone"},
        },
    )

    with pytest.raises(HTTPException) as exc:
        await firebase_phone.verify_firebase_phone_id_token("x" * 200, PHONE)
    assert exc.value.status_code == 422
    assert "completed again" in str(exc.value.detail)


def test_numbering_plan_accepts_mobile_and_rejects_known_non_mobile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = object()
    monkeypatch.setattr(
        firebase_phone.phonenumbers, "parse", lambda value, region: parsed
    )
    monkeypatch.setattr(
        firebase_phone.phonenumbers, "is_valid_number", lambda value: True
    )
    monkeypatch.setattr(
        firebase_phone.phonenumbers,
        "format_number",
        lambda value, format_type: PHONE,
    )
    monkeypatch.setattr(
        firebase_phone.phonenumbers,
        "number_type",
        lambda value: PhoneNumberType.MOBILE,
    )
    assert firebase_phone._canonical_mobile_number(PHONE) == PHONE

    for line_type in (
        PhoneNumberType.VOIP,
        PhoneNumberType.FIXED_LINE,
        PhoneNumberType.FIXED_LINE_OR_MOBILE,
        PhoneNumberType.TOLL_FREE,
        PhoneNumberType.UNKNOWN,
    ):
        monkeypatch.setattr(
            firebase_phone.phonenumbers,
            "number_type",
            lambda value, selected=line_type: selected,
        )
        with pytest.raises(HTTPException) as exc:
            firebase_phone._canonical_mobile_number(PHONE)
        assert exc.value.status_code == 422


def test_registration_contract_uses_optional_firebase_id_token() -> None:
    request = FreeRegisterRequest(
        username="firebase_user",
        email="firebase@example.com",
        password="StrongPassword123!",
        name="Firebase User",
        birth_date=date(1990, 1, 1),
        country_code="AE",
        phone_number=PHONE,
        consent_accepted=True,
        consent_version="2026-07-31",
        telemetry={},
    )
    assert request.firebase_id_token is None


def test_frontend_uses_firebase_sms_recaptcha_and_in_memory_tokens() -> None:
    auth_gate = (
        REPO_ROOT / "web-dashboard/frontend/src/components/auth/AuthGate.tsx"
    ).read_text(encoding="utf-8")
    firebase_client = (
        REPO_ROOT / "web-dashboard/frontend/src/lib/firebase-phone-auth.ts"
    ).read_text(encoding="utf-8")
    auth_service = (
        REPO_ROOT / "web-dashboard/frontend/src/lib/auth-service.ts"
    ).read_text(encoding="utf-8")

    assert "startFirebasePhoneVerification" in auth_gate
    assert "firebase_id_token" in auth_gate
    assert "Phone verification assertion" not in auth_gate
    assert "RecaptchaVerifier" in firebase_client
    assert "signInWithPhoneNumber" in firebase_client
    assert "inMemoryPersistence" in firebase_client
    assert "firebase_id_token?: string" in auth_service


def test_production_mounts_admin_credential_and_drops_privileges() -> None:
    web_compose = (REPO_ROOT / "web-dashboard/docker-compose.production.yml").read_text(
        encoding="utf-8"
    )
    deploy_compose = (
        REPO_ROOT / "deploy/production/docker-compose.production.yml"
    ).read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "web-dashboard/backend/Dockerfile").read_text(
        encoding="utf-8"
    )
    entrypoint = (
        REPO_ROOT / "web-dashboard/backend/scripts/docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    secret_ignore = (REPO_ROOT / "web-dashboard/secrets/.gitignore").read_text(
        encoding="utf-8"
    )

    for compose in (web_compose, deploy_compose):
        assert "/run/secrets/aionex/firebase-admin.json" in compose
        assert "/run/secrets/aionex:ro" in compose
    assert "gosu" in dockerfile
    assert 'ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]' in dockerfile
    assert "install -m 0400 -o aionex -g aionex" in entrypoint
    assert 'exec gosu aionex "$@"' in entrypoint
    assert "!.gitignore" in secret_ignore

    subprocess.run(
        [
            "sh",
            "-n",
            str(REPO_ROOT / "web-dashboard/backend/scripts/docker-entrypoint.sh"),
        ],
        check=True,
    )
