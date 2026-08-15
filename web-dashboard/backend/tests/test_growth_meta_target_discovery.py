from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from app.services import growth_meta_target_discovery as discovery

ACCOUNT_ACTIVE = "123456789012345"
ACCOUNT_INACTIVE = "987654321098765"
SECRET = "unit-test-owned-target-discovery-secret"


def _response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        discovery.owned.META_TOKEN_FILE_ENV,
        "/run/operator-secrets/meta-owned-target-test",
    )
    monkeypatch.setenv(discovery.owned.META_GRAPH_API_VERSION_ENV, "v26.0")
    monkeypatch.setattr(discovery.owned, "_read_token", lambda _: SECRET)


def test_target_discovery_returns_only_opaque_refs_and_safe_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls: list[str] = []

    def opener(request, timeout=20):
        assert timeout == 20
        calls.append(request.full_url)
        assert SECRET not in request.full_url
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        if "/me/adaccounts?" in request.full_url:
            return _response(
                {
                    "data": [
                        {
                            "id": f"act_{ACCOUNT_INACTIVE}",
                            "name": "Inactive Account",
                            "account_status": 2,
                            "currency": "usd",
                            "timezone_name": "America/Los_Angeles",
                        },
                        {
                            "id": f"act_{ACCOUNT_ACTIVE}",
                            "name": "Active Account",
                            "account_status": 1,
                            "currency": "eur",
                            "timezone_name": "Asia/Nicosia",
                        },
                    ],
                    "paging": {},
                }
            )
        if request.full_url.endswith("/me/permissions"):
            return _response(
                {
                    "data": [
                        {"permission": "ads_read", "status": "granted"},
                        {"permission": "ads_management", "status": "declined"},
                    ]
                }
            )
        raise AssertionError(f"unexpected request: {request.full_url}")

    result = discovery.probe_meta_owned_targets_read_only(opener=opener)
    serialized = json.dumps(result, sort_keys=True)

    assert [item["name"] for item in result["accounts"]] == [
        "Active Account",
        "Inactive Account",
    ]
    assert result["accounts"][0]["active"] is True
    assert result["accounts"][0]["currency"] == "EUR"
    assert result["accounts"][0]["scope_ref"].startswith("accountref://meta/sha256/")
    assert ACCOUNT_ACTIVE not in serialized
    assert ACCOUNT_INACTIVE not in serialized
    assert SECRET not in serialized
    assert result["permissions"] == {
        "ads_read": True,
        "ads_management": False,
        "business_management": False,
    }
    assert result["owned_token_write_ready"] is False
    assert result["provider_write_executed"] is False
    assert result["provider_spend_executed"] is False
    assert result["raw_account_ids_returned"] is False
    assert result["raw_secret_returned"] is False
    assert len(calls) == 2


def test_target_discovery_marks_truncated_results_without_returning_paging_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    def opener(request, timeout=20):
        if "/me/adaccounts?" in request.full_url:
            return _response(
                {
                    "data": [
                        {
                            "id": f"act_{ACCOUNT_ACTIVE}",
                            "name": "Target",
                            "account_status": 1,
                            "currency": "AED",
                            "timezone_name": "Asia/Dubai",
                        }
                    ],
                    "paging": {
                        "next": "https://graph.facebook.com/v26.0/next?access_token=must-not-return"
                    },
                }
            )
        if request.full_url.endswith("/me/permissions"):
            return _response({"data": []})
        raise AssertionError("unexpected request")

    result = discovery.probe_meta_owned_targets_read_only(opener=opener)
    serialized = json.dumps(result)
    assert result["result_page_truncated"] is True
    assert "must-not-return" not in serialized
    assert "paging" not in result


def test_target_discovery_redacts_meta_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    def opener(request, timeout=20):
        body = io.BytesIO(
            json.dumps(
                {
                    "error": {
                        "message": f"secret={SECRET}",
                        "code": 190,
                    }
                }
            ).encode("utf-8")
        )
        raise HTTPError(request.full_url, 400, "bad request", {}, body)

    with pytest.raises(
        discovery.MetaTargetDiscoveryError,
        match="meta-target-account-list-api-error-190",
    ) as exc_info:
        discovery.probe_meta_owned_targets_read_only(opener=opener)
    assert SECRET not in str(exc_info.value)
