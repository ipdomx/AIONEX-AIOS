#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class HostSpec:
    host_id: str
    service_url: str
    capabilities: tuple[str, ...]
    deployment_host: str


def run(argv: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"stdout={completed.stdout[-4000:]}\n"
            f"stderr={completed.stderr[-4000:]}"
        )
    return completed.stdout


def cert_fingerprint(cert_path: Path) -> str:
    der = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-outform", "DER"],
        capture_output=True,
        check=True,
    ).stdout
    return hashlib.sha256(der).hexdigest()


def write_text(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(mode)


def write_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def create_certificate(
    root: Path,
    ca_key: Path,
    ca_cert: Path,
    name: str,
    *,
    common_name: str,
    san: str,
    extended_key_usage: str,
) -> tuple[Path, Path]:
    key = root / f"{name}.key"
    csr = root / f"{name}.csr"
    cert = root / f"{name}.crt"
    ext = root / f"{name}.ext"
    write_text(
        ext,
        "\n".join(
            (
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                f"extendedKeyUsage={extended_key_usage}",
                f"subjectAltName={san}",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            )
        )
        + "\n",
        0o600,
    )
    run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            f"/CN={common_name}",
        ]
    )
    run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(cert),
            "-days",
            "30",
            "-sha256",
            "-extfile",
            str(ext),
        ]
    )
    key.chmod(0o600)
    cert.chmod(0o644)
    csr.unlink(missing_ok=True)
    ext.unlink(missing_ok=True)
    return key, cert


