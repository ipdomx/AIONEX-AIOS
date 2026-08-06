from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from scripts.phase29b.activate_portal_hostname import (
    PORTAL_HOSTNAME,
    PORTAL_SERVICE,
    PortalActivationError,
    activate_portal_hostname,
    build_portal_ingress,
    load_activation_secret,
    load_tunnel_identity,
)

ACCOUNT_ID = "a" * 32
ZONE_ID = "b" * 32
RECORD_ID = "c" * 32
TUNNEL_ID = "11111111-1111-1111-1111-111111111111"


class FakeCloudflare:
    def __init__(
        self,
        *,
        dns_records: list[dict[str, Any]] | None = None,
        fail_dns: bool = False,
    ) -> None:
        self.config: dict[str, Any] = {
            "ingress": [
                {"hostname": "api.vip-e.net", "service": "http://nginx:8080"},
                {
                    "hostname": "gabarot.vip-e.net",
                    "service": "http://nginx:8081",
                    "originRequest": {"noTLSVerify": False},
                },
                {"service": "http_status:404"},
            ],
            "originRequest": {"connectTimeout": 30},
        }
        self.original_config = json.loads(json.dumps(self.config))
        self.dns_records = list(dns_records or [])
        self.fail_dns = fail_dns
        self.mutations: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any:
        del query
        if method == "GET" and path == "/user/tokens/verify":
            return {"status": "active"}
        if method == "GET" and path == f"/zones/{ZONE_ID}":
            return {
                "id": ZONE_ID,
                "name": "vip-e.net",
                "account": {"id": ACCOUNT_ID},
            }
        if method == "GET" and path == (
            f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}"
        ):
            return {
                "id": TUNNEL_ID,
                "config_src": "cloudflare",
            }
        configuration_path = (
            f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
        )
        if method == "GET" and path == configuration_path:
            return {"config": json.loads(json.dumps(self.config))}
        if method == "PUT" and path == configuration_path:
            assert payload is not None
            self.config = json.loads(json.dumps(payload["config"]))
            self.mutations.append((method, path))
            return {"config": json.loads(json.dumps(self.config))}
        dns_collection = f"/zones/{ZONE_ID}/dns_records"
        if method == "GET" and path == dns_collection:
            return json.loads(json.dumps(self.dns_records))
        if method in {"POST", "PUT"} and path.startswith(dns_collection):
            if self.fail_dns:
                raise PortalActivationError("simulated DNS failure")
            assert payload is not None
            record = {
                "id": RECORD_ID,
                **dict(payload),
            }
            self.dns_records = [record]
            self.mutations.append((method, path))
            return record
        raise AssertionError(f"unexpected request: {method} {path}")


def _secret_file(path: Path, token: str = "x" * 40) -> Path:
    path.write_text(
        "\n".join(
            (
                f"CLOUDFLARE_API_TOKEN={token}",
                f"CLOUDFLARE_ACCOUNT_ID={ACCOUNT_ID}",
                f"CLOUDFLARE_ZONE_ID={ZONE_ID}",
                "",
            )
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_activation_secret_is_exact_mode_bound_and_redacted(tmp_path: Path) -> None:
    path = _secret_file(tmp_path / "cloudflare.env")
    secret = load_activation_secret(path, require_root=False)
    assert secret.account_id == ACCOUNT_ID
    assert secret.zone_id == ZONE_ID
    assert "x" * 20 not in repr(secret)

    path.chmod(0o644)
    with pytest.raises(PortalActivationError, match="mode 600"):
        load_activation_secret(path, require_root=False)

    path = _secret_file(tmp_path / "placeholder.env", "replace-with-token")
    with pytest.raises(PortalActivationError, match="placeholder"):
        load_activation_secret(path, require_root=False)


def test_tunnel_identity_is_derived_without_returning_connector_secret(
    tmp_path: Path,
) -> None:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"a": ACCOUNT_ID, "t": TUNNEL_ID, "s": "hidden"}).encode()
    ).decode().rstrip("=")
    path = tmp_path / "production.env"
    path.write_text(
        f"OTHER=value\nCLOUDFLARE_TUNNEL_TOKEN={encoded}\n",
        encoding="utf-8",
    )
    identity = load_tunnel_identity(path)
    assert identity.account_id == ACCOUNT_ID
    assert identity.tunnel_id == TUNNEL_ID
    assert "hidden" not in repr(identity)


