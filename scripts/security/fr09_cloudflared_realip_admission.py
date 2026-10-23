#!/usr/bin/env python3
"""Admit exactly one live Cloudflared TCP peer to Nginx RealIP, without reload.

This prepares an *optional* Nginx overlay. It never changes the production
service, DNS, Cloudflare, Docker networks, customer data, or rollback images.
A separately reviewed change must activate the overlay and reload Nginx.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any

PROJECT = "web-dashboard"
NGINX_NAME = "web-dashboard-nginx-1"
TUNNEL_NAME = "web-dashboard-cloudflared-1"
DEFAULT_OUTPUT_DIR = Path("/var/lib/aionex-migration/fr09-trusted-realip")
OUTPUT_NAME = "trusted-cloudflared.conf"


class RealIPAdmissionError(ValueError):
    """Refuse uncertain or untrusted Docker peer metadata."""


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RealIPAdmissionError(f"{label} must be an object")
    return value


def _check_identity(item: dict[str, Any], *, name: str, service: str) -> None:
    if item.get("Name") != f"/{name}":
        raise RealIPAdmissionError("Docker container identity mismatch")
    config = _as_object(item.get("Config"), "container Config")
    labels = _as_object(config.get("Labels"), "container labels")
    if (
        labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != service
    ):
        raise RealIPAdmissionError("Docker Compose project or service mismatch")
    state = _as_object(item.get("State"), "container State")
    if state.get("Running") is not True:
        raise RealIPAdmissionError("trusted peer or gateway is not running")


def _ipv4_network(raw: dict[str, Any], label: str) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Network]:
    address = raw.get("IPAddress")
    prefix = raw.get("IPPrefixLen")
    if not isinstance(address, str) or type(prefix) is not int:
        raise RealIPAdmissionError(f"{label} IPv4 address and prefix required")
    try:
        ip = ipaddress.IPv4Address(address)
        net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
    except ipaddress.AddressValueError as exc:
        raise RealIPAdmissionError("invalid Docker IPv4 address") from exc
    except ipaddress.NetmaskValueError as exc:
        raise RealIPAdmissionError("invalid Docker IPv4 prefix") from exc
    if not ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise RealIPAdmissionError("trusted peer must use a private, routable container IPv4")
    if prefix < 12 or prefix > 30:
        raise RealIPAdmissionError("unexpected private Docker bridge CIDR size")
    return ip, net


def admitted_tunnel_peer(nginx: dict[str, Any], tunnel: dict[str, Any]) -> ipaddress.IPv4Address:
    """Require one exact running Compose tunnel peer on the same private subnet."""
    _check_identity(nginx, name=NGINX_NAME, service="nginx")
    _check_identity(tunnel, name=TUNNEL_NAME, service="cloudflared")
    ng_nets = _as_object(
        _as_object(nginx.get("NetworkSettings"), "nginx NetworkSettings").get("Networks"),
        "nginx networks",
    )
    cl_nets = _as_object(
        _as_object(tunnel.get("NetworkSettings"), "tunnel NetworkSettings").get("Networks"),
        "tunnel networks",
    )
    shared = sorted(
        name for name in (set(ng_nets) & set(cl_nets))
        if name == f"{PROJECT}_aionex-network"
    )
    if len(shared) != 1:
        raise RealIPAdmissionError("exactly one approved shared Docker network is required")
    gateway_ip, gateway_net = _ipv4_network(
        _as_object(ng_nets[shared[0]], "nginx network"), "nginx"
    )
    peer_ip, peer_net = _ipv4_network(
        _as_object(cl_nets[shared[0]], "cloudflared network"), "cloudflared"
    )
    if gateway_net != peer_net or gateway_ip == peer_ip or peer_ip not in gateway_net:
        raise RealIPAdmissionError("cloudflared and Nginx network provenance differs")
    return peer_ip


def render_trusted_peer(peer: ipaddress.IPv4Address) -> bytes:
    """No broad RFC1918, Cloudflare public, loopback, or arbitrary header trust."""
    if (type(peer) is not ipaddress.IPv4Address or not peer.is_private
            or peer.is_loopback or peer.is_unspecified
            or peer.is_multicast or peer.is_reserved):
        raise RealIPAdmissionError("invalid exact trusted source IP")
    return (
        "# AIONEX FR09: generated from the running, labeled Cloudflared peer.\n"
        f"set_real_ip_from {peer}/32;\n"
        "real_ip_header CF-Connecting-IP;\n"
        "real_ip_recursive off;\n"
    ).encode("ascii")


def _live_inspect() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["docker", "inspect", NGINX_NAME, TUNNEL_NAME],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RealIPAdmissionError("Docker peer evidence is unavailable") from exc
    if completed.returncode:
        raise RealIPAdmissionError("Docker peer inspection failed")
    try:
        items = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RealIPAdmissionError("Docker peer evidence is not JSON") from exc
    if not isinstance(items, list) or len(items) != 2:
        raise RealIPAdmissionError("exactly two peer records are required")
    return (_as_object(items[0], "nginx"), _as_object(items[1], "cloudflared"))


def _safe_directory(directory: Path) -> None:
    if not directory.is_absolute():
        raise RealIPAdmissionError("output directory must be absolute")
    if directory.is_symlink():
        raise RealIPAdmissionError("output directory must not be a symbolic link")
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    st = directory.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise RealIPAdmissionError("output directory must be owned by root and non-writable by others")
    os.chmod(directory, 0o755)


def apply_config(payload: bytes, directory: Path) -> str:
    """Atomically stage trust for later separately reviewed Nginx reload."""
    if os.geteuid() != 0:
        raise RealIPAdmissionError("writing trusted peer config requires root")
    _safe_directory(directory)
    target = directory / OUTPUT_NAME
    if target.is_symlink():
        raise RealIPAdmissionError("trusted peer config must not be a symlink")
    if any(p.name != OUTPUT_NAME for p in directory.glob("*.conf")):
        raise RealIPAdmissionError("unreviewed additional trusted-source config is forbidden")
    if target.exists():
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0:
            raise RealIPAdmissionError("existing trusted peer config owner/type invalid")
        if target.read_bytes() == payload:
            return "UNCHANGED"
    fd, pathname = tempfile.mkstemp(prefix=".fr09-realip-", dir=directory)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pathname, target)
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(pathname):
            os.unlink(pathname)
    return "STAGED_NOT_RELOADED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="stage root-owned source-IP trust, no reload")
    args = parser.parse_args()
    try:
        peer = admitted_tunnel_peer(*_live_inspect())
        payload = render_trusted_peer(peer)
        decision = (
            apply_config(payload, DEFAULT_OUTPUT_DIR)
            if args.apply else "DRY_RUN_NOT_WRITTEN"
        )
        print(json.dumps({
            "status": decision,
            "trusted_peer": "exact_live_cloudflared_container_ipv4_32",
            "trusted_peer_sha256": hashlib.sha256(str(peer).encode()).hexdigest(),
            "config_sha256": hashlib.sha256(payload).hexdigest(),
            "output": str(DEFAULT_OUTPUT_DIR / OUTPUT_NAME),
            "nginx_reloaded": False,
            "production_reconfigured": False,
            "automatic_provider_calls": False,
            "final_release_accepted": False,
        }, sort_keys=True))
        return 0
    except RealIPAdmissionError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc),
                          "nginx_reloaded": False, "production_reconfigured": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
