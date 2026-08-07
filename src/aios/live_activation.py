from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from shutil import which
from typing import Iterable, Mapping
import json
import os

from .providers.tool_catalog import THREE_D_PROVIDER_RECORDS, ToolActivation, local_tool_catalog, provider_activation


@dataclass(frozen=True, slots=True)
class ActivationRecord:
    surface_id: str
    category: str
    status: str
    reason: str
    evidence: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ActivationSnapshot:
    version: int
    workers: tuple[ActivationRecord, ...]
    tools: tuple[ActivationRecord, ...]
    providers: tuple[ActivationRecord, ...]
    integrations: tuple[ActivationRecord, ...]

    @property
    def ready(self) -> bool:
        required = (*self.workers, *self.tools, *self.providers, *self.integrations)
        return all(item.status in {"ready", "unconfigured", "unavailable"} for item in required)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


WORKER_HEALTH_ENV = {
    "backup-worker": "BACKUP_WORKER_HEALTH_FILE",
    "communication-worker": "COMMUNICATION_WORKER_HEALTH_FILE",
    "operations-observer": "OPERATIONS_OBSERVER_HEALTH_FILE",
    "studio-worker": "STUDIO_WORKER_HEALTH_FILE",
    "project-worker": "PROJECT_WORKER_HEALTH_FILE",
    "telegram-worker": "AIOS_TELEGRAM_HEALTH_FILE",
}


def worker_records(*, running_services: Iterable[str], health_files: Mapping[str, str | None] | None = None) -> tuple[ActivationRecord, ...]:
    running = set(running_services)
    health_files = dict(health_files or {})
    records: list[ActivationRecord] = []
    for worker, env_name in WORKER_HEALTH_ENV.items():
        path = health_files.get(worker) or os.environ.get(env_name)
        if worker == "telegram-worker" and worker not in running:
            token_file = os.environ.get("AIOS_TELEGRAM_BOT_TOKEN_FILE")
            configured = bool(token_file and Path(token_file).is_file())
            records.append(ActivationRecord(worker, "worker", "unconfigured" if not configured else "unavailable", "Telegram worker is an explicit optional profile and requires a configured bot token before it may run." if not configured else "Telegram credential exists but worker profile is not running.", {"running": False, "credential_configured": configured}))
            continue
        if worker not in running:
            records.append(ActivationRecord(worker, "worker", "unavailable", "Required production worker is not running.", {"running": False}))
            continue
        evidence: dict[str, object] = {"running": True}
        if path:
            evidence["health_file"] = path
            evidence["health_file_exists"] = Path(path).is_file()
        records.append(ActivationRecord(worker, "worker", "ready", "Production worker is running; container health remains the deployment source of truth.", evidence))
    return tuple(records)


def tool_records(executable_overrides: Mapping[str, str] | None = None) -> tuple[ActivationRecord, ...]:
    return tuple(
        ActivationRecord(tool.tool_id, tool.category, tool.activation.value, tool.reason, {"local": tool.local, "executable": tool.executable or ""})
        for tool in local_tool_catalog(executable_overrides)
    )


def provider_records(configured_env: Iterable[str]) -> tuple[ActivationRecord, ...]:
    env = frozenset(configured_env)
    return tuple(
        ActivationRecord(record.provider_id, record.category, record.activation.value, record.reason, {"credential_env": record.credential_env or ""})
        for record in (provider_activation(item.provider_id, env) for item in THREE_D_PROVIDER_RECORDS)
    )


def integration_records() -> tuple[ActivationRecord, ...]:
    commands = {
        "git": "git",
        "github": "gh",
        "docker": "docker",
        "node": "node",
        "npm": "npm",
        "python": "python3",
        "kubernetes": "kubectl",
        "helm": "helm",
    }
    rows: list[ActivationRecord] = []
    for integration, executable in commands.items():
        path = which(executable)
        optional = integration in {"kubernetes", "helm"}
        status = "ready" if path else ("unconfigured" if optional else "unavailable")
        reason = "Executable discovered on runtime host." if path else ("Optional integration is not configured on this runtime host." if optional else "Required executable is unavailable on runtime host.")
        rows.append(ActivationRecord(integration, "runtime-integration", status, reason, {"executable": path or ""}))
    return tuple(rows)


def build_activation_snapshot(*, running_services: Iterable[str], configured_env: Iterable[str], executable_overrides: Mapping[str, str] | None = None) -> ActivationSnapshot:
    return ActivationSnapshot(
        1,
        worker_records(running_services=running_services),
        tool_records(executable_overrides),
        provider_records(configured_env),
        integration_records(),
    )
