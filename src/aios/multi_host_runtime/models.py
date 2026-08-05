from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class HostState(StrEnum):
    ENROLLED = "enrolled"
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class HostRecord:
    host_id: str
    service_url: str
    capabilities: tuple[str, ...]
    certificate_sha256: str
    state: HostState
    heartbeat_at: float | None
    enrolled_at: float
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HostLeaderLease:
    cluster_id: str
    host_id: str
    term: int
    fencing_token: str
    acquired_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class MultiHostCycleResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    tasks_total: int
    tasks_succeeded: int
    tasks_dead_lettered: int
    recovered_tasks: int
    leaders_observed: tuple[str, ...]
    hosts_used: tuple[str, ...]
    total_duration: float
