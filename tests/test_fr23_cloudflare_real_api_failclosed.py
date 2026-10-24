"""Cloudflare integration must not invent connections or DNS changes.

All responses are synthetic in-memory fakes. The tests never connect to
Cloudflare, change production DNS, inspect an operator's token, or use workers.
"""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError

import pytest

from aios.infrastructure.cloudflare import (
    CloudflareProvider, CloudflareRequestError, _RejectRedirects
)
from aios.infrastructure.models import (
    ConnectionProfile, ConnectionState, Credential,
)

ZONE = "a" * 32
RECORD = "b" * 32
SECRET = "synthetic-test-only-never-a-live-cloudflare-token"


def invoke(coroutine):
    return asyncio.run(coroutine)


def fixture(monkeypatch):
    calls = []
    responses = []

    def fake_transport(request):
        calls.append((
            request.get_method(),
            request.full_url,
            request.data,
            request.get_header("Authorization"),
        ))
        if responses:
            next_response = responses.pop(0)
            if isinstance(next_response, BaseException):
                raise next_response
            return json.dumps(next_response).encode()
        if request.full_url.endswith("/user/tokens/verify"):
            result = {"status": "active"}
        elif request.full_url.endswith("/settings/security_header"):
            result = {"id": "security_header",
                      "value": {"strict_transport_security": {"enabled": False}}}
        else:
            result = {"id": RECORD, "name": "example.com"}
        return json.dumps({"success": True, "result": result}).encode()

    monkeypatch.setattr(CloudflareProvider, "_transport", staticmethod(fake_transport))
    provider = CloudflareProvider()
    profile = ConnectionProfile(name="cf", integration="cloudflare")
    return provider, profile, calls, responses


def ready(monkeypatch):
    provider, profile, calls, responses = fixture(monkeypatch)
    invoke(provider.connect(profile, {"credential": Credential(token=SECRET)}))
    assert provider.state == ConnectionState.CONNECTED
    return provider, calls, responses


def test_missing_real_token_rejected_before_any_transport(monkeypatch):
    p, profile, calls, _ = fixture(monkeypatch)
    with pytest.raises(PermissionError, match="token is required"):
        invoke(p.connect(profile, {}))
    assert calls == []
    assert p.state == ConnectionState.FAILED


def test_wrong_credentials_and_token_injection_denied(monkeypatch):
    p, profile, calls, _ = fixture(monkeypatch)
    for credential in (None, "raw-text-token", Credential(token="\nInjected: token")):
        with pytest.raises(PermissionError):
            invoke(p.connect(profile, {"credential": credential}))
    assert calls == []


def test_endpoint_override_ssrf_denied_before_transport(monkeypatch):
    p, _, calls, _ = fixture(monkeypatch)
    for endpoint in (
        "http://127.0.0.1:8080", "http://169.254.169.254/latest",
        "https://api.cloudflare.com.attacker.test/client/v4",
        "https://api.cloudflare.com/client/v4/../internal",
    ):
        with pytest.raises(ValueError, match="cannot be overridden"):
            invoke(p.connect(
                ConnectionProfile(name="cf", integration="cloudflare", endpoint=endpoint),
                {"credential": Credential(token=SECRET)},
            ))
    assert not calls


