from __future__ import annotations

import io
import json

import pytest

from app.services import growth_meta_owned_connector as meta


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        meta.META_TOKEN_FILE_ENV, "/run/operator-secrets/meta-owned-test"
    )
    monkeypatch.setenv(meta.META_GRAPH_API_VERSION_ENV, "v26.0")
    monkeypatch.setattr(meta, "_read_token", lambda _: "unit-test-secret-material")


def test_owned_assets_probe_is_read_only_redacted_and_identity_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    def opener(request, timeout=20):
        assert timeout == 20
        assert request.full_url.startswith(
            "https://graph.facebook.com/v26.0/me/adaccounts?"
        )
        assert "fields=id%2Caccount_status" in request.full_url
        assert "limit=100" in request.full_url
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        payload = {
            "data": [
                {"id": "act_111", "account_status": 1},
                {"id": "act_222", "account_status": 2},
            ],
            "paging": {"next": "https://example.invalid/next-with-sensitive-data"},
        }
        return io.BytesIO(json.dumps(payload).encode())

    evidence = meta.probe_meta_owned_assets_read_only(opener=opener)
    assert evidence["provider"] == "meta"
    assert evidence["capability"] == "ads_read"
    assert evidence["scope"] == "owned_assets"
    assert evidence["validation_mode"] == "read_only"
    assert evidence["ad_accounts_count"] == 2
    assert evidence["active_ad_accounts_count"] == 1
    assert evidence["result_page_truncated"] is True
    assert evidence["provider_call_allowed"] is True
    assert evidence["mutation_allowed"] is False
    assert evidence["spend_allowed"] is False
    serialized = repr(evidence)
    assert "unit-test-secret-material" not in serialized
    assert "act_111" not in serialized
    assert "act_222" not in serialized
    assert "example.invalid" not in serialized


def test_owned_assets_rejects_non_allowlisted_secret_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(meta.META_TOKEN_FILE_ENV, "/tmp/not-allowed")
    with pytest.raises(
        meta.MetaOwnedReadOnlyValidationError,
        match="token-file-not-allowlisted",
    ):
        meta.probe_meta_owned_assets_read_only()


def test_owned_assets_rejects_invalid_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(meta.META_TOKEN_FILE_ENV, "/run/operator-secrets/meta-test")
    monkeypatch.setenv(meta.META_GRAPH_API_VERSION_ENV, "latest")
    with pytest.raises(
        meta.MetaOwnedReadOnlyValidationError,
        match="graph-api-version-invalid",
    ):
        meta.probe_meta_owned_assets_read_only()


def test_safe_output_contains_counts_not_credentials_or_ids(capsys) -> None:
    evidence = {
        "ad_accounts_count": 2,
        "active_ad_accounts_count": 1,
        "result_page_truncated": False,
        "credential_ref": meta.META_CREDENTIAL_REF,
        "ids": ["act_111", "act_222"],
    }
    meta._print_safe_evidence(evidence)
    output = capsys.readouterr().out
    assert "AIOS_META_OWNED_READ_ONLY_VALIDATION_OK" in output
    assert "ad_accounts_count=2" in output
    assert "credential_ref" not in output
    assert "act_111" not in output
    assert "act_222" not in output
    assert "mutation_allowed=false" in output
    assert "spend_allowed=false" in output
