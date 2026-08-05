#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


_SSH_TARGET = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._:-]+$")
_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class InventoryTarget:
    role: str
    host_id: str
    ssh_target: str
    bundle_directory: Path


class DeploymentValidationError(ValueError):
    pass


def run(argv: Sequence[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"stdout={completed.stdout[-5000:]}\n"
            f"stderr={completed.stderr[-5000:]}"
        )
    return completed


def load_inventory(path: Path, bundle_root: Path) -> tuple[InventoryTarget, tuple[InventoryTarget, ...]]:
    if not path.is_file() or path.is_symlink():
        raise DeploymentValidationError("inventory is missing or unsafe")
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentValidationError("inventory is invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise DeploymentValidationError("inventory must be an object")
    control = decoded.get("control_plane")
    hosts = decoded.get("hosts")
    if not isinstance(control, dict) or not isinstance(hosts, list) or len(hosts) != 3:
        raise DeploymentValidationError("inventory requires one control plane and exactly three hosts")

    def target(role: str, item: dict[str, Any], bundle_name: str) -> InventoryTarget:
        host_id = str(item.get("host_id") or "")
        ssh_target = str(item.get("ssh_target") or "")
        if not _HOST_ID.fullmatch(host_id):
            raise DeploymentValidationError(f"invalid host_id for {role}")
        if not _SSH_TARGET.fullmatch(ssh_target):
            raise DeploymentValidationError(f"invalid ssh_target for {role}")
        bundle = (bundle_root / bundle_name).resolve(strict=True)
        if bundle_root.resolve(strict=True) not in bundle.parents:
            raise DeploymentValidationError("bundle escapes bundle_root")
        return InventoryTarget(role, host_id, ssh_target, bundle)

    control_target = target("control-plane", control, "control-plane")
    host_targets = tuple(
        target("agent", item, str(item.get("host_id") or ""))
        for item in hosts
        if isinstance(item, dict)
    )
    if len(host_targets) != 3:
        raise DeploymentValidationError("host entries are invalid")
    if len({item.host_id for item in host_targets}) != 3:
        raise DeploymentValidationError("host IDs must be unique")
    if len({item.ssh_target for item in (control_target, *host_targets)}) != 4:
        raise DeploymentValidationError("each role must use a distinct SSH target")
    expected_ids = {
        item["host_id"]
        for item in json.loads(
            (bundle_root / "control-plane/enrollment.json").read_text(encoding="utf-8")
        )["hosts"]
    }
    if {item.host_id for item in host_targets} != expected_ids:
        raise DeploymentValidationError("inventory hosts do not match the enrollment manifest")
    return control_target, host_targets


def source_archive(project_root: Path, destination: Path) -> None:
    required = (project_root / "src", project_root / "pyproject.toml", project_root / "README.md")
    if not all(path.exists() for path in required):
        raise DeploymentValidationError("project source is incomplete")
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(project_root / "src", arcname="src")
        archive.add(project_root / "pyproject.toml", arcname="pyproject.toml")
        archive.add(project_root / "README.md", arcname="README.md")


def ssh(target: str, remote_command: str, *, apply: bool) -> list[str]:
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        target,
        remote_command,
    ]
    if apply:
        run(argv)
    return argv


def scp(source: Path, target: str, destination: str, *, recursive: bool, apply: bool) -> list[str]:
    argv = [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
    ]
    if recursive:
        argv.append("-r")
    argv.extend([str(source), f"{target}:{destination}"])
    if apply:
        run(argv)
    return argv


def deploy_target(
    target: InventoryTarget,
    archive: Path,
    bundle_root: Path,
    *,
    apply: bool,
) -> list[list[str]]:
    staging = f"/tmp/aionex-phase24b-{target.host_id}"
    commands: list[list[str]] = []
    commands.append(
        ssh(
            target.ssh_target,
            f"rm -rf {shlex.quote(staging)} && mkdir -p {shlex.quote(staging)}",
            apply=apply,
        )
    )
    commands.append(scp(archive, target.ssh_target, f"{staging}/source.tar.gz", recursive=False, apply=apply))
    commands.append(scp(target.bundle_directory, target.ssh_target, staging, recursive=True, apply=apply))
    if target.role == "control-plane":
        host_secrets = bundle_root / "host-secrets"
        commands.append(scp(host_secrets, target.ssh_target, staging, recursive=True, apply=apply))
        remote = " && ".join(
            (
                "sudo -n id aionex >/dev/null 2>&1 || sudo -n useradd --system --home /nonexistent --shell /usr/sbin/nologin aionex",
                "sudo -n install -d -o root -g aionex -m 0750 /opt/aionex-phase24b /etc/aionex/phase24b /var/lib/aionex/phase24b",
                f"sudo -n tar -xzf {shlex.quote(staging)}/source.tar.gz -C /opt/aionex-phase24b",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/control-plane/ca.crt /etc/aionex/phase24b/ca.crt",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/control-plane/control-plane.crt /etc/aionex/phase24b/control-plane.crt",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/control-plane/control-plane.key /etc/aionex/phase24b/control-plane.key",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/control-plane/control-plane.env /etc/aionex/phase24b/control-plane.env",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/control-plane/enrollment.json /etc/aionex/phase24b/enrollment.json",
                "sudo -n install -d -o root -g aionex -m 0750 /etc/aionex/phase24b/host-secrets",
                f"sudo -n cp {shlex.quote(staging)}/host-secrets/*.key /etc/aionex/phase24b/host-secrets/",
                "sudo -n chown root:aionex /etc/aionex/phase24b/host-secrets/*.key && sudo -n chmod 0640 /etc/aionex/phase24b/host-secrets/*.key",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/control-plane/aionex-phase24b-control-plane.service /etc/systemd/system/aionex-phase24b-control-plane.service",
                "sudo -n systemctl daemon-reload",
                "sudo -n systemctl enable --now aionex-phase24b-control-plane.service",
            )
        )
    else:
        remote = " && ".join(
            (
                "sudo -n id aionex >/dev/null 2>&1 || sudo -n useradd --system --home /nonexistent --shell /usr/sbin/nologin aionex",
                "sudo -n install -d -o root -g aionex -m 0750 /opt/aionex-phase24b /etc/aionex/phase24b /var/lib/aionex/phase22d",
                f"sudo -n tar -xzf {shlex.quote(staging)}/source.tar.gz -C /opt/aionex-phase24b",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/{target.host_id}/ca.crt /etc/aionex/phase24b/ca.crt",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/{target.host_id}/host.crt /etc/aionex/phase24b/host.crt",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/{target.host_id}/host-private.key /etc/aionex/phase24b/host-private.key",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/{target.host_id}/host.key /etc/aionex/phase24b/host.key",
                f"sudo -n install -m 0640 -o root -g aionex {shlex.quote(staging)}/{target.host_id}/agent.env /etc/aionex/phase24b/agent.env",
                f"sudo -n install -m 0644 {shlex.quote(staging)}/{target.host_id}/aionex-phase24b-agent.service /etc/systemd/system/aionex-phase24b-agent.service",
                "sudo -n systemctl daemon-reload",
                "sudo -n systemctl enable --now aionex-phase24b-agent.service",
            )
        )
    commands.append(ssh(target.ssh_target, remote, apply=apply))
    return commands


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path("/opt/AIOS"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    bundle_root = args.bundle_root.resolve(strict=True)
    control, hosts = load_inventory(args.inventory, bundle_root)
    with tempfile.TemporaryDirectory(prefix="aionex-phase24b-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        source_archive(args.project_root.resolve(strict=True), archive)
        plan: list[list[str]] = []
        for target in (control, *hosts):
            plan.extend(
                deploy_target(
                    target,
                    archive,
                    bundle_root,
                    apply=args.apply,
                )
            )
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "targets": [target.ssh_target for target in (control, *hosts)],
                "commands": plan,
                "production_modified": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
