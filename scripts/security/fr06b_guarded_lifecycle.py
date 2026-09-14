#!/usr/bin/env python3
"""Fail-closed FR-06B3B guarded lifecycle and final-delta executor.

The executor is intentionally unable to unlock or create vaults, change Cloudflare,
or open application admission. A successful cutover stops at
"candidate_started_admission_closed" so live acceptance remains a separate gate.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
SUBPART = "FR-06B3B"
PRODUCTION_ROOT = Path("/opt/AIOS")
PRODUCTION_STATE_DIR = Path("/var/lib/aionex/fr06b3b")
PRODUCTION_ENV_FILE = PRODUCTION_ROOT / "web-dashboard" / ".env.production"
PRODUCTION_DOCKER_HOSTS = {
    "unix:///run/docker.sock",
    "unix:///var/run/docker.sock",
}
MAX_PLAN_TTL_SECONDS = 900
MAX_WINDOW_SECONDS = 4 * 60 * 60
MAX_START_ATTEMPTS = 3
MAX_RETAINED_INSTANCE_COUNT = 256
SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class LifecycleError(RuntimeError):
    """Malformed input or an operational failure with details safe to retain."""


class LifecycleBlocked(RuntimeError):
    """A well-formed request that does not satisfy every safety gate."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LifecycleError(f"{label} must be an RFC3339 UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LifecycleError(f"{label} is not a valid timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"cannot read valid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise LifecycleError(f"JSON object required: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)
    except OSError as exc:
        raise LifecycleError(f"cannot hash input: {path}") from exc


def _ensure_regular_private_input(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise LifecycleError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise LifecycleError(f"{label} must be a real regular file")
    if info.st_mode & 0o022:
        raise LifecycleBlocked(f"{label} must not be group/world writable")


def _write_json_exclusive(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise LifecycleBlocked(f"one-time output already exists: {path.name}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_json_atomic(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    fd = os.open(temporary, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    allowed: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LifecycleError(f"required executable unavailable: {argv[0]}") from exc
    accepted = allowed or {0}
    if result.returncode not in accepted:
        raise LifecycleError(
            f"{argv[0]} failed with exit code {result.returncode}; output withheld"
        )
    return result


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LifecycleError(f"cannot load required module: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_contracts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_dir = root / "docs" / "project" / "receipts"
    b2 = _json_object(receipt_dir / "FR-06B2-compose-cutover-contract.json")
    b3a = _json_object(receipt_dir / "FR-06B3A-admission-restart-contract.json")
    matrix = b2.get("matrix")
    restart = b3a.get("restart_policy")
    if not isinstance(matrix, dict) or not isinstance(restart, dict):
        raise LifecycleError("FR-06 contract shape is invalid")
    writers = matrix.get("runtime_writer_services")
    readers = matrix.get("read_only_only_services")
    initializers = matrix.get("initializer_services")
    roots = matrix.get("roots")
    if (
        not isinstance(writers, list)
        or len(set(writers)) != 18
        or not isinstance(readers, list)
        or len(set(readers)) != 2
        or not isinstance(initializers, list)
        or len(set(initializers)) != 2
        or not isinstance(roots, list)
        or len(roots) != 11
    ):
        raise LifecycleBlocked("FR-06B2 service/root matrix drifted")
    guarded = sorted(set(writers) | set(readers))
    if (
        restart.get("guarded_runtime_policy") != "no"
        or sorted(restart.get("protected_runtime_services", [])) != guarded
        or restart.get("protected_runtime_service_count") != 20
        or b3a.get("admission_gate", {}).get("production_authorization_capability") is not False
    ):
        raise LifecycleBlocked("FR-06B3A guarded restart contract drifted")
    return b2, b3a


def _evaluate_admission(
    root: Path,
    evidence: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    allow_isolated_lab: bool,
    max_age_seconds: int,
) -> dict[str, Any]:
    module = _load_module(
        root / "scripts" / "security" / "fr06b_cutover_admission.py",
        f"fr06b3a_admission_{secrets.token_hex(4)}",
    )
    try:
        result = module.evaluate(
            evidence,
            snapshot,
            allow_isolated_lab,
            max_age_seconds,
        )
    except Exception as exc:
        if isinstance(exc, (module.AdmissionError, module.AdmissionBlocked)):
            raise LifecycleBlocked(f"FR-06B3A admission rejected: {exc}") from exc
        raise
    environment = evidence.get("environment")
    wanted = (
        "isolated_lab_ready"
        if environment == "isolated_lab"
        else "production_preflight_ready"
    )
    if (
        result.get("preflight_passed") is not True
        or result.get("decision") != wanted
        or result.get("production_authorized") is not False
        or result.get("executor_present") is not False
        or result.get("blockers") != []
    ):
        raise LifecycleBlocked("fresh FR-06B3A preflight did not pass")
    return result


def _fresh_admitted_snapshot(
    root: Path,
    evidence: dict[str, Any],
    snapshot: dict[str, Any],
    env_file: Path,
    docker_host: str,
    max_age_seconds: int,
) -> dict[str, Any]:
    if evidence.get("environment") != "production":
        _evaluate_admission(
            root,
            evidence,
            snapshot,
            allow_isolated_lab=True,
            max_age_seconds=max_age_seconds,
        )
        return snapshot
    module = _load_module(
        root / "scripts" / "security" / "fr06b_cutover_admission.py",
        f"fr06b3a_live_inspection_{secrets.token_hex(4)}",
    )
    mapper_items = snapshot.get("mappers")
    volume_items = snapshot.get("volumes")
    if not isinstance(mapper_items, list) or not isinstance(volume_items, list):
        raise LifecycleError("admitted snapshot topology is incomplete")
    mappers = {
        str(item.get("role")): item
        for item in mapper_items
        if isinstance(item, dict)
    }
    volumes = {
        str(item.get("role")): item
        for item in volume_items
        if isinstance(item, dict)
    }
    roles = {"asset-vault", "project-execution-vault"}
    if set(mappers) != roles or set(volumes) != roles:
        raise LifecycleBlocked("admitted mapper or volume role matrix drifted")
    try:
        fresh = module.inspect_runtime(
            argparse.Namespace(
                root=root,
                env_file=env_file,
                docker_host=docker_host,
                environment="production",
                asset_mapper=Path(str(mappers["asset-vault"]["path"])),
                project_mapper=Path(str(mappers["project-execution-vault"]["path"])),
                asset_mount_root=Path(str(mappers["asset-vault"]["mount_root"])),
                project_mount_root=Path(
                    str(mappers["project-execution-vault"]["mount_root"])
                ),
                asset_volume=str(volumes["asset-vault"]["name"]),
                project_volume=str(volumes["project-execution-vault"]["name"]),
            )
        )
    except Exception as exc:
        if isinstance(exc, (module.AdmissionError, module.AdmissionBlocked)):
            raise LifecycleBlocked(
                "live FR-06B3A runtime reinspection failed closed"
            ) from exc
        raise
    _evaluate_admission(
        root,
        evidence,
        fresh,
        allow_isolated_lab=False,
        max_age_seconds=max_age_seconds,
    )
    return fresh


def _validate_window(evidence: dict[str, Any], environment: str, now: datetime) -> None:
    if environment == "isolated_lab":
        return
    approvals = evidence.get("approvals")
    if not isinstance(approvals, dict):
        raise LifecycleBlocked("production approvals are missing")
    start = _parse_time(approvals.get("window_starts_at"), "window_starts_at")
    end = _parse_time(approvals.get("window_ends_at"), "window_ends_at")
    if end <= start or (end - start).total_seconds() > MAX_WINDOW_SECONDS:
        raise LifecycleBlocked("maintenance window bounds are invalid")
    if not (start <= now <= end):
        raise LifecycleBlocked("current time is outside the approved maintenance window")
    if approvals.get("owner_authorized") is not True:
        raise LifecycleBlocked("owner authorization is absent")


def _validate_environment(
    root: Path,
    state_dir: Path,
    env_file: Path,
    docker_host: str,
    evidence: dict[str, Any],
    lab_layout: dict[str, Any] | None,
    allow_isolated_lab: bool,
) -> tuple[str, Path | None]:
    environment = evidence.get("environment")
    if environment not in {"isolated_lab", "production"}:
        raise LifecycleError("evidence.environment is invalid")
    if environment == "production":
        if allow_isolated_lab or lab_layout is not None:
            raise LifecycleBlocked("lab controls cannot be mixed with production")
        if root.resolve() != PRODUCTION_ROOT:
            raise LifecycleBlocked("production project root must be /opt/AIOS")
        if state_dir != PRODUCTION_STATE_DIR:
            raise LifecycleBlocked("production state directory is fixed")
        if env_file.resolve() != PRODUCTION_ENV_FILE:
            raise LifecycleBlocked("production env file is fixed")
        if docker_host not in PRODUCTION_DOCKER_HOSTS:
            raise LifecycleBlocked("production Docker socket is not allowlisted")
        if os.geteuid() != 0:
            raise LifecycleBlocked("production lifecycle requires root")
        return environment, None
    if not allow_isolated_lab or lab_layout is None:
        raise LifecycleBlocked("isolated lab requires explicit flag and layout")
    if lab_layout.get("schema_version") != 1:
        raise LifecycleError("lab layout schema is invalid")
    sandbox_value = lab_layout.get("sandbox_root")
    if not isinstance(sandbox_value, str) or not SAFE_PATH_RE.fullmatch(sandbox_value):
        raise LifecycleBlocked("lab sandbox root is invalid")
    sandbox = Path(sandbox_value).resolve(strict=True)
    if root.resolve() == PRODUCTION_ROOT:
        raise LifecycleBlocked("isolated lab cannot target the production root")
    if not _is_within(state_dir.resolve(), sandbox):
        raise LifecycleBlocked("lab state directory must stay inside its sandbox")
    if docker_host in PRODUCTION_DOCKER_HOSTS:
        raise LifecycleBlocked("isolated lab cannot use the production Docker socket")
    return environment, sandbox


def _secure_state_dir(path: Path, environment: str, sandbox: Path | None) -> Path:
    if not path.is_absolute() or not SAFE_PATH_RE.fullmatch(str(path)):
        raise LifecycleBlocked("state directory must be a safe absolute path")
    if environment == "production" and path != PRODUCTION_STATE_DIR:
        raise LifecycleBlocked("production state directory drifted")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise LifecycleBlocked("state directory must be a real directory")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise LifecycleBlocked("state directory must be mode 0700")
    if environment == "production" and info.st_uid != 0:
        raise LifecycleBlocked("production state directory must be root-owned")
    resolved = path.resolve()
    if environment == "production" and resolved != path:
        raise LifecycleBlocked("production state directory cannot traverse symlinks")
    if sandbox is not None and not _is_within(resolved, sandbox):
        raise LifecycleBlocked("lab state directory escaped the sandbox")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _safe_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or not SAFE_PATH_RE.fullmatch(str(path)):
        raise LifecycleBlocked(f"{label} is not a safe absolute path")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise LifecycleBlocked(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise LifecycleBlocked(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _root_rows(b2: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in b2["matrix"]["roots"]:
        if not isinstance(item, dict):
            raise LifecycleError("invalid FR-06B2 root row")
        rows.append(
            {
                "name": str(item["compose_volume"]),
                "vault": str(item["vault"]),
                "target_subpath": str(item["target_subpath"]),
            }
        )
    if len({row["name"] for row in rows}) != 11:
        raise LifecycleBlocked("FR-06B2 root names are not unique")
    return rows


def _validate_pairs(pairs: list[dict[str, str]], sandbox: Path | None) -> None:
    if len(pairs) != 11:
        raise LifecycleBlocked("exactly eleven root pairs are required")
    seen_source: set[Path] = set()
    seen_target: set[Path] = set()
    for pair in pairs:
        source = _safe_directory(Path(pair["source"]), f"{pair['name']}:source")
        target = _safe_directory(Path(pair["target"]), f"{pair['name']}:target")
        if source == target or _is_within(source, target) or _is_within(target, source):
            raise LifecycleBlocked(f"{pair['name']}: source/target overlap")
        if source in seen_source or target in seen_target:
            raise LifecycleBlocked("duplicate source or target root")
        if sandbox is not None and (
            not _is_within(source, sandbox) or not _is_within(target, sandbox)
        ):
            raise LifecycleBlocked("lab root escaped the sandbox")
        pair["source"] = str(source)
        pair["target"] = str(target)
        seen_source.add(source)
        seen_target.add(target)


def _production_pairs(
    b2: dict[str, Any],
    snapshot: dict[str, Any],
    docker_host: str,
) -> list[dict[str, str]]:
    mappers = snapshot.get("mappers")
    if not isinstance(mappers, list):
        raise LifecycleError("snapshot mapper list missing")
    mount_by_role: dict[str, Path] = {}
    for item in mappers:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role"))
        mount_root = item.get("mount_root")
        if not isinstance(mount_root, str):
            raise LifecycleBlocked(f"{role}: mount root was not retained")
        mount_by_role[role] = _safe_directory(Path(mount_root), f"{role}:mount")
    pairs: list[dict[str, str]] = []
    for row in _root_rows(b2):
        volume_name = f"web-dashboard_{row['name']}"
        result = _run(
            ["docker", "--host", docker_host, "volume", "inspect", volume_name],
            timeout=30,
        )
        try:
            inspected = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LifecycleError("Docker volume inspection was not JSON") from exc
        if (
            not isinstance(inspected, list)
            or len(inspected) != 1
            or inspected[0].get("Driver") != "local"
        ):
            raise LifecycleBlocked(f"{row['name']}: legacy Docker volume drifted")
        mountpoint = inspected[0].get("Mountpoint")
        if not isinstance(mountpoint, str):
            raise LifecycleBlocked(f"{row['name']}: legacy mountpoint missing")
        vault_root = mount_by_role.get(row["vault"])
        if vault_root is None:
            raise LifecycleBlocked(f"{row['vault']}: candidate mount missing")
        target = vault_root / row["target_subpath"]
        target_resolved = _safe_directory(target, f"{row['name']}:candidate")
        if not _is_within(target_resolved, vault_root):
            raise LifecycleBlocked(f"{row['name']}: candidate escaped vault")
        pairs.append(
            {
                **row,
                "source": str(_safe_directory(Path(mountpoint), f"{row['name']}:legacy")),
                "target": str(target_resolved),
                "legacy_volume": volume_name,
                "candidate_volume": (
                    "aionex-fr06-asset-vault"
                    if row["vault"] == "asset-vault"
                    else "aionex-fr06-project-execution-vault"
                ),
            }
        )
    _validate_pairs(pairs, None)
    return pairs


def _lab_pairs(
    b2: dict[str, Any],
    layout: dict[str, Any],
    sandbox: Path,
) -> list[dict[str, str]]:
    sources = layout.get("source_roots")
    targets = layout.get("target_roots")
    if not isinstance(sources, dict) or not isinstance(targets, dict):
        raise LifecycleError("lab source_roots and target_roots are required")
    rows = _root_rows(b2)
    wanted = {row["name"] for row in rows}
    if set(sources) != wanted or set(targets) != wanted:
        raise LifecycleBlocked("lab layout root matrix drifted")
    pairs = [
        {
            **row,
            "source": str(sources[row["name"]]),
            "target": str(targets[row["name"]]),
            "legacy_volume": f"lab-legacy-{row['name']}",
            "candidate_volume": f"lab-candidate-{row['vault']}",
        }
        for row in rows
    ]
    _validate_pairs(pairs, sandbox)
    return pairs


def _service_matrix(b2: dict[str, Any]) -> tuple[list[str], list[str]]:
    matrix = b2["matrix"]
    runtime = sorted(
        set(matrix["runtime_writer_services"]) | set(matrix["read_only_only_services"])
    )
    initializers = sorted(matrix["initializer_services"])
    return runtime, initializers


def _validated_active_instances(
    value: Any,
    allowed_services: Iterable[str],
) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise LifecycleBlocked("retained active service topology is missing")
    allowed = set(allowed_services)
    if not set(value).issubset(allowed):
        raise LifecycleBlocked("retained receipt contains an unreviewed service")
    total = 0
    result: dict[str, list[str]] = {}
    for service, identifiers in value.items():
        if not isinstance(service, str) or not isinstance(identifiers, list) or not identifiers:
            raise LifecycleBlocked("retained service instance topology is invalid")
        if any(
            not isinstance(identifier, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier) is None
            for identifier in identifiers
        ):
            raise LifecycleBlocked("retained service instance identifier is invalid")
        if len(set(identifiers)) != len(identifiers):
            raise LifecycleBlocked("retained service instance identifier is duplicated")
        total += len(identifiers)
        result[service] = list(identifiers)
    if total > MAX_RETAINED_INSTANCE_COUNT:
        raise LifecycleBlocked("retained service instance count exceeds the safety bound")
    return dict(sorted(result.items()))


def _expected_service_mounts(b2: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for root in b2["matrix"]["roots"]:
        for consumer in root["consumers"]:
            service = str(consumer["service"])
            result.setdefault(service, []).append(
                {
                    "root": str(root["compose_volume"]),
                    "vault": str(root["vault"]),
                    "target": str(consumer["target"]),
                    "rw": consumer["access"] == "rw",
                }
            )
    return result


class LabRuntime:
    def __init__(
        self,
        state_path: Path,
        runtime_services: list[str],
        initializers: list[str],
    ) -> None:
        self.state_path = state_path
        self.runtime_services = runtime_services
        self.initializers = initializers

    def _load(self) -> dict[str, Any]:
        value = _json_object(self.state_path)
        if value.get("schema_version") != 1:
            raise LifecycleError("lab runtime state schema is invalid")
        services = value.get("services")
        if not isinstance(services, dict) or set(services) != set(self.runtime_services):
            raise LifecycleBlocked("lab runtime service matrix drifted")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        _write_json_atomic(self.state_path, value)

    def topology(self, mode: str, *, allow_stopped: bool = True) -> dict[str, list[str]]:
        value = self._load()
        if value.get("unlisted_consumers"):
            raise LifecycleBlocked("lab runtime has an unlisted volume consumer")
        active: dict[str, list[str]] = {}
        for service in self.runtime_services:
            item = value["services"][service]
            if not isinstance(item, dict):
                raise LifecycleError("lab runtime service state is invalid")
            running = item.get("running") is True
            if running:
                if item.get("mount_mode") != mode:
                    raise LifecycleBlocked(f"{service}: lab mount mode drifted")
                wanted_policy = "unless-stopped" if mode == "legacy" else "no"
                if item.get("restart_policy") != wanted_policy:
                    raise LifecycleBlocked(f"{service}: lab restart policy drifted")
                instances = item.get("instances")
                if not isinstance(instances, list) or not instances:
                    raise LifecycleBlocked(f"{service}: lab instance list missing")
                active[service] = [str(item_id) for item_id in instances]
            elif not allow_stopped and item.get("desired") is True:
                raise LifecycleBlocked(f"{service}: expected lab service is stopped")
        return active

    def exact_stop(self, expected: dict[str, list[str]], mode: str) -> None:
        value = self._load()
        current = self.topology(mode)
        if current != expected:
            raise LifecycleBlocked("lab runtime topology changed after planning")
        for service in expected:
            value["services"][service]["running"] = False
        self._save(value)

    def stop_mode(self, mode: str) -> None:
        value = self._load()
        for service, item in value["services"].items():
            if item.get("running") is True and item.get("mount_mode") == mode:
                item["running"] = False
        self._save(value)

    def assert_stopped(self) -> None:
        value = self._load()
        if any(item.get("running") is True for item in value["services"].values()):
            raise LifecycleBlocked("lab protected service remains running")
        if value.get("unlisted_writers"):
            raise LifecycleBlocked("lab unlisted writable descriptor remains")

    def start_initializers(self, mode: str) -> None:
        value = self._load()
        value.setdefault("events", []).append(f"initializers:{mode}")
        self._save(value)
        if value.get("fail_phase") == f"{mode}_initializer":
            raise LifecycleError("injected lab initializer failure")

    def start_services(self, desired: dict[str, list[str]], mode: str) -> None:
        value = self._load()
        policy = "unless-stopped" if mode == "legacy" else "no"
        for service, identifiers in desired.items():
            item = value["services"][service]
            item["instances"] = list(identifiers)
            item["running"] = True
            item["desired"] = True
            item["mount_mode"] = mode
            item["restart_policy"] = policy
        value.setdefault("events", []).append(f"services:{mode}")
        self._save(value)
        if value.get("fail_phase") == f"{mode}_start":
            raise LifecycleError("injected lab start failure")

    def verify(self, desired: dict[str, list[str]], mode: str) -> None:
        value = self._load()
        if value.get("fail_phase") == f"{mode}_health":
            raise LifecycleError("injected lab health failure")
        current = self.topology(mode, allow_stopped=False)
        if current != desired:
            raise LifecycleBlocked(f"{mode} service topology failed acceptance")

    def clear_failure(self) -> None:
        value = self._load()
        value["fail_phase"] = None
        self._save(value)


class DockerRuntime:
    def __init__(
        self,
        root: Path,
        env_file: Path,
        docker_host: str,
        b2: dict[str, Any],
        pairs: list[dict[str, str]],
    ) -> None:
        self.root = root
        self.dashboard = root / "web-dashboard"
        self.env_file = env_file
        self.docker_host = docker_host
        self.b2 = b2
        self.pairs = pairs
        self.runtime_services, self.initializers = _service_matrix(b2)
        self.mount_matrix = _expected_service_mounts(b2)

    def _docker(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return _run(["docker", "--host", self.docker_host, *args], timeout=timeout)

    def _containers(self) -> list[dict[str, Any]]:
        ids = [
            line
            for line in self._docker(
                [
                    "ps",
                    "-a",
                    "--filter",
                    "label=com.docker.compose.project=web-dashboard",
                    "--format",
                    "{{.ID}}",
                ]
            ).stdout.splitlines()
            if line
        ]
        if not ids:
            return []
        try:
            value = json.loads(self._docker(["inspect", *ids], timeout=120).stdout)
        except json.JSONDecodeError as exc:
            raise LifecycleError("Docker container inspection was not JSON") from exc
        if not isinstance(value, list):
            raise LifecycleError("Docker container inspection shape is invalid")
        return [item for item in value if isinstance(item, dict)]

    def _volume_for(self, root_name: str, mode: str) -> str:
        pair = next(item for item in self.pairs if item["name"] == root_name)
        return pair["legacy_volume"] if mode == "legacy" else pair["candidate_volume"]

    def _verify_container(self, item: dict[str, Any], service: str, mode: str) -> None:
        host = item.get("HostConfig")
        if not isinstance(host, dict):
            raise LifecycleBlocked(f"{service}: Docker host config missing")
        restart = host.get("RestartPolicy")
        policy = restart.get("Name") if isinstance(restart, dict) else None
        wanted_policy = "unless-stopped" if mode == "legacy" else "no"
        if policy != wanted_policy:
            raise LifecycleBlocked(f"{service}: restart policy drifted")
        mounts = item.get("Mounts")
        if not isinstance(mounts, list):
            raise LifecycleBlocked(f"{service}: Docker mounts missing")
        observed = {
            (str(mount.get("Name")), str(mount.get("Destination")), bool(mount.get("RW")))
            for mount in mounts
            if isinstance(mount, dict) and mount.get("Type") == "volume"
        }
        all_protected = {
            value
            for pair in self.pairs
            for value in (pair["legacy_volume"], pair["candidate_volume"])
        }
        observed_protected = {
            item for item in observed if item[0] in all_protected
        }
        expected_protected: set[tuple[str, str, bool]] = set()
        for expected in self.mount_matrix.get(service, []):
            wanted = (
                self._volume_for(expected["root"], mode),
                expected["target"],
                expected["rw"],
            )
            expected_protected.add(wanted)
            if wanted not in observed:
                raise LifecycleBlocked(
                    f"{service}: protected mount drifted for {expected['root']}"
                )
        if observed_protected != expected_protected:
            raise LifecycleBlocked(f"{service}: unexpected protected mount present")

    def topology(self, mode: str, *, allow_stopped: bool = True) -> dict[str, list[str]]:
        active: dict[str, list[str]] = {}
        containers = self._containers()
        for item in containers:
            config = item.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            service = (
                labels.get("com.docker.compose.service")
                if isinstance(labels, dict)
                else None
            )
            if service not in self.runtime_services:
                continue
            state = item.get("State")
            running = isinstance(state, dict) and state.get("Running") is True
            if running:
                self._verify_container(item, str(service), mode)
                identifier = str(item.get("Id", ""))
                if not identifier:
                    raise LifecycleError("Docker container id missing")
                active.setdefault(str(service), []).append(identifier)
        for identifiers in active.values():
            identifiers.sort()
        protected_volumes = {
            value
            for pair in self.pairs
            for value in (pair["legacy_volume"], pair["candidate_volume"])
        }
        for volume in protected_volumes:
            ids = [
                line
                for line in self._docker(
                    ["ps", "-a", "--filter", f"volume={volume}", "--format", "{{.ID}}"]
                ).stdout.splitlines()
                if line
            ]
            if not ids:
                continue
            try:
                attached = json.loads(self._docker(["inspect", *ids]).stdout)
            except json.JSONDecodeError as exc:
                raise LifecycleError("Docker attachment inspection was not JSON") from exc
            for item in attached:
                labels = item.get("Config", {}).get("Labels") or {}
                if (
                    labels.get("com.docker.compose.project") != "web-dashboard"
                    or labels.get("com.docker.compose.service")
                    not in (set(self.runtime_services) | set(self.initializers))
                ):
                    raise LifecycleBlocked("unlisted container uses a protected volume")
        return dict(sorted(active.items()))

    def exact_stop(self, expected: dict[str, list[str]], mode: str) -> None:
        if self.topology(mode) != expected:
            raise LifecycleBlocked("production topology changed after planning")
        identifiers = [identifier for ids in expected.values() for identifier in ids]
        if identifiers:
            self._docker(["stop", "--time", "30", *identifiers], timeout=180)
        self.assert_stopped()

    def stop_mode(self, mode: str) -> None:
        active = self.topology(mode)
        identifiers = [identifier for ids in active.values() for identifier in ids]
        if identifiers:
            self._docker(["stop", "--time", "30", *identifiers], timeout=180)

    def assert_stopped(self) -> None:
        containers = self._containers()
        for item in containers:
            labels = item.get("Config", {}).get("Labels") or {}
            service = labels.get("com.docker.compose.service")
            state = item.get("State") or {}
            if service in self.runtime_services and state.get("Running") is True:
                raise LifecycleBlocked(f"{service}: protected container remains running")
        if self.topology("legacy") or self.topology("candidate"):
            raise LifecycleBlocked("a protected runtime container remains active")

    def _compose_prefix(self, mode: str) -> list[str]:
        files = [self.dashboard / "docker-compose.production.yml"]
        if mode == "candidate":
            files += [
                self.dashboard / "docker-compose.fr06-assets.yml",
                self.dashboard / "docker-compose.fr06-admission.yml",
            ]
        result = [
            "compose",
            "--project-directory",
            str(self.dashboard),
            "--env-file",
            str(self.env_file),
            "--profile",
            "*",
        ]
        for path in files:
            result += ["-f", str(path)]
        return result

    def start_initializers(self, mode: str) -> None:
        prefix = self._compose_prefix(mode)
        for service in self.initializers:
            self._docker(
                [
                    *prefix,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--pull",
                    "never",
                    service,
                ],
                timeout=300,
            )

    def start_services(self, desired: dict[str, list[str]], mode: str) -> None:
        services = sorted(desired)
        if not services:
            raise LifecycleBlocked("no protected runtime service was selected")
        scales: list[str] = []
        for service in services:
            scales += ["--scale", f"{service}={len(desired[service])}"]
        self._docker(
            [
                *self._compose_prefix(mode),
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "300",
                *scales,
                *services,
            ],
            timeout=600,
        )

    def verify(self, desired: dict[str, list[str]], mode: str) -> None:
        current = self.topology(mode, allow_stopped=False)
        if {key: len(value) for key, value in current.items()} != {
            key: len(value) for key, value in desired.items()
        }:
            raise LifecycleBlocked(f"{mode} service scale failed acceptance")
        containers = self._containers()
        for item in containers:
            labels = item.get("Config", {}).get("Labels") or {}
            service = labels.get("com.docker.compose.service")
            if service not in desired:
                continue
            state = item.get("State") or {}
            if state.get("Running") is not True:
                raise LifecycleBlocked(f"{service}: container is not running")
            health = state.get("Health")
            if isinstance(health, dict) and health.get("Status") != "healthy":
                raise LifecycleBlocked(f"{service}: container is not healthy")

    def clear_failure(self) -> None:
        return


def _runtime_and_pairs(
    root: Path,
    env_file: Path,
    docker_host: str,
    b2: dict[str, Any],
    snapshot: dict[str, Any],
    environment: str,
    layout: dict[str, Any] | None,
    sandbox: Path | None,
):
    runtime_services, initializers = _service_matrix(b2)
    if environment == "production":
        pairs = _production_pairs(b2, snapshot, docker_host)
        return (
            DockerRuntime(root, env_file, docker_host, b2, pairs),
            pairs,
        )
    if layout is None or sandbox is None:
        raise LifecycleError("lab layout was not retained")
    pairs = _lab_pairs(b2, layout, sandbox)
    runtime_state = layout.get("runtime_state")
    if not isinstance(runtime_state, str) or not SAFE_PATH_RE.fullmatch(runtime_state):
        raise LifecycleBlocked("lab runtime state path is invalid")
    state_path = Path(runtime_state).resolve(strict=True)
    if not _is_within(state_path, sandbox):
        raise LifecycleBlocked("lab runtime state escaped the sandbox")
    _ensure_regular_private_input(state_path, "lab runtime state")
    return LabRuntime(state_path, runtime_services, initializers), pairs


def _git_acceptance(root: Path, evidence: dict[str, Any], environment: str) -> str:
    source = evidence.get("source")
    if not isinstance(source, dict):
        raise LifecycleError("source evidence is missing")
    if environment == "isolated_lab":
        sha = source.get("lab_commit_sha")
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise LifecycleBlocked("lab source commit is invalid")
        return sha
    sha = source.get("merge_sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise LifecycleBlocked("production merge commit is invalid")
    heads = _run(["git", "rev-parse", "HEAD", "origin/main"], cwd=root).stdout.splitlines()
    if heads != [sha, sha]:
        raise LifecycleBlocked("production checkout and origin/main must equal merge SHA")
    status = _run(["git", "status", "--porcelain=v1"], cwd=root).stdout
    if status.strip():
        raise LifecycleBlocked("production source tree is not clean")
    return sha


def _plan_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "plan_id"}


def _validate_plan_digest(plan: dict[str, Any]) -> None:
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or len(plan_id) != 64:
        raise LifecycleError("plan id is invalid")
    if _digest(_plan_body(plan)) != plan_id:
        raise LifecycleBlocked("plan digest mismatch")


def create_cutover_plan(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    evidence_path = args.evidence.resolve()
    snapshot_path = args.snapshot.resolve()
    _ensure_regular_private_input(evidence_path, "evidence")
    _ensure_regular_private_input(snapshot_path, "snapshot")
    evidence = _json_object(evidence_path)
    snapshot = _json_object(snapshot_path)
    if snapshot.get("docker_host") != args.docker_host:
        raise LifecycleBlocked("Docker socket differs from the admitted snapshot")
    layout = _json_object(args.lab_layout.resolve()) if args.lab_layout else None
    environment, sandbox = _validate_environment(
        root,
        args.state_dir,
        args.env_file,
        args.docker_host,
        evidence,
        layout,
        args.allow_isolated_lab,
    )
    state_dir = _secure_state_dir(args.state_dir, environment, sandbox)
    if not 1 <= args.ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise LifecycleBlocked("plan TTL is outside the bounded range")
    now = _utc_now()
    _validate_window(evidence, environment, now)
    _evaluate_admission(
        root,
        evidence,
        snapshot,
        allow_isolated_lab=args.allow_isolated_lab,
        max_age_seconds=args.max_age_seconds,
    )
    snapshot = _fresh_admitted_snapshot(
        root,
        evidence,
        snapshot,
        args.env_file.resolve(),
        args.docker_host,
        args.max_age_seconds,
    )
    b2, _ = _load_contracts(root)
    runtime, pairs = _runtime_and_pairs(
        root,
        args.env_file.resolve(),
        args.docker_host,
        b2,
        snapshot,
        environment,
        layout,
        sandbox,
    )
    active = runtime.topology("legacy")
    if not active:
        raise LifecycleBlocked("no protected runtime services are active")
    source_commit = _git_acceptance(root, evidence, environment)
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "subpart": SUBPART,
        "operation": "cutover",
        "environment": environment,
        "nonce": secrets.token_hex(32),
        "created_at": _utc_text(now),
        "expires_at": _utc_text(now + timedelta(seconds=args.ttl_seconds)),
        "source_commit": source_commit,
        "evidence_sha256": _file_digest(evidence_path),
        "snapshot_sha256": _file_digest(snapshot_path),
        "contract_sha256": _file_digest(
            root
            / "docs"
            / "project"
            / "receipts"
            / "FR-06B3B-guarded-lifecycle-contract.json"
        ),
        "docker_host": args.docker_host,
        "env_file": str(args.env_file.resolve()),
        "state_dir": str(state_dir),
        "roots": pairs,
        "active_instances": active,
        "service_count": len(active),
        "instance_count": sum(len(value) for value in active.values()),
        "admission_will_remain_closed": True,
        "cloudflare_change_permitted": False,
        "vault_unlock_or_creation_permitted": False,
        "legacy_deletion_permitted": False,
    }
    body["plan_id"] = _digest(body)
    plan_path = state_dir / "plans" / f"{body['plan_id']}.json"
    _write_json_exclusive(plan_path, body)
    return {
        "schema_version": SCHEMA_VERSION,
        "subpart": SUBPART,
        "decision": "cutover_plan_ready",
        "plan_id": body["plan_id"],
        "plan": str(plan_path),
        "expires_at": body["expires_at"],
        "production_executed": False,
    }


def _load_bound_plan(
    plan_path: Path,
    evidence_path: Path,
    snapshot_path: Path,
    now: datetime,
) -> dict[str, Any]:
    _ensure_regular_private_input(plan_path, "plan")
    plan = _json_object(plan_path)
    _validate_plan_digest(plan)
    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("subpart") != SUBPART:
        raise LifecycleError("plan schema or subpart is invalid")
    if plan.get("operation") != "cutover":
        raise LifecycleBlocked("only a cutover plan can be applied")
    if _parse_time(plan.get("created_at"), "plan.created_at") > now + timedelta(minutes=5):
        raise LifecycleBlocked("plan was created in the future")
    if now > _parse_time(plan.get("expires_at"), "plan.expires_at"):
        raise LifecycleBlocked("plan expired")
    if plan.get("evidence_sha256") != _file_digest(evidence_path):
        raise LifecycleBlocked("evidence changed after planning")
    if plan.get("snapshot_sha256") != _file_digest(snapshot_path):
        raise LifecycleBlocked("snapshot changed after planning")
    return plan


def _lock(state_dir: Path):
    path = state_dir / ".lifecycle.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        raise LifecycleBlocked("another FR-06B3B operation holds the lock") from exc
    return descriptor


def _reserve_once(state_dir: Path, operation_id: str, operation: str) -> Path:
    path = state_dir / "reservations" / f"{operation_id}.json"
    _write_json_exclusive(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "operation_id": operation_id,
            "operation": operation,
            "reserved_at": _utc_text(),
            "single_use": True,
        },
    )
    return path


def _writable_fds(roots: Iterable[Path]) -> list[dict[str, Any]]:
    resolved = [path.resolve(strict=True) for path in roots]
    found: list[dict[str, Any]] = []
    proc = Path("/proc")
    for process in proc.iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        fd_dir = process / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for descriptor in descriptors:
            try:
                target_text = os.readlink(descriptor)
            except OSError:
                continue
            if target_text.endswith(" (deleted)"):
                target_text = target_text[:-10]
            if not target_text.startswith("/"):
                continue
            target = Path(target_text)
            if not any(_is_within(target, root) for root in resolved):
                continue
            try:
                lines = (process / "fdinfo" / descriptor.name).read_text(
                    encoding="utf-8"
                ).splitlines()
            except OSError:
                continue
            flag_line = next((line for line in lines if line.startswith("flags:")), None)
            if flag_line is None:
                continue
            try:
                flags = int(flag_line.split()[1], 8)
            except (IndexError, ValueError):
                continue
            if flags & os.O_ACCMODE != os.O_RDONLY:
                found.append({"pid": int(process.name), "fd": int(descriptor.name)})
    return sorted(found, key=lambda item: (item["pid"], item["fd"]))


def _assert_quiescent(runtime: LabRuntime | DockerRuntime, roots: Iterable[Path]) -> None:
    runtime.assert_stopped()
    if isinstance(runtime, DockerRuntime):
        writers = _writable_fds(roots)
        if writers:
            raise LifecycleBlocked(
                f"unlisted writable descriptors remain: {len(writers)}"
            )


def _manifest_module(root: Path):
    return _load_module(
        root / "scripts" / "security" / "fr06b_asset_copy_manifest.py",
        f"fr06b_manifest_{secrets.token_hex(4)}",
    )


def _store_manifest(path: Path, manifest: dict[str, Any]) -> None:
    _write_json_exclusive(path, manifest)


def _stable_delta(
    root: Path,
    pairs: list[dict[str, str]],
    evidence_dir: Path,
    *,
    reverse: bool,
) -> list[dict[str, Any]]:
    manifest = _manifest_module(root)
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    results: list[dict[str, Any]] = []
    for pair in pairs:
        source = Path(pair["target"] if reverse else pair["source"])
        target = Path(pair["source"] if reverse else pair["target"])
        label = pair["name"]
        before = manifest.build_manifest(source)
        _store_manifest(evidence_dir / f"{label}.source-before.json", before)
        _run(
            [
                "rsync",
                "-a",
                "--numeric-ids",
                "--delete",
                "--safe-links",
                "--no-devices",
                "--no-specials",
                "--",
                f"{source}/",
                f"{target}/",
            ],
            timeout=3600,
        )
        os.sync()
        after = manifest.build_manifest(source)
        candidate = manifest.build_manifest(target)
        _store_manifest(evidence_dir / f"{label}.source-after.json", after)
        _store_manifest(evidence_dir / f"{label}.target.json", candidate)
        if before.get("entries") != after.get("entries"):
            raise LifecycleBlocked(f"{label}: source changed during final delta")
        if after.get("entries") != candidate.get("entries"):
            raise LifecycleBlocked(f"{label}: final delta manifest mismatch")
        summary = candidate.get("summary")
        if not isinstance(summary, dict):
            raise LifecycleError(f"{label}: manifest summary missing")
        results.append(
            {
                "root": label,
                "vault": pair["vault"],
                "directories": int(summary["directories"]),
                "regular_files": int(summary["regular_files"]),
                "payload_bytes": int(summary["payload_bytes"]),
                "aggregate_sha256": str(summary["aggregate_sha256"]),
            }
        )
    return results


def _verify_exact_pairs(
    root: Path,
    pairs: list[dict[str, str]],
    evidence_dir: Path,
) -> list[dict[str, Any]]:
    manifest = _manifest_module(root)
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    results: list[dict[str, Any]] = []
    for pair in pairs:
        source = manifest.build_manifest(Path(pair["source"]))
        target = manifest.build_manifest(Path(pair["target"]))
        label = pair["name"]
        _store_manifest(evidence_dir / f"{label}.sealed-source.json", source)
        _store_manifest(evidence_dir / f"{label}.post-initializer-target.json", target)
        if source.get("entries") != target.get("entries"):
            raise LifecycleBlocked(
                f"{label}: initializer changed candidate manifest after final delta"
            )
        summary = target.get("summary")
        if not isinstance(summary, dict):
            raise LifecycleError(f"{label}: post-initializer summary missing")
        results.append(
            {
                "root": label,
                "directories": int(summary["directories"]),
                "regular_files": int(summary["regular_files"]),
                "payload_bytes": int(summary["payload_bytes"]),
                "aggregate_sha256": str(summary["aggregate_sha256"]),
            }
        )
    return results


def _validate_legacy_baseline(
    root: Path,
    pairs: list[dict[str, str]],
    baseline: Any,
    evidence_dir: Path,
) -> list[dict[str, Any]]:
    if not isinstance(baseline, list) or len(baseline) != len(pairs):
        raise LifecycleBlocked("cutover receipt legacy baseline is incomplete")
    fields = (
        "root",
        "vault",
        "directories",
        "regular_files",
        "payload_bytes",
        "aggregate_sha256",
    )
    expected: dict[str, dict[str, Any]] = {}
    for item in baseline:
        if not isinstance(item, dict):
            raise LifecycleBlocked("cutover receipt legacy baseline is malformed")
        label = item.get("root")
        if not isinstance(label, str) or label in expected:
            raise LifecycleBlocked("cutover receipt legacy baseline roots are invalid")
        expected[label] = {field: item.get(field) for field in fields}
    labels = [pair["name"] for pair in pairs]
    if set(expected) != set(labels):
        raise LifecycleBlocked("cutover receipt legacy baseline root set drifted")

    manifest = _manifest_module(root)
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    results: list[dict[str, Any]] = []
    for pair in pairs:
        label = pair["name"]
        current = manifest.build_manifest(Path(pair["source"]))
        _store_manifest(evidence_dir / f"{label}.legacy-after-reseal.json", current)
        summary = current.get("summary")
        if not isinstance(summary, dict):
            raise LifecycleError(f"{label}: legacy baseline summary missing")
        observed = {
            "root": label,
            "vault": pair["vault"],
            "directories": int(summary["directories"]),
            "regular_files": int(summary["regular_files"]),
            "payload_bytes": int(summary["payload_bytes"]),
            "aggregate_sha256": str(summary["aggregate_sha256"]),
        }
        if observed != expected[label]:
            raise LifecycleBlocked(
                f"{label}: legacy root changed while reboot seals were absent"
            )
        results.append(observed)
    return results


def _mountpoint(path: Path) -> bool:
    return (
        _run(["mountpoint", "-q", str(path)], allowed={0, 1, 32}).returncode == 0
    )


def _seal_sources(pairs: list[dict[str, str]]) -> list[str]:
    sources = [Path(pair["source"]) for pair in pairs]
    sealed: list[Path] = []
    try:
        for source in sources:
            if _mountpoint(source):
                raise LifecycleBlocked(f"legacy root already has a mount: {source.name}")
            _run(["mount", "--bind", str(source), str(source)])
            sealed.append(source)
            try:
                _run(
                    [
                        "mount",
                        "-o",
                        "remount,bind,ro,nodev,nosuid",
                        str(source),
                    ]
                )
            except Exception:
                _run(["umount", str(source)], allowed={0, 32})
                raise
            options = set(
                _run(
                    ["findmnt", "-n", "-o", "OPTIONS", "--target", str(source)]
                ).stdout.strip().split(",")
            )
            if "ro" not in options or "rw" in options:
                raise LifecycleBlocked(f"legacy root did not become read-only: {source.name}")
    except BaseException:
        _unseal_sources([str(path) for path in sealed], tolerate=True)
        raise
    return [str(path) for path in sealed]


def _unseal_sources(paths: list[str], *, tolerate: bool = False) -> None:
    failures: list[str] = []
    for raw in reversed(paths):
        path = Path(raw)
        result = _run(["umount", str(path)], allowed={0, 32})
        if result.returncode != 0 and _mountpoint(path):
            failures.append(path.name)
    if failures and not tolerate:
        raise LifecycleError(
            f"failed to unseal legacy roots: {','.join(sorted(failures))}"
        )


def _sealed(paths: list[str]) -> bool:
    for raw in paths:
        path = Path(raw)
        if not _mountpoint(path):
            return False
        options = set(
            _run(["findmnt", "-n", "-o", "OPTIONS", "--target", raw]).stdout.strip().split(
                ","
            )
        )
        if "ro" not in options or "rw" in options:
            return False
    return True


def _receipt(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    result["receipt_sha256"] = _digest(result)
    return result


def _validate_receipt(value: dict[str, Any]) -> None:
    supplied = value.get("receipt_sha256")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not isinstance(supplied, str) or supplied != _digest(body):
        raise LifecycleBlocked("receipt digest mismatch")


def _record_result(
    state_dir: Path,
    operation_id: str,
    body: dict[str, Any],
) -> Path:
    value = _receipt(body)
    path = state_dir / "results" / f"{operation_id}.json"
    _write_json_exclusive(path, value)
    return path


def _bind_inputs(
    args: argparse.Namespace,
    *,
    require_plan: bool,
) -> tuple[
    Path,
    Path,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
    str,
    Path | None,
    Path,
]:
    root = args.root.resolve()
    evidence_path = args.evidence.resolve()
    snapshot_path = args.snapshot.resolve()
    _ensure_regular_private_input(evidence_path, "evidence")
    _ensure_regular_private_input(snapshot_path, "snapshot")
    evidence = _json_object(evidence_path)
    snapshot = _json_object(snapshot_path)
    if snapshot.get("docker_host") != args.docker_host:
        raise LifecycleBlocked("Docker socket differs from the admitted snapshot")
    layout = _json_object(args.lab_layout.resolve()) if args.lab_layout else None
    environment, sandbox = _validate_environment(
        root,
        args.state_dir,
        args.env_file,
        args.docker_host,
        evidence,
        layout,
        args.allow_isolated_lab,
    )
    state_dir = _secure_state_dir(args.state_dir, environment, sandbox)
    _validate_window(evidence, environment, _utc_now())
    _evaluate_admission(
        root,
        evidence,
        snapshot,
        allow_isolated_lab=args.allow_isolated_lab,
        max_age_seconds=args.max_age_seconds,
    )
    snapshot = _fresh_admitted_snapshot(
        root,
        evidence,
        snapshot,
        args.env_file.resolve(),
        args.docker_host,
        args.max_age_seconds,
    )
    if require_plan and not hasattr(args, "plan"):
        raise LifecycleError("plan is required")
    return (
        root,
        evidence_path,
        evidence,
        snapshot,
        layout,
        environment,
        sandbox,
        state_dir,
    )


def apply_cutover(args: argparse.Namespace) -> dict[str, Any]:
    (
        root,
        evidence_path,
        evidence,
        snapshot,
        layout,
        environment,
        sandbox,
        state_dir,
    ) = _bind_inputs(args, require_plan=True)
    snapshot_path = args.snapshot.resolve()
    now = _utc_now()
    plan = _load_bound_plan(args.plan.resolve(), evidence_path, snapshot_path, now)
    if plan.get("environment") != environment or plan.get("state_dir") != str(state_dir):
        raise LifecycleBlocked("plan environment or state directory drifted")
    if args.plan.resolve().parent != state_dir / "plans":
        raise LifecycleBlocked("plan must remain in its private state directory")
    if plan.get("docker_host") != args.docker_host or plan.get("env_file") != str(args.env_file.resolve()):
        raise LifecycleBlocked("plan Docker socket or environment file drifted")
    expected_confirmation = f"EXECUTE_FR06B3B_CUTOVER:{plan['plan_id']}"
    if args.confirmation != expected_confirmation:
        raise LifecycleBlocked("exact cutover confirmation is required")
    if environment == "production" and args.confirm_production != "FR06B3B_PRODUCTION_CUTOVER":
        raise LifecycleBlocked("second production confirmation is required")
    if plan.get("contract_sha256") != _file_digest(
        root
        / "docs"
        / "project"
        / "receipts"
        / "FR-06B3B-guarded-lifecycle-contract.json"
    ):
        raise LifecycleBlocked("executor contract changed after planning")
    b2, _ = _load_contracts(root)
    runtime, pairs = _runtime_and_pairs(
        root,
        args.env_file.resolve(),
        args.docker_host,
        b2,
        snapshot,
        environment,
        layout,
        sandbox,
    )
    if pairs != plan.get("roots"):
        raise LifecycleBlocked("root layout changed after planning")
    active = plan.get("active_instances")
    if not isinstance(active, dict) or runtime.topology("legacy") != active:
        raise LifecycleBlocked("runtime topology changed after planning")
    if _git_acceptance(root, evidence, environment) != plan.get("source_commit"):
        raise LifecycleBlocked("source commit changed after planning")

    lock_fd = _lock(state_dir)
    operation_id = str(plan["plan_id"])
    journal = state_dir / "journals" / f"{operation_id}.jsonl"
    sealed: list[str] = []
    candidate_runtime_attempted = False
    forward_summary: list[dict[str, Any]] = []
    post_initializer_summary: list[dict[str, Any]] = []
    _reserve_once(state_dir, operation_id, "cutover")
    try:
        _append_event(
            journal,
            {
                "at": _utc_text(),
                "phase": "reserved",
                "environment": environment,
                "admission_closed": True,
            },
        )
        runtime.exact_stop(active, "legacy")
        _assert_quiescent(
            runtime,
            [Path(pair["source"]) for pair in pairs]
            + [Path(pair["target"]) for pair in pairs],
        )
        _append_event(journal, {"at": _utc_text(), "phase": "writers_stopped"})
        sealed = _seal_sources(pairs)
        _append_event(
            journal,
            {
                "at": _utc_text(),
                "phase": "legacy_read_only",
                "root_count": len(sealed),
            },
        )
        forward_summary = _stable_delta(
            root,
            pairs,
            state_dir / "manifests" / operation_id / "forward",
            reverse=False,
        )
        if not _sealed(sealed):
            raise LifecycleBlocked("legacy read-only seal drifted during final delta")
        _append_event(journal, {"at": _utc_text(), "phase": "final_delta_exact"})
        _validate_window(evidence, environment, _utc_now())
        start_snapshot = _fresh_admitted_snapshot(
            root,
            evidence,
            snapshot,
            args.env_file.resolve(),
            args.docker_host,
            args.max_age_seconds,
        )
        _start_runtime, start_pairs = _runtime_and_pairs(
            root,
            args.env_file.resolve(),
            args.docker_host,
            b2,
            start_snapshot,
            environment,
            layout,
            sandbox,
        )
        if start_pairs != pairs:
            raise LifecycleBlocked("root layout changed before candidate start")
        runtime.start_initializers("candidate")
        post_initializer_summary = _verify_exact_pairs(
            root,
            pairs,
            state_dir / "manifests" / operation_id / "post-initializer",
        )
        candidate_runtime_attempted = True
        runtime.start_services(active, "candidate")
        runtime.verify(active, "candidate")
        if not _sealed(sealed):
            raise LifecycleBlocked("legacy read-only seal drifted after candidate start")
        body = {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "operation": "cutover",
            "operation_id": operation_id,
            "environment": environment,
            "status": "candidate_started_admission_closed",
            "completed_at": _utc_text(),
            "source_commit": plan["source_commit"],
            "plan_id": plan["plan_id"],
            "active_instances": active,
            "legacy_read_only_roots": sealed,
            "roots": pairs,
            "final_delta": forward_summary,
            "post_initializer_exact": post_initializer_summary,
            "admission_opened": False,
            "cloudflare_changed": False,
            "vaults_created_or_unlocked": False,
            "legacy_deleted": False,
            "production_execution": environment == "production",
            "live_p95_accepted": False,
            "parent_batch_completed": False,
        }
        _append_event(
            journal,
            {
                "at": _utc_text(),
                "phase": "candidate_started_admission_closed",
                "result_pending": True,
            },
        )
        result_path = _record_result(state_dir, operation_id, body)
        return {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "status": body["status"],
            "operation_id": operation_id,
            "result": str(result_path),
            "admission_opened": False,
            "production_execution": environment == "production",
        }
    except BaseException as original:
        rollback_error: BaseException | None = None
        rollback_kind = (
            "post_candidate_reverse_delta"
            if candidate_runtime_attempted
            else "pre_candidate"
        )
        try:
            runtime.stop_mode("candidate")
            runtime.assert_stopped()
            if sealed:
                _unseal_sources(sealed)
            reverse_summary: list[dict[str, Any]] = []
            if candidate_runtime_attempted:
                _assert_quiescent(runtime, [Path(pair["target"]) for pair in pairs])
                reverse_summary = _stable_delta(
                    root,
                    pairs,
                    state_dir / "manifests" / operation_id / "automatic-reverse",
                    reverse=True,
                )
            runtime.clear_failure()
            runtime.start_initializers("legacy")
            runtime.start_services(active, "legacy")
            runtime.verify(active, "legacy")
            rollback_body = {
                    "schema_version": SCHEMA_VERSION,
                    "subpart": SUBPART,
                    "operation": "cutover",
                    "operation_id": operation_id,
                    "environment": environment,
                    "status": "cutover_failed_automatic_rollback_passed",
                    "completed_at": _utc_text(),
                    "rollback_kind": rollback_kind,
                    "reverse_delta": reverse_summary,
                    "admission_opened": False,
                    "cloudflare_changed": False,
                    "legacy_deleted": False,
                    "production_execution": environment == "production",
                    "parent_batch_completed": False,
                }
            _append_event(
                journal,
                {
                    "at": _utc_text(),
                    "phase": "automatic_rollback_passed",
                    "rollback_kind": rollback_kind,
                    "result_pending": True,
                },
            )
            _record_result(state_dir, operation_id, rollback_body)
        except BaseException as rollback_exc:
            rollback_error = rollback_exc
            _append_event(
                journal,
                {
                    "at": _utc_text(),
                    "phase": "automatic_rollback_failed",
                    "admission_must_remain_closed": True,
                },
            )
        if rollback_error is not None:
            raise LifecycleError(
                "cutover failed and automatic rollback also failed; admission must remain closed"
            ) from rollback_error
        raise LifecycleError(
            "cutover failed; automatic rollback passed and admission remains closed"
        ) from original
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _validate_nonce(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", value):
        raise LifecycleBlocked("operation nonce must be 16-128 safe characters")


def _load_success_receipt(path: Path) -> dict[str, Any]:
    _ensure_regular_private_input(path, "cutover receipt")
    value = _json_object(path)
    _validate_receipt(value)
    if (
        value.get("subpart") != SUBPART
        or value.get("operation") != "cutover"
        or value.get("status") != "candidate_started_admission_closed"
        or value.get("admission_opened") is not False
    ):
        raise LifecycleBlocked("receipt is not a successful closed-admission cutover")
    return value


def guarded_start(args: argparse.Namespace) -> dict[str, Any]:
    (
        root,
        _evidence_path,
        evidence,
        snapshot,
        layout,
        environment,
        sandbox,
        state_dir,
    ) = _bind_inputs(args, require_plan=False)
    prior = _load_success_receipt(args.receipt.resolve())
    if args.receipt.resolve().parent != state_dir / "results":
        raise LifecycleBlocked("cutover receipt must remain in its private state directory")
    if prior.get("environment") != environment:
        raise LifecycleBlocked("receipt environment drifted")
    current_source_commit = _git_acceptance(root, evidence, environment)
    _validate_nonce(args.nonce)
    active_value = prior.get("active_instances")
    sealed = prior.get("legacy_read_only_roots")
    if not isinstance(sealed, list) or len(sealed) != 11:
        raise LifecycleBlocked("guarded start receipt topology is incomplete")
    operation_id = _digest(
        {
            "operation": "guarded_start",
            "receipt": prior["receipt_sha256"],
            "nonce": args.nonce,
        }
    )
    if args.confirmation != f"START_FR06B3B:{operation_id}":
        raise LifecycleBlocked("exact guarded-start confirmation is required")
    if environment == "production" and args.confirm_production != "FR06B3B_PRODUCTION_START":
        raise LifecycleBlocked("second production start confirmation is required")
    b2, _ = _load_contracts(root)
    runtime, pairs = _runtime_and_pairs(
        root,
        args.env_file.resolve(),
        args.docker_host,
        b2,
        snapshot,
        environment,
        layout,
        sandbox,
    )
    active = _validated_active_instances(active_value, runtime.runtime_services)
    if pairs != prior.get("roots"):
        raise LifecycleBlocked("guarded-start root layout differs from the cutover receipt")
    if sealed != [pair["source"] for pair in pairs]:
        raise LifecycleBlocked("guarded-start legacy seal layout differs from bound roots")
    if runtime.topology("candidate"):
        raise LifecycleBlocked("guarded start requires all candidate consumers stopped")
    lock_fd = _lock(state_dir)
    _reserve_once(state_dir, operation_id, "guarded_start")
    journal = state_dir / "journals" / f"{operation_id}.jsonl"
    try:
        protected_roots = [Path(pair["source"]) for pair in pairs] + [
            Path(pair["target"]) for pair in pairs
        ]
        _assert_quiescent(runtime, protected_roots)
        seals_reestablished = False
        legacy_baseline_verified = False
        if not _sealed(sealed):
            _unseal_sources(sealed, tolerate=True)
            restored_seals = _seal_sources(pairs)
            if restored_seals != sealed:
                raise LifecycleBlocked("re-established legacy seal layout drifted")
            _validate_legacy_baseline(
                root,
                pairs,
                prior.get("final_delta"),
                state_dir / "manifests" / operation_id / "legacy-after-reseal",
            )
            seals_reestablished = True
            legacy_baseline_verified = True
            _append_event(
                journal,
                {
                    "at": _utc_text(),
                    "phase": "legacy_seals_reestablished",
                    "root_count": len(restored_seals),
                    "legacy_baseline_verified": True,
                },
            )
        for attempt in range(1, MAX_START_ATTEMPTS + 1):
            attempt_snapshot = _fresh_admitted_snapshot(
                root,
                evidence,
                snapshot,
                args.env_file.resolve(),
                args.docker_host,
                args.max_age_seconds,
            )
            attempt_runtime, attempt_pairs = _runtime_and_pairs(
                root,
                args.env_file.resolve(),
                args.docker_host,
                b2,
                attempt_snapshot,
                environment,
                layout,
                sandbox,
            )
            if attempt_pairs != pairs:
                raise LifecycleBlocked("root layout changed before guarded start")
            _assert_quiescent(attempt_runtime, protected_roots)
            if not _sealed(sealed):
                raise LifecycleBlocked("legacy read-only seal drifted before guarded start")
            _validate_window(evidence, environment, _utc_now())
            try:
                runtime.start_initializers("candidate")
                runtime.start_services(active, "candidate")
                runtime.verify(active, "candidate")
                if not _sealed(sealed):
                    raise LifecycleBlocked("legacy read-only seal drifted")
                result_path = _record_result(
                    state_dir,
                    operation_id,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "subpart": SUBPART,
                        "operation": "guarded_start",
                        "operation_id": operation_id,
                        "environment": environment,
                        "status": "candidate_started_admission_closed",
                        "completed_at": _utc_text(),
                        "attempt": attempt,
                        "source_cutover_receipt": prior["receipt_sha256"],
                        "executor_source_commit": current_source_commit,
                        "legacy_seals_reestablished": seals_reestablished,
                        "legacy_baseline_verified_after_reseal": legacy_baseline_verified,
                        "admission_opened": False,
                        "cloudflare_changed": False,
                        "production_execution": environment == "production",
                        "parent_batch_completed": False,
                    },
                )
                return {
                    "schema_version": SCHEMA_VERSION,
                    "subpart": SUBPART,
                    "status": "candidate_started_admission_closed",
                    "attempt": attempt,
                    "result": str(result_path),
                    "admission_opened": False,
                }
            except BaseException as start_error:
                runtime.stop_mode("candidate")
                runtime.assert_stopped()
                _append_event(
                    journal,
                    {
                        "at": _utc_text(),
                        "phase": "start_attempt_failed",
                        "attempt": attempt,
                    },
                )
                if not isinstance(start_error, Exception):
                    raise LifecycleError(
                        "guarded start interrupted; candidates stopped and admission remains closed"
                    ) from start_error
                if attempt == MAX_START_ATTEMPTS:
                    raise LifecycleError(
                        "bounded guarded start exhausted; admission remains closed"
                    ) from start_error
                if environment == "production":
                    time.sleep(5 * attempt)
        raise LifecycleError("unreachable guarded-start state")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def rollback_cutover(args: argparse.Namespace) -> dict[str, Any]:
    (
        root,
        _evidence_path,
        evidence,
        snapshot,
        layout,
        environment,
        sandbox,
        state_dir,
    ) = _bind_inputs(args, require_plan=False)
    prior = _load_success_receipt(args.receipt.resolve())
    if args.receipt.resolve().parent != state_dir / "results":
        raise LifecycleBlocked("cutover receipt must remain in its private state directory")
    if prior.get("environment") != environment:
        raise LifecycleBlocked("receipt environment drifted")
    current_source_commit = _git_acceptance(root, evidence, environment)
    _validate_nonce(args.nonce)
    active_value = prior.get("active_instances")
    sealed = prior.get("legacy_read_only_roots")
    if not isinstance(sealed, list) or len(sealed) != 11:
        raise LifecycleBlocked("rollback receipt topology is incomplete")
    operation_id = _digest(
        {
            "operation": "rollback",
            "receipt": prior["receipt_sha256"],
            "nonce": args.nonce,
        }
    )
    if args.confirmation != f"ROLLBACK_FR06B3B:{operation_id}":
        raise LifecycleBlocked("exact rollback confirmation is required")
    if environment == "production" and args.confirm_production != "FR06B3B_PRODUCTION_ROLLBACK":
        raise LifecycleBlocked("second production rollback confirmation is required")
    b2, _ = _load_contracts(root)
    runtime, pairs = _runtime_and_pairs(
        root,
        args.env_file.resolve(),
        args.docker_host,
        b2,
        snapshot,
        environment,
        layout,
        sandbox,
    )
    active = _validated_active_instances(active_value, runtime.runtime_services)
    if pairs != prior.get("roots"):
        raise LifecycleBlocked("rollback root layout differs from the cutover receipt")
    if sealed != [pair["source"] for pair in pairs]:
        raise LifecycleBlocked("rollback legacy seal layout differs from bound roots")
    if runtime.topology("candidate"):
        raise LifecycleBlocked(
            "candidate services must be stopped before the fresh rollback preflight"
        )
    lock_fd = _lock(state_dir)
    _reserve_once(state_dir, operation_id, "rollback")
    journal = state_dir / "journals" / f"{operation_id}.jsonl"
    try:
        _assert_quiescent(
            runtime,
            [Path(pair["source"]) for pair in pairs]
            + [Path(pair["target"]) for pair in pairs],
        )
        _unseal_sources(sealed, tolerate=True)
        if any(_mountpoint(Path(path)) for path in sealed):
            raise LifecycleBlocked("legacy root remained sealed before reverse delta")
        reverse = _stable_delta(
            root,
            pairs,
            state_dir / "manifests" / operation_id / "manual-reverse",
            reverse=True,
        )
        runtime.start_initializers("legacy")
        runtime.start_services(active, "legacy")
        runtime.verify(active, "legacy")
        rollback_body = {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "operation": "rollback",
            "operation_id": operation_id,
            "environment": environment,
            "status": "legacy_restored_admission_closed",
            "completed_at": _utc_text(),
            "source_cutover_receipt": prior["receipt_sha256"],
            "executor_source_commit": current_source_commit,
            "reverse_delta": reverse,
            "admission_opened": False,
            "cloudflare_changed": False,
            "candidate_deleted": False,
            "production_execution": environment == "production",
            "parent_batch_completed": False,
        }
        _append_event(
            journal,
            {
                "at": _utc_text(),
                "phase": "legacy_restored_admission_closed",
                "result_pending": True,
            },
        )
        result_path = _record_result(state_dir, operation_id, rollback_body)
        return {
            "schema_version": SCHEMA_VERSION,
            "subpart": SUBPART,
            "status": "legacy_restored_admission_closed",
            "result": str(result_path),
            "admission_opened": False,
        }
    except BaseException as exc:
        _append_event(
            journal,
            {
                "at": _utc_text(),
                "phase": "rollback_failed",
                "admission_must_remain_closed": True,
            },
        )
        raise LifecycleError(
            "rollback failed; admission must remain closed for manual recovery"
        ) from exc
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--docker-host", required=True)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    parser.add_argument("--allow-isolated-lab", action="store_true")
    parser.add_argument("--lab-layout", type=Path)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan-cutover")
    _common(plan)
    plan.add_argument("--ttl-seconds", type=int, default=600)

    apply = commands.add_parser("apply-cutover")
    _common(apply)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--confirmation", required=True)
    apply.add_argument("--confirm-production", default="")

    start = commands.add_parser("guarded-start")
    _common(start)
    start.add_argument("--receipt", type=Path, required=True)
    start.add_argument("--nonce", required=True)
    start.add_argument("--confirmation", required=True)
    start.add_argument("--confirm-production", default="")

    rollback = commands.add_parser("rollback")
    _common(rollback)
    rollback.add_argument("--receipt", type=Path, required=True)
    rollback.add_argument("--nonce", required=True)
    rollback.add_argument("--confirmation", required=True)
    rollback.add_argument("--confirm-production", default="")

    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.max_age_seconds < 1 or args.max_age_seconds > 3600:
            raise LifecycleBlocked("max evidence age is outside the bounded range")
        if args.command == "plan-cutover":
            result = create_cutover_plan(args)
        elif args.command == "apply-cutover":
            result = apply_cutover(args)
        elif args.command == "guarded-start":
            result = guarded_start(args)
        else:
            result = rollback_cutover(args)
    except LifecycleBlocked as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "subpart": SUBPART,
                    "decision": "blocked",
                    "production_authorized": False,
                    "admission_opened": False,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    except (LifecycleError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"FR06B3B_LIFECYCLE_ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
