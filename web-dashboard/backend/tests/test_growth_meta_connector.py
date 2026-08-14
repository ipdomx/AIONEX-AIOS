from __future__ import annotations

import io
import json

import pytest

from app.services import growth_meta_connector as meta


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(meta.META_TOKEN_FILE_ENV, "/run/operator-secrets/meta-test")
    monkeypatch.setenv(meta.META_AD_ACCOUNT_ID_ENV, "2249132522535424")
    monkeypatch.setenv(meta.META_GRAPH_API_VERSION_ENV, "v26.0")
    monkeypatch.setattr(meta, "_read_token", lambda _: "unit-test-secret-material")


def test_meta_sandbox_probe_is_read_only_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    def opener(request, timeout=20):
        assert timeout == 20
        assert request.full_url.startswith(
            "https://graph.facebook.com/v26.0/act_2249132522535424"
        )
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        payload = {
            "id": "act_2249132522535424",
            "name": "AIONEX-AIOS Sandbox",
            "currency": "AED",
            "timezone_name": "Asia/Dubai",
            "account_status": 1,
        }
        return io.BytesIO(json.dumps(payload).encode())

    evidence = meta.probe_meta_sandbox_read_only(opener=opener)
    assert evidence["provider"] == "meta"
    assert evidence["capability"] == "ads_read"
    assert evidence["validation_mode"] == "sandbox"
    assert evidence["provider_call_allowed"] is True
    assert evidence["mutation_allowed"] is False
    assert evidence["spend_allowed"] is False
    assert "unit-test-secret-material" not in repr(evidence)


def test_meta_sandbox_rejects_non_allowlisted_secret_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(meta.META_TOKEN_FILE_ENV, "/tmp/not-allowed")
    monkeypatch.setenv(meta.META_AD_ACCOUNT_ID_ENV, "2249132522535424")
    with pytest.raises(
        meta.MetaSandboxValidationError, match="token-file-not-allowlisted"
    ):
        meta.probe_meta_sandbox_read_only()


def test_meta_sandbox_rejects_invalid_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(meta.META_TOKEN_FILE_ENV, "/run/operator-secrets/meta-test")
    monkeypatch.setenv(meta.META_AD_ACCOUNT_ID_ENV, "not-an-account")
    with pytest.raises(meta.MetaSandboxValidationError, match="account-id-invalid"):
        meta.probe_meta_sandbox_read_only()


def test_safe_evidence_output_never_contains_credential_ref(capsys) -> None:
    evidence = {
        "account_name": "AIONEX-AIOS Sandbox",
        "currency": "AED",
        "timezone": "Asia/Dubai",
        "account_status": 1,
        "credential_ref": meta.META_CREDENTIAL_REF,
    }
    meta._print_safe_evidence(evidence)
    output = capsys.readouterr().out
    assert "AIOS_META_SANDBOX_VALIDATION_OK" in output
    assert "credential_ref" not in output
    assert "mutation_allowed=false" in output
    assert "spend_allowed=false" in output
