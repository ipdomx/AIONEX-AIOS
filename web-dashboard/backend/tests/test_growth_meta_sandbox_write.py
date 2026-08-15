from __future__ import annotations

import io
import json
from urllib.parse import parse_qs

import pytest

from app.services import growth_meta_sandbox_write as write

ACCOUNT_ID = "2249132522535424"
CAMPAIGN_ID = "9988776655443322"
SECRET = "unit-test-secret-material"


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        write.meta_read.META_TOKEN_FILE_ENV, "/run/operator-secrets/meta-test"
    )
    monkeypatch.setenv(write.meta_read.META_AD_ACCOUNT_ID_ENV, ACCOUNT_ID)
    monkeypatch.setenv(write.meta_read.META_GRAPH_API_VERSION_ENV, "v26.0")
    monkeypatch.setenv(write.META_CONFIRM_ENV, write.META_CONFIRM_VALUE)
    monkeypatch.setattr(write.meta_read, "_read_token", lambda _: SECRET)


def _response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def test_sandbox_write_creates_only_paused_campaign_without_budget_then_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    def opener(request, timeout=20):
        assert timeout == 20
        method = request.get_method()
        url = request.full_url
        calls.append((method, url))
        assert SECRET not in url
        assert request.headers.get("Authorization", "").startswith("Bearer ")

        if method == "GET" and url.startswith(
            f"https://graph.facebook.com/v26.0/act_{ACCOUNT_ID}?fields="
        ):
            return _response(
                {
                    "id": f"act_{ACCOUNT_ID}",
                    "name": "AIONEX-AIOS Sandbox",
                    "currency": "AED",
                    "timezone_name": "Asia/Dubai",
                    "account_status": 1,
                }
            )
        if method == "GET" and url.endswith("/me/permissions"):
            return _response(
                {
                    "data": [
                        {"permission": "ads_management", "status": "granted"},
                        {"permission": "public_profile", "status": "granted"},
                    ]
                }
            )
        if method == "POST" and url.endswith(f"/act_{ACCOUNT_ID}/campaigns"):
            form = parse_qs((request.data or b"").decode("utf-8"))
            assert set(form) == {
                "name",
                "objective",
                "status",
                "special_ad_categories",
            }
            assert form["objective"] == ["OUTCOME_TRAFFIC"]
            assert form["status"] == ["PAUSED"]
            assert form["special_ad_categories"] == ["[]"]
            assert not any("budget" in key.lower() for key in form)
            assert not any(
                "adset" in key.lower() or "ad_set" in key.lower() for key in form
            )
            return _response({"id": CAMPAIGN_ID})
        if method == "GET" and url.startswith(
            f"https://graph.facebook.com/v26.0/{CAMPAIGN_ID}?fields="
        ):
            return _response(
                {
                    "id": CAMPAIGN_ID,
                    "name": "AIONEX GS12 Sandbox Write Validation",
                    "status": "PAUSED",
                    "objective": "OUTCOME_TRAFFIC",
                }
            )
        if method == "DELETE" and url.endswith(f"/{CAMPAIGN_ID}"):
            return _response({"success": True})
        raise AssertionError(f"unexpected request: {method} {url}")

    evidence = write.probe_meta_sandbox_write_validation(opener=opener)

    assert evidence["provider"] == "meta"
    assert evidence["capability"] == "ads.manage"
    assert evidence["validation_mode"] == "sandbox_write"
    assert evidence["campaign_created"] is True
    assert evidence["campaign_status_verified"] == "PAUSED"
    assert evidence["campaign_deleted"] is True
    assert evidence["ad_set_created"] is False
    assert evidence["ad_created"] is False
    assert evidence["budget_configured"] is False
    assert evidence["real_spend_minor"] == 0
    assert evidence["sandbox_mutation_verified"] is True
    assert evidence["live_provider_mutation_allowed"] is False
    assert evidence["mutation_allowed"] is False
    assert evidence["spend_allowed"] is False
    assert evidence["execution_adapter_verified"] is False
    assert evidence["sandbox_execution_adapter_verified"] is True
    assert evidence["raw_secret_persisted"] is False
    assert SECRET not in repr(evidence)
    assert CAMPAIGN_ID not in repr(evidence)
    assert [method for method, _ in calls] == ["GET", "GET", "POST", "GET", "DELETE"]