def test_connect_performs_live_style_authenticated_api_token_verification(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    assert len(calls) == 1
    method, url, data, authorization = calls[0]
    assert method == "GET"
    assert url == "https://api.cloudflare.com/client/v4/user/tokens/verify"
    assert data is None
    assert authorization == "Bearer " + SECRET
    assert p._token == SECRET
    assert "token" not in repr(p.profile)


def test_inactive_token_denied_instead_of_reporting_connected(monkeypatch):
    p, profile, calls, responses = fixture(monkeypatch)
    responses.append({"success": True, "result": {"status": "expired"}})
    with pytest.raises(PermissionError, match="not been verified active"):
        invoke(p.connect(profile, {"credential": Credential(token=SECRET)}))
    assert p.state == ConnectionState.FAILED
    assert p._token is None
    assert len(calls) == 1


def test_cloudflare_failure_envelope_refuses_fake_success(monkeypatch):
    p, profile, _, responses = fixture(monkeypatch)
    responses.append({"success": False, "result": {"id": "fake"}})
    with pytest.raises(CloudflareRequestError, match="did not confirm success"):
        invoke(p.connect(profile, {"credential": Credential(token=SECRET)}))
    assert p.state == ConnectionState.FAILED


def test_missing_result_or_malformed_response_refuses_success(monkeypatch):
    p, profile, _, responses = fixture(monkeypatch)
    responses.append({"success": True})
    with pytest.raises(CloudflareRequestError, match="result is missing"):
        invoke(p.connect(profile, {"credential": Credential(token=SECRET)}))
    assert p.state == ConnectionState.FAILED


def test_api_health_reverifies_real_token_and_disconnects(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    h = invoke(p.health_check())
    assert h.state == ConnectionState.CONNECTED
    assert h.latency_ms is not None
    assert h.message == "Cloudflare API token verified active"
    assert len(calls) == 2
    invoke(p.disconnect())
    assert p._token is None
    h2 = invoke(p.health_check())
    assert h2.state == ConnectionState.DISCONNECTED
    assert len(calls) == 2


def test_health_does_not_invent_uptime_when_api_unavailable(monkeypatch):
    p, calls, responses = ready(monkeypatch)
    responses.append(URLError("synthetic unavailable"))
    status = invoke(p.health_check())
    assert status.state == ConnectionState.FAILED
    assert p.state == ConnectionState.FAILED
    assert len(calls) == 2
    assert SECRET not in status.message


def test_read_only_accounts_zones_dns_and_security_header_are_actual_api_routes(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    rows = [
        ("accounts", {"page": 1, "per_page": 50},
         "/accounts?page=1&per_page=50"),
        ("zones", {"name": "example.com"}, "/zones?name=example.com"),
        ("dns_records", {"zone_id": ZONE, "type": "A"},
         f"/zones/{ZONE}/dns_records?type=A"),
        ("zone_security_headers", {"zone_id": ZONE},
         f"/zones/{ZONE}/settings/security_header"),
    ]
    for capability, payload, suffix in rows:
        result = invoke(p.execute(capability, payload))
        assert result["provider"] == "cloudflare"
        assert result["operation"] == capability
        assert result["result"] is not None
        assert calls[-1][0] == "GET"
        assert calls[-1][1].endswith(suffix)
    assert len(calls) == 5


def test_removed_fake_only_capabilities_not_advertised_or_executable(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for capability in (
        "firewall_rules", "workers", "r2_buckets", "tunnels",
        "load_balancers", "analytics", "purge_cache",
    ):
        assert capability not in {v.name for v in p.descriptor.capabilities}
        with pytest.raises(KeyError, match="unsupported"):
            invoke(p.execute(capability, {"approved": True}))
    assert len(calls) == 1



def test_dns_mutations_are_not_exposed_even_with_forged_approval(monkeypatch):
    provider, calls, _ = ready(monkeypatch)
    for capability in ("create_dns_record", "update_dns_record", "delete_dns_record"):
        assert capability not in {item.name for item in provider.descriptor.capabilities}
        for approved in (None, True, "true"):
            with pytest.raises(KeyError, match="unsupported capability"):
                invoke(provider.execute(capability, {
                    "zone_id": ZONE, "record_id": RECORD,
                    "record": {"type": "A", "name": "x.example.com",
                               "content": "192.0.2.5"},
                    "approved": approved,
                }))
    assert len(calls) == 1


def test_dns_zone_id_path_traversal_rejected_before_any_request(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for value in ("../other", "a" * 31, "a" * 32 + "/etc",
                  "https://bad.test/", 42):
        for capability in ("dns_records", "zone_security_headers"):
            with pytest.raises(ValueError, match="zone_id"):
                invoke(p.execute(capability, {"zone_id": value}))
    assert len(calls) == 1


def test_dns_read_query_params_are_bounded_and_validated(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for query in (
        {"page": 0},
        {"page": True},
        {"per_page": 101},
        {"per_page": 2.5},
        {"type": ["A"]},
        {"type": "DELETE"},
        {"name": "evil.com/x"},
        {"name": "a" * 254},
    ):
        with pytest.raises(ValueError):
            invoke(p.execute("dns_records", {"zone_id": ZONE, **query}))
    assert len(calls) == 1

def test_http_error_never_reflects_token_or_api_error_body(monkeypatch):
    p, calls, responses = ready(monkeypatch)
    responses.append(HTTPError(
        "https://api.cloudflare.com/client/v4/zones",
        403, "synthetic-reflect-" + SECRET, None, None,
    ))
    with pytest.raises(CloudflareRequestError) as caught:
        invoke(p.execute("zones", {}))
    assert "403" in str(caught.value)
    assert SECRET not in str(caught.value)
    assert "synthetic-reflect" not in str(caught.value)
    assert len(calls) == 2


def test_redirect_never_sends_token_elsewhere():
    assert _RejectRedirects().redirect_request(
        object(), None, 302, "Redirect", {}, "https://evil.invalid"
    ) is None


def test_internal_api_layer_cannot_send_mutations(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(PermissionError, match="read-only"):
            p._api(SECRET, method, "/zones/" + ZONE + "/dns_records")
    with pytest.raises(PermissionError, match="read-only"):
        p._api(SECRET, "GET", "/zones", body={"danger": "write"})
    assert len(calls) == 1


def test_missing_endpoint_never_says_connected(monkeypatch):
    p, profile, _, responses = fixture(monkeypatch)
    responses.append(URLError("synthetic DNS error"))
    with pytest.raises(CloudflareRequestError):
        invoke(p.connect(profile, {"credential": Credential(token=SECRET)}))
    assert p.state == ConnectionState.FAILED
    assert p._endpoint is None
    assert p._token is None
