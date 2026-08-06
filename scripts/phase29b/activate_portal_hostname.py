#!/usr/bin/env python3
"""Activate the fixed AIONEX public portal hostname through Cloudflare.

This operator intentionally accepts no hostname, origin, tunnel, zone, or path
from the caller. It can only connect ai.vip-e.net to the existing production
Cloudflare Tunnel and the fixed nginx portal listener.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

API_ROOT = "https://api.cloudflare.com/client/v4"
SECRET_PATH = Path("/root/.config/aionex/cloudflare/phase29b-portal.env")
PRODUCTION_ENV_PATH = Path("/opt/AIOS/web-dashboard/.env.production")
ZONE_NAME = "vip-e.net"
PORTAL_HOSTNAME = "ai.vip-e.net"
PORTAL_SERVICE = "http://nginx:8082"
REQUIRED_INGRESS = {
    "api.vip-e.net": "http://nginx:8080",
    "gabarot.vip-e.net": "http://nginx:8081",
}
CATCH_ALL_SERVICE = "http_status:404"
_ID = re.compile(r"^[0-9a-f]{32}$")
_TUNNEL_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PLACEHOLDER_MARKERS = (
    "placeholder",
    "replace-",
    "replace_with",
    "changeme",
    "example-token",
    "cloudflare-api-token",
)


class PortalActivationError(RuntimeError):
    """The fixed portal activation could not be completed safely."""


@dataclass(frozen=True, slots=True, repr=False)
class CloudflareActivationSecret:
    api_token: str
    account_id: str
    zone_id: str


@dataclass(frozen=True, slots=True)
class TunnelIdentity:
    account_id: str
    tunnel_id: str


class CloudflareTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any: ...


class OfficialCloudflareTransport:
    def __init__(self, api_token: str, *, timeout_seconds: float = 30.0) -> None:
        if not api_token or any(character.isspace() for character in api_token):
            raise PortalActivationError("Cloudflare API token is invalid")
        self._api_token = api_token
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any:
        if not path.startswith("/") or ".." in path:
            raise PortalActivationError("Cloudflare API path is invalid")
        url = API_ROOT + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body = None
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
            "User-Agent": "AIONEX-AIOS-Phase29B/1.0",
        }
        if payload is not None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                document = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_codes: list[str] = []
            try:
                document = json.loads(exc.read().decode("utf-8"))
                error_codes = [
                    str(item.get("code"))
                    for item in document.get("errors", [])
                    if isinstance(item, Mapping) and item.get("code") is not None
                ]
            except Exception:
                pass
            suffix = ",".join(error_codes) if error_codes else "unavailable"
            raise PortalActivationError(
                f"Cloudflare API request failed ({exc.code}; codes={suffix})"
            ) from None
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise PortalActivationError(
                f"Cloudflare API request failed ({type(exc).__name__})"
            ) from None
        if not isinstance(document, Mapping) or document.get("success") is not True:
            raise PortalActivationError("Cloudflare API returned an unsuccessful result")
        return document.get("result")


def _read_exact_env(path: Path, *, required_names: set[str]) -> dict[str, str]:
    if not path.is_absolute():
        raise PortalActivationError("configuration path must be absolute")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise PortalActivationError("configuration file is not a safe regular file")
    if info.st_size <= 0 or info.st_size > 16_384:
        raise PortalActivationError("configuration file size is invalid")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PortalActivationError("configuration contains an invalid line")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in values:
            raise PortalActivationError("configuration contains a duplicate variable")
        values[name] = value
    if set(values) != required_names:
        raise PortalActivationError("configuration variables do not match the contract")
    return values


def load_activation_secret(
    path: Path = SECRET_PATH,
    *,
    require_root: bool = True,
) -> CloudflareActivationSecret:
    info = path.lstat()
    if require_root and (info.st_uid != 0 or info.st_gid != 0):
        raise PortalActivationError("Cloudflare activation secret must be root-owned")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise PortalActivationError("Cloudflare activation secret must have mode 600")
    values = _read_exact_env(
        path,
        required_names={
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_ZONE_ID",
        },
    )
    lowered = "\n".join(values.values()).lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise PortalActivationError("Cloudflare activation secret contains a placeholder")
    token = values["CLOUDFLARE_API_TOKEN"]
    account_id = values["CLOUDFLARE_ACCOUNT_ID"].lower()
    zone_id = values["CLOUDFLARE_ZONE_ID"].lower()
    if not 20 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise PortalActivationError("Cloudflare API token is invalid")
    if not _ID.fullmatch(account_id) or not _ID.fullmatch(zone_id):
        raise PortalActivationError("Cloudflare account or zone identifier is invalid")
    return CloudflareActivationSecret(token, account_id, zone_id)


def load_tunnel_identity(
    production_env_path: Path = PRODUCTION_ENV_PATH,
) -> TunnelIdentity:
    values = _read_exact_env_loose(production_env_path)
    token = values.get("CLOUDFLARE_TUNNEL_TOKEN", "")
    if not token:
        raise PortalActivationError("production tunnel token is missing")
    try:
        padded = token + "=" * (-len(token) % 4)
        document = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        raise PortalActivationError("production tunnel token metadata is invalid") from None
    account_id = str(document.get("a") or "").lower()
    tunnel_id = str(document.get("t") or "").lower()
    if not _ID.fullmatch(account_id) or not _TUNNEL_ID.fullmatch(tunnel_id):
        raise PortalActivationError("production tunnel identity is invalid")
    return TunnelIdentity(account_id, tunnel_id)


def _read_exact_env_loose(path: Path) -> dict[str, str]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise PortalActivationError("production environment file is missing or unsafe")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def build_portal_ingress(existing: object) -> list[dict[str, Any]]:
    if not isinstance(existing, list) or not existing:
        raise PortalActivationError("tunnel ingress configuration is missing")
    named: dict[str, dict[str, Any]] = {}
    catch_all: dict[str, Any] | None = None
    ordered: list[dict[str, Any]] = []
    for raw in existing:
        if not isinstance(raw, Mapping):
            raise PortalActivationError("tunnel ingress rule is invalid")
        rule = dict(raw)
        hostname = str(rule.get("hostname") or "").strip().lower()
        service = str(rule.get("service") or "").strip()
        if not service:
            raise PortalActivationError("tunnel ingress service is missing")
        if hostname:
            if hostname in named:
                raise PortalActivationError("tunnel ingress contains duplicate hostnames")
            named[hostname] = rule
            ordered.append(rule)
        else:
            if catch_all is not None:
                raise PortalActivationError("tunnel ingress contains multiple catch-all rules")
            catch_all = rule
    if catch_all is None or str(catch_all.get("service")) != CATCH_ALL_SERVICE:
        raise PortalActivationError("tunnel catch-all rule is missing or unsafe")
    for hostname, service in REQUIRED_INGRESS.items():
        rule = named.get(hostname)
        if rule is None or str(rule.get("service")) != service:
            raise PortalActivationError(
                f"required production ingress is missing or changed: {hostname}"
            )
    portal_rule = dict(named.get(PORTAL_HOSTNAME) or {})
    portal_rule["hostname"] = PORTAL_HOSTNAME
    portal_rule["service"] = PORTAL_SERVICE
    result = [
        rule
        for rule in ordered
        if str(rule.get("hostname") or "").lower() != PORTAL_HOSTNAME
    ]
    result.append(portal_rule)
    result.append(catch_all)
    return result


def _dns_state(records: object, tunnel_id: str) -> tuple[str, str | None]:
    if not isinstance(records, list):
        raise PortalActivationError("Cloudflare DNS record response is invalid")
    matching = [
        record
        for record in records
        if isinstance(record, Mapping)
        and str(record.get("name") or "").lower() == PORTAL_HOSTNAME
    ]
    if len(matching) > 1:
        raise PortalActivationError("multiple DNS records exist for the portal hostname")
    target = f"{tunnel_id}.cfargotunnel.com"
    if not matching:
        return "missing", None
    record = matching[0]
    if str(record.get("type") or "").upper() != "CNAME":
        raise PortalActivationError("portal hostname conflicts with a non-CNAME record")
    record_id = str(record.get("id") or "")
    if not _ID.fullmatch(record_id):
        raise PortalActivationError("portal DNS record identifier is invalid")
    correct = (
        str(record.get("content") or "").lower().rstrip(".") == target
        and record.get("proxied") is True
    )
    return ("ready" if correct else "update"), record_id


def activate_portal_hostname(
    transport: CloudflareTransport,
    *,
    account_id: str,
    zone_id: str,
    tunnel_id: str,
    apply: bool,
) -> dict[str, object]:
    verification = transport.request("GET", "/user/tokens/verify")
    if not isinstance(verification, Mapping) or verification.get("status") != "active":
        raise PortalActivationError("Cloudflare API token is not active")
    zone = transport.request("GET", f"/zones/{zone_id}")
    if (
        not isinstance(zone, Mapping)
        or str(zone.get("name") or "").lower() != ZONE_NAME
        or str((zone.get("account") or {}).get("id") or "").lower() != account_id
    ):
        raise PortalActivationError("Cloudflare zone does not match the production account")
    tunnel = transport.request(
        "GET",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}",
    )
    if (
        not isinstance(tunnel, Mapping)
        or str(tunnel.get("id") or "").lower() != tunnel_id
        or tunnel.get("config_src") != "cloudflare"
    ):
        raise PortalActivationError("production tunnel is missing or not remotely managed")
    configuration = transport.request(
        "GET",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
    )
    if not isinstance(configuration, Mapping) or not isinstance(
        configuration.get("config"), Mapping
    ):
        raise PortalActivationError("production tunnel configuration is invalid")
    original_config = dict(configuration["config"])
    desired_ingress = build_portal_ingress(original_config.get("ingress"))
    desired_config = dict(original_config)
    desired_config["ingress"] = desired_ingress
    records = transport.request(
        "GET",
        f"/zones/{zone_id}/dns_records",
        query={"name": PORTAL_HOSTNAME, "per_page": "100"},
    )
    dns_state, record_id = _dns_state(records, tunnel_id)
    ingress_ready = original_config.get("ingress") == desired_ingress
    if not apply:
        return {
            "success": True,
            "mode": "check",
            "portal_hostname": PORTAL_HOSTNAME,
            "portal_service": PORTAL_SERVICE,
            "tunnel_ingress_ready": ingress_ready,
            "dns_state": dns_state,
            "activation_ready": ingress_ready and dns_state == "ready",
            "secret_returned": False,
        }
    changed_tunnel = not ingress_ready
    if changed_tunnel:
        transport.request(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            payload={"config": desired_config},
        )
    try:
        dns_payload = {
            "type": "CNAME",
            "name": PORTAL_HOSTNAME,
            "content": f"{tunnel_id}.cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
            "comment": "AIONEX AIOS managed public portal origin",
        }
        if dns_state == "missing":
            transport.request(
                "POST",
                f"/zones/{zone_id}/dns_records",
                payload=dns_payload,
            )
        elif dns_state == "update" and record_id is not None:
            transport.request(
                "PUT",
                f"/zones/{zone_id}/dns_records/{record_id}",
                payload=dns_payload,
            )
    except BaseException:
        if changed_tunnel:
            try:
                transport.request(
                    "PUT",
                    f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
                    payload={"config": original_config},
                )
            except BaseException as rollback_exc:
                raise PortalActivationError(
                    "DNS activation failed and tunnel configuration rollback failed"
                ) from rollback_exc
        raise
    verification_config = transport.request(
        "GET",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
    )
    verification_records = transport.request(
        "GET",
        f"/zones/{zone_id}/dns_records",
        query={"name": PORTAL_HOSTNAME, "per_page": "100"},
    )
    final_ingress = build_portal_ingress(
        (verification_config.get("config") or {}).get("ingress")
        if isinstance(verification_config, Mapping)
        else None
    )
    final_dns_state, _ = _dns_state(verification_records, tunnel_id)
    if final_ingress != desired_ingress or final_dns_state != "ready":
        raise PortalActivationError("Cloudflare portal activation verification failed")
    return {
        "success": True,
        "mode": "apply",
        "portal_hostname": PORTAL_HOSTNAME,
        "portal_service": PORTAL_SERVICE,
        "tunnel_ingress_ready": True,
        "dns_state": "ready",
        "activation_ready": True,
        "secret_returned": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check or apply the fixed AIONEX Phase 29B portal hostname activation."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        secret = load_activation_secret()
        identity = load_tunnel_identity()
        if secret.account_id != identity.account_id:
            raise PortalActivationError(
                "Cloudflare activation account does not match the production tunnel"
            )
        result = activate_portal_hostname(
            OfficialCloudflareTransport(secret.api_token),
            account_id=secret.account_id,
            zone_id=secret.zone_id,
            tunnel_id=identity.tunnel_id,
            apply=bool(arguments.apply),
        )
    except (FileNotFoundError, PortalActivationError) as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "status": "blocked",
                    "reason": str(exc),
                    "portal_hostname": PORTAL_HOSTNAME,
                    "portal_service": PORTAL_SERVICE,
                    "secret_returned": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