def test_sandbox_write_requires_explicit_one_run_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.delenv(write.META_CONFIRM_ENV)
    with pytest.raises(
        write.MetaSandboxWriteValidationError,
        match="write-confirmation-required",
    ):
        write.probe_meta_sandbox_write_validation()


def test_sandbox_write_rejects_non_sandbox_account_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    methods: list[str] = []

    def opener(request, timeout=20):
        methods.append(request.get_method())
        return _response(
            {
                "id": f"act_{ACCOUNT_ID}",
                "name": "Production Advertising Account",
                "currency": "AED",
                "timezone_name": "Asia/Dubai",
                "account_status": 1,
            }
        )

    with pytest.raises(
        write.MetaSandboxWriteValidationError,
        match="account-not-explicitly-sandbox",
    ):
        write.probe_meta_sandbox_write_validation(opener=opener)
    assert methods == ["GET"]


def test_sandbox_write_requires_ads_management_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    methods: list[str] = []

    def opener(request, timeout=20):
        method = request.get_method()
        methods.append(method)
        if request.full_url.startswith(
            f"https://graph.facebook.com/v26.0/act_{ACCOUNT_ID}?fields="
        ):
            return _response(
                {
                    "id": f"act_{ACCOUNT_ID}",
                    "name": "AIONEX-AIOS Sandbox",
                    "currency": "AED",
                    "timezone_name": "Asia/Dubai",
                    "account_status": 1,
                }
            )
        if request.full_url.endswith("/me/permissions"):
            return _response(
                {"data": [{"permission": "ads_read", "status": "granted"}]}
            )
        raise AssertionError("mutation was attempted without ads_management")

    with pytest.raises(
        write.MetaSandboxWriteValidationError,
        match="ads-management-permission-required",
    ):
        write.probe_meta_sandbox_write_validation(opener=opener)
    assert methods == ["GET", "GET"]


def test_sandbox_write_prioritizes_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    delete_attempted = False

    def opener(request, timeout=20):
        nonlocal delete_attempted
        method = request.get_method()
        url = request.full_url
        if method == "GET" and url.startswith(
            f"https://graph.facebook.com/v26.0/act_{ACCOUNT_ID}?fields="
        ):
            return _response(
                {
                    "id": f"act_{ACCOUNT_ID}",
                    "name": "AIONEX-AIOS Sandbox",
                    "currency": "AED",
                    "timezone_name": "Asia/Dubai",
                    "account_status": 1,
                }
            )
        if method == "GET" and url.endswith("/me/permissions"):
            return _response(
                {"data": [{"permission": "ads_management", "status": "granted"}]}
            )
        if method == "POST":
            return _response({"id": CAMPAIGN_ID})
        if method == "GET" and CAMPAIGN_ID in url:
            return _response(
                {
                    "id": CAMPAIGN_ID,
                    "status": "ACTIVE",
                    "objective": "OUTCOME_TRAFFIC",
                }
            )
        if method == "DELETE":
            delete_attempted = True
            return _response({"success": False})
        raise AssertionError(f"unexpected request {method} {url}")

    with pytest.raises(
        write.MetaSandboxWriteValidationError,
        match="campaign-cleanup-failed",
    ):
        write.probe_meta_sandbox_write_validation(opener=opener)
    assert delete_attempted is True


def test_safe_evidence_output_contains_no_external_id_or_credential(capsys) -> None:
    write._print_safe_evidence({})
    output = capsys.readouterr().out
    assert "AIOS_META_SANDBOX_WRITE_VALIDATION_OK" in output
    assert "campaign_deleted=true" in output
    assert "real_spend_minor=0" in output
    assert "live_provider_mutation_allowed=false" in output
    assert "spend_allowed=false" in output
    assert "credential" not in output.lower()
    assert CAMPAIGN_ID not in output
