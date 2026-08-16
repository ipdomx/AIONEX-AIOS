from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from app.services import growth_meta_page_discovery as pages


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _response(payload: dict) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def test_page_discovery_returns_only_opaque_refs_and_safe_tasks(monkeypatch) -> None:
    monkeypatch.setattr(
        pages.owned,
        "_safe_config",
        lambda: ("/run/operator-secrets/meta-token", "v26.0"),
    )
    monkeypatch.setattr(pages.owned, "_read_token", lambda _path: "fake-meta-token")
    raw_page_id = "623456789012345"

    def opener(request, timeout=20):
        assert timeout == 20
        url = request.full_url
        if url.endswith("/me/permissions"):
            return _response(
                {
                    "data": [
                        {"permission": "pages_read_engagement", "status": "granted"},
                        {"permission": "ads_management", "status": "granted"},
                    ]
                }
            )
        assert "/me/accounts?" in url
        return _response(
            {
                "data": [
                    {
                        "id": raw_page_id,
                        "name": "  Example   Page  ",
                        "tasks": ["ADVERTISE", "ANALYZE", "UNEXPECTED_TASK"],
                    }
                ]
            }
        )

    result = pages.probe_meta_pages_read_only(opener=opener)
    assert result["page_count"] == 1
    assert result["advertise_ready_page_count"] == 1
    assert result["result_page_truncated"] is False
    assert result["pages"][0]["name"] == "Example Page"
    assert result["pages"][0]["advertise_ready"] is True
    assert result["pages"][0]["tasks"] == ["ADVERTISE", "ANALYZE"]
    assert result["pages"][0]["page_ref"] == pages._page_ref(raw_page_id)
    assert raw_page_id not in json.dumps(result, sort_keys=True)
    assert "fake-meta-token" not in json.dumps(result, sort_keys=True)
    assert result["provider_write_executed"] is False
    assert result["provider_spend_executed"] is False
    assert result["raw_page_ids_returned"] is False
    assert result["raw_secret_returned"] is False


def test_page_ref_resolver_requires_advertise_and_does_not_persist_raw_id(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pages.owned,
        "_safe_config",
        lambda: ("/run/operator-secrets/meta-token", "v26.0"),
    )
    monkeypatch.setattr(pages.owned, "_read_token", lambda _path: "fake-meta-token")
    raw_page_id = "723456789012345"
    calls = 0

    def opener(request, timeout=20):
        nonlocal calls
        calls += 1
        if request.full_url.endswith("/me/permissions"):
            return _response({"data": []})
        return _response(
            {"data": [{"id": raw_page_id, "name": "Ad Page", "tasks": ["ADVERTISE"]}]}
        )

    resolved_id, tasks = pages.resolve_page_ref_to_raw_id(
        pages._page_ref(raw_page_id), opener=opener
    )
    assert resolved_id == raw_page_id
    assert tasks == ["ADVERTISE"]
    assert calls == 3


def test_page_discovery_fails_closed_on_truncated_inventory(monkeypatch) -> None:
    monkeypatch.setattr(
        pages.owned,
        "_safe_config",
        lambda: ("/run/operator-secrets/meta-token", "v26.0"),
    )
    monkeypatch.setattr(pages.owned, "_read_token", lambda _path: "fake-meta-token")
    raw_page_id = "823456789012345"

    def opener(request, timeout=20):
        if request.full_url.endswith("/me/permissions"):
            return _response({"data": []})
        return _response(
            {
                "data": [{"id": raw_page_id, "name": "Page", "tasks": ["ADVERTISE"]}],
                "paging": {"next": "https://graph.facebook.com/next"},
            }
        )

    result = pages.probe_meta_pages_read_only(opener=opener)
    assert result["result_page_truncated"] is True
    with pytest.raises(
        pages.MetaPageDiscoveryError, match="meta-page-inventory-truncated"
    ):
        pages.resolve_page_ref_to_raw_id(pages._page_ref(raw_page_id), opener=opener)


def test_page_discovery_redacts_provider_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        pages.owned,
        "_safe_config",
        lambda: ("/run/operator-secrets/meta-token", "v26.0"),
    )
    monkeypatch.setattr(pages.owned, "_read_token", lambda _path: "fake-meta-token")

    def opener(_request, timeout=20):
        body = io.BytesIO(
            json.dumps({"error": {"code": 190, "message": "secret message"}}).encode()
        )
        raise HTTPError("https://graph.facebook.com", 400, "bad", hdrs=None, fp=body)

    with pytest.raises(
        pages.MetaPageDiscoveryError, match="meta-page-list-api-error-190"
    ) as exc:
        pages.probe_meta_pages_read_only(opener=opener)
    assert "secret message" not in str(exc.value)