def generate_material(
    root: Path,
    cluster_id: str,
    hosts: Sequence[HostSpec],
    *,
    control_plane_dns: str = "control-plane",
) -> dict:
    if shutil.which("openssl") is None:
        raise RuntimeError("openssl is required")
    if not cluster_id.strip() or len(hosts) < 1:
        raise ValueError("cluster_id and at least one host are required")
    host_ids = [host.host_id for host in hosts]
    if len(set(host_ids)) != len(host_ids):
        raise ValueError("host IDs must be unique")

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, mode=0o700)
    pki = root / "pki"
    pki.mkdir(mode=0o700)

    ca_key = pki / "ca.key"
    ca_cert = pki / "ca.crt"
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-newkey",
            "rsa:4096",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-days",
            "30",
            "-sha256",
            "-subj",
            f"/CN=AIONEX-{cluster_id}-CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )
    ca_key.chmod(0o600)
    ca_cert.chmod(0o644)

    control_key, control_cert = create_certificate(
        pki,
        ca_key,
        ca_cert,
        "control-plane",
        common_name=control_plane_dns,
        san=f"DNS:{control_plane_dns},DNS:localhost,IP:127.0.0.1",
        extended_key_usage="serverAuth,clientAuth",
    )

    control_directory = root / "control-plane"
    host_secret_directory = root / "host-secrets"
    control_directory.mkdir(mode=0o700)
    host_secret_directory.mkdir(mode=0o700)
    shutil.copy2(ca_cert, control_directory / "ca.crt")
    shutil.copy2(control_cert, control_directory / "control-plane.crt")
    shutil.copy2(control_key, control_directory / "control-plane.key")
    (control_directory / "control-plane.key").chmod(0o600)
    control_env = "\n".join(
        (
            f"AIOS_MULTI_HOST_CLUSTER_ID={cluster_id}",
            "AIOS_MULTI_HOST_STATE_PATH=/var/lib/aionex/phase24b/control-plane.sqlite3",
            "AIOS_MULTI_HOST_SECRET_DIR=/etc/aionex/phase24b/host-secrets",
            "AIOS_MULTI_HOST_ENROLLMENT_MANIFEST=/etc/aionex/phase24b/enrollment.json",
            "AIOS_MULTI_HOST_CA_FILE=/etc/aionex/phase24b/ca.crt",
            "AIOS_MULTI_HOST_CERT_FILE=/etc/aionex/phase24b/control-plane.crt",
            "AIOS_MULTI_HOST_KEY_FILE=/etc/aionex/phase24b/control-plane.key",
            "AIOS_MULTI_HOST_LISTEN_HOST=0.0.0.0",
            "AIOS_MULTI_HOST_LISTEN_PORT=9443",
            "AIOS_MULTI_HOST_HEARTBEAT_TIMEOUT=10",
            "AIOS_MULTI_HOST_LEADER_LEASE=5",
            "AIOS_MULTI_HOST_TASK_LEASE=5",
            "PYTHONPATH=/opt/aionex-phase24b/src",
        )
    ) + "\n"
    write_text(control_directory / "control-plane.env", control_env, 0o600)
    control_unit = """[Unit]
Description=AIONEX Phase 24B Multi-Host Control Plane
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=aionex
Group=aionex
EnvironmentFile=/etc/aionex/phase24b/control-plane.env
ExecStart=/usr/bin/python3 -m aios.multi_host_runtime.control_plane
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/aionex/phase24b

[Install]
WantedBy=multi-user.target
"""
    write_text(
        control_directory / "aionex-phase24b-control-plane.service",
        control_unit,
    )

    enrollment_hosts: list[dict] = []
    for host in hosts:
        host_pki = pki / host.host_id
        host_pki.mkdir(mode=0o700)
        key, cert = create_certificate(
            host_pki,
            ca_key,
            ca_cert,
            host.host_id,
            common_name=host.host_id,
            san=f"DNS:{host.host_id}",
            extended_key_usage="clientAuth",
        )
        secret = secrets.token_bytes(32)
        secret_hex = secret.hex().encode("ascii") + b"\n"
        write_bytes(host_secret_directory / f"{host.host_id}.key", secret_hex)

        bundle = root / host.host_id
        bundle.mkdir(mode=0o700)
        shutil.copy2(ca_cert, bundle / "ca.crt")
        shutil.copy2(cert, bundle / "host.crt")
        shutil.copy2(key, bundle / "host-private.key")
        shutil.copy2(host_secret_directory / f"{host.host_id}.key", bundle / "host.key")
        (bundle / "host-private.key").chmod(0o600)
        (bundle / "host.key").chmod(0o600)

        capabilities = ",".join(host.capabilities)
        env_text = "\n".join(
            (
                f"AIOS_MULTI_HOST_CLUSTER_ID={cluster_id}",
                f"AIOS_MULTI_HOST_HOST_ID={host.host_id}",
                f"AIOS_MULTI_HOST_SERVICE_URL={host.service_url}",
                f"AIOS_MULTI_HOST_CAPABILITIES={capabilities}",
                "AIOS_MULTI_HOST_CONTROL_PLANE_URL=https://CONTROL_PLANE_HOST:9443",
                "AIOS_MULTI_HOST_SOURCE_ROOT=/var/lib/aionex/phase22d",
                "AIOS_MULTI_HOST_SECRET_FILE=/etc/aionex/phase24b/host.key",
                "AIOS_MULTI_HOST_CA_FILE=/etc/aionex/phase24b/ca.crt",
                "AIOS_MULTI_HOST_CERT_FILE=/etc/aionex/phase24b/host.crt",
                "AIOS_MULTI_HOST_KEY_FILE=/etc/aionex/phase24b/host-private.key",
                "PYTHONPATH=/opt/aionex-phase24b/src",
            )
        ) + "\n"
        write_text(bundle / "agent.env", env_text, 0o600)
        unit = """[Unit]
Description=AIONEX Phase 24B Multi-Host Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=aionex
Group=aionex
EnvironmentFile=/etc/aionex/phase24b/agent.env
ExecStart=/usr/bin/python3 -m aios.multi_host_runtime.agent
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/var/lib/aionex/phase22d

[Install]
WantedBy=multi-user.target
"""
        write_text(bundle / "aionex-phase24b-agent.service", unit)
        enrollment_hosts.append(
            {
                "host_id": host.host_id,
                "service_url": host.service_url,
                "capabilities": list(host.capabilities),
                "deployment_host": host.deployment_host,
                "certificate_sha256": cert_fingerprint(cert),
            }
        )

    enrollment = {
        "schema_version": 1,
        "cluster_id": cluster_id,
        "certificate_lifetime_days": 30,
        "hosts": enrollment_hosts,
        "private_keys_committed": False,
        "production_modified": False,
    }
    write_text(
        control_directory / "enrollment.json",
        json.dumps(enrollment, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        0o600,
    )
    ca_key.unlink(missing_ok=True)
    for path in pki.glob("ca.srl"):
        path.unlink(missing_ok=True)
    return enrollment


def parse_host(value: str) -> HostSpec:
    parts = value.split("|", 3)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "host must be host_id|service_url|capability1,capability2|deployment_host"
        )
    host_id, service_url, raw_capabilities, deployment_host = parts
    capabilities = tuple(
        sorted({item.strip().lower() for item in raw_capabilities.split(",") if item.strip()})
    )
    if not host_id or not service_url.startswith("https://") or not capabilities or not deployment_host:
        raise argparse.ArgumentTypeError("host specification is invalid")
    return HostSpec(host_id, service_url, capabilities, deployment_host)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cluster-id", default="aionex-phase24b")
    parser.add_argument("--control-plane-dns", default="control-plane")
    parser.add_argument("--host", action="append", type=parse_host, required=True)
    args = parser.parse_args()
    enrollment = generate_material(
        args.root,
        args.cluster_id,
        args.host,
        control_plane_dns=args.control_plane_dns,
    )
    print(json.dumps(enrollment, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
