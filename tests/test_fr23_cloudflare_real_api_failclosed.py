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


def test_dns_mutations_all_require_explicit_owner_approval(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for capability, data in [
        ("create_dns_record", {"zone_id": ZONE, "record": {
            "type": "A", "name": "test.example.com", "content": "192.0.2.5"
        }}),
        ("update_dns_record", {"zone_id": ZONE, "record_id": RECORD,
                               "record": {"ttl": 120}}),
        ("delete_dns_record", {"zone_id": ZONE, "record_id": RECORD}),
    ]:
        with pytest.raises(PermissionError, match="Owner approval"):
            invoke(p.execute(capability, data))
        with pytest.raises(PermissionError, match="Owner approval"):
            invoke(p.execute(capability, {**data, "approved": "true"}))
    assert len(calls) == 1


def test_dns_create_patch_and_delete_use_real_methods_when_approved(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    create = invoke(p.execute("create_dns_record", {
        "zone_id": ZONE, "approved": True,
        "record": {"type": "A", "name": "EDGE.EXAMPLE.COM",
                   "content": "192.0.2.5", "ttl": 120, "proxied": True},
    }))
    assert create["operation"] == "create_dns_record"
    assert calls[-1][0] == "POST"
    assert calls[-1][1].endswith(f"/zones/{ZONE}/dns_records")
    assert json.loads(calls[-1][2]) == {
        "type": "A", "name": "edge.example.com", "content": "192.0.2.5",
        "ttl": 120, "proxied": True,
    }

    invoke(p.execute("update_dns_record", {
        "zone_id": ZONE, "record_id": RECORD, "approved": True,
        "record": {"ttl": 300},
    }))
    assert calls[-1][0] == "PATCH"
    assert calls[-1][1].endswith(f"/zones/{ZONE}/dns_records/{RECORD}")
    assert json.loads(calls[-1][2]) == {"ttl": 300}

    invoke(p.execute("delete_dns_record", {
        "zone_id": ZONE, "record_id": RECORD, "approved": True,
    }))
    assert calls[-1][0] == "DELETE"
    assert calls[-1][1].endswith(f"/zones/{ZONE}/dns_records/{RECORD}")
    assert calls[-1][2] is None


def test_dns_zone_id_and_record_id_path_traversal_fail_before_request(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    for value in ("../other", "a" * 31, "a" * 32 + "/etc", "https://bad.test/", 42):
        with pytest.raises(ValueError, match="zone_id"):
            invoke(p.execute("dns_records", {"zone_id": value}))
        with pytest.raises(ValueError, match="record_id"):
            invoke(p.execute("delete_dns_record", {
                "zone_id": ZONE, "record_id": value, "approved": True,
            }))
    assert len(calls) == 1


def test_dns_content_controls_reject_malformed_mutations_before_network(monkeypatch):
    p, calls, _ = ready(monkeypatch)
    cases = [
        {"type": "A", "name": "x.example.com", "content": "not-an-ip"},
        {"type": "AAAA", "name": "x.example.com", "content": "192.0.2.1"},
        {"type": "CNAME", "name": "x.example.com", "content": "\nBad"},
        {"type": "TXT", "name": "x.example.com", "content": "hello",
         "proxied": True},
        {"type": "A", "name": "x.example.com", "content": "192.0.2.1",
         "ttl": 30},
        {"type": "A", "name": "x.example.com", "content": "192.0.2.1",
         "ttl": True},
        {"type": "A", "name": "a/b", "content": "192.0.2.1"},
        {"type": "A", "name": "x.example.com", "content": "192.0.2.1",
         "token": "secret"},
    ]
    for record in cases:
        with pytest.raises(ValueError):
            invoke(p.execute("create_dns_record", {
                "zone_id": ZONE, "approved": True, "record": record,
            }))
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


def test_missing_endpoint_never_says_connected(monkeypatch):
    p, profile, _, responses = fixture(monkeypatch)
    responses.append(URLError("synthetic DNS error"))
    with pytest.raises(CloudflareRequestError):
        invoke(p.connect(profile, {"credential": Credential(token=SECRET)}))
    assert p.state == ConnectionState.FAILED
    assert p._endpoint is None
    assert p._token is None