def test_ingress_builder_preserves_required_routes_and_catch_all() -> None:
    original = [
        {"hostname": "api.vip-e.net", "service": "http://nginx:8080"},
        {
            "hostname": "gabarot.vip-e.net",
            "service": "http://nginx:8081",
            "originRequest": {"noTLSVerify": False},
        },
        {"service": "http_status:404"},
    ]
    result = build_portal_ingress(original)
    assert result[-1] == {"service": "http_status:404"}
    portal = next(item for item in result if item.get("hostname") == PORTAL_HOSTNAME)
    assert portal["service"] == PORTAL_SERVICE
    assert next(
        item for item in result if item.get("hostname") == "gabarot.vip-e.net"
    )["originRequest"] == {"noTLSVerify": False}


def test_check_mode_is_read_only_and_reports_missing_dns() -> None:
    cloudflare = FakeCloudflare()
    result = activate_portal_hostname(
        cloudflare,
        account_id=ACCOUNT_ID,
        zone_id=ZONE_ID,
        tunnel_id=TUNNEL_ID,
        apply=False,
    )
    assert result["success"] is True
    assert result["mode"] == "check"
    assert result["tunnel_ingress_ready"] is False
    assert result["dns_state"] == "missing"
    assert result["activation_ready"] is False
    assert cloudflare.mutations == []


def test_apply_adds_fixed_ingress_and_proxied_tunnel_cname() -> None:
    cloudflare = FakeCloudflare()
    result = activate_portal_hostname(
        cloudflare,
        account_id=ACCOUNT_ID,
        zone_id=ZONE_ID,
        tunnel_id=TUNNEL_ID,
        apply=True,
    )
    assert result["activation_ready"] is True
    portal = next(
        item
        for item in cloudflare.config["ingress"]
        if item.get("hostname") == PORTAL_HOSTNAME
    )
    assert portal["service"] == PORTAL_SERVICE
    assert cloudflare.config["ingress"][-1]["service"] == "http_status:404"
    assert cloudflare.dns_records == [
        {
            "id": RECORD_ID,
            "type": "CNAME",
            "name": PORTAL_HOSTNAME,
            "content": f"{TUNNEL_ID}.cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
            "comment": "AIONEX AIOS managed public portal origin",
        }
    ]


def test_dns_failure_rolls_back_the_tunnel_configuration() -> None:
    cloudflare = FakeCloudflare(fail_dns=True)
    with pytest.raises(PortalActivationError, match="simulated DNS failure"):
        activate_portal_hostname(
            cloudflare,
            account_id=ACCOUNT_ID,
            zone_id=ZONE_ID,
            tunnel_id=TUNNEL_ID,
            apply=True,
        )
    assert cloudflare.config == cloudflare.original_config
    configuration_updates = [
        item for item in cloudflare.mutations if item[0] == "PUT"
    ]
    assert len(configuration_updates) == 2


def test_non_cname_conflict_fails_before_any_mutation() -> None:
    cloudflare = FakeCloudflare(
        dns_records=[
            {
                "id": RECORD_ID,
                "type": "A",
                "name": PORTAL_HOSTNAME,
                "content": "192.0.2.1",
                "proxied": True,
            }
        ]
    )
    with pytest.raises(PortalActivationError, match="non-CNAME"):
        activate_portal_hostname(
            cloudflare,
            account_id=ACCOUNT_ID,
            zone_id=ZONE_ID,
            tunnel_id=TUNNEL_ID,
            apply=True,
        )
    assert cloudflare.mutations == []
