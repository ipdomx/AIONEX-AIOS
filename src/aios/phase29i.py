"""Phase 29I production closure contracts.

Provider/model activation is intentionally excluded and remains Phase 29J.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
from urllib.parse import urlparse


class Lifecycle(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PUBLISHED = "published"
    ACTIVE = "active"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: str
    actor: str
    subject: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PluginVersion:
    plugin_id: str
    owner_id: str
    version: str
    checksum: str
    signature: str
    permissions: frozenset[str]
    compatibility: str
    artifact_uri: str
    state: Lifecycle = Lifecycle.SUBMITTED


@dataclass(slots=True)
class Installation:
    installation_id: str
    organization_id: str
    plugin_id: str
    version: str
    state: Lifecycle = Lifecycle.ACTIVE
    previous_version: str | None = None


class PluginLifecycleService:
    """Audited plugin review/install/update/disable/uninstall/rollback service."""
    def __init__(self, *, signing_key: bytes, allowed_permissions: set[str], platform_version: str) -> None:
        if len(signing_key) < 16:
            raise ValueError("signing key is too short")
        self._key = signing_key
        self._allowed = set(allowed_permissions)
        self.platform_version = platform_version
        self.versions: dict[tuple[str, str], PluginVersion] = {}
        self.installations: dict[str, Installation] = {}
        self.audit: list[AuditEvent] = []

    def expected_signature(self, plugin_id: str, version: str, checksum: str) -> str:
        return hmac.new(self._key, f"{plugin_id}:{version}:{checksum}".encode(), hashlib.sha256).hexdigest()

    def submit(self, item: PluginVersion, actor: str) -> PluginVersion:
        key = (item.plugin_id, item.version)
        if key in self.versions:
            raise ValueError("plugin version already exists")
        if not item.permissions.issubset(self._allowed):
            raise PermissionError("plugin requests unsupported permissions")
        if not hmac.compare_digest(item.signature, self.expected_signature(item.plugin_id, item.version, item.checksum)):
            raise PermissionError("plugin signature verification failed")
        self.versions[key] = item
        self.audit.append(AuditEvent("plugin.submit", actor, f"{item.plugin_id}@{item.version}"))
        return item

    def approve(self, plugin_id: str, version: str, actor: str) -> PluginVersion:
        item = self.versions[(plugin_id, version)]
        item.state = Lifecycle.APPROVED
        self.audit.append(AuditEvent("plugin.approve", actor, f"{plugin_id}@{version}"))
        return item

    def publish(self, plugin_id: str, version: str, actor: str) -> PluginVersion:
        item = self.versions[(plugin_id, version)]
        if item.state is not Lifecycle.APPROVED:
            raise RuntimeError("plugin version requires review approval")
        item.state = Lifecycle.PUBLISHED
        self.audit.append(AuditEvent("plugin.publish", actor, f"{plugin_id}@{version}"))
        return item

    def install(self, installation_id: str, organization_id: str, plugin_id: str, version: str, actor: str) -> Installation:
        item = self.versions[(plugin_id, version)]
        if item.state is not Lifecycle.PUBLISHED:
            raise RuntimeError("only published plugin versions may be installed")
        installation = Installation(installation_id, organization_id, plugin_id, version)
        self.installations[installation_id] = installation
        self.audit.append(AuditEvent("plugin.install", actor, installation_id, {"version": version}))
        return installation

    def update(self, installation_id: str, version: str, actor: str) -> Installation:
        installation = self.installations[installation_id]
        item = self.versions[(installation.plugin_id, version)]
        if item.state is not Lifecycle.PUBLISHED:
            raise RuntimeError("target version is not published")
        installation.previous_version, installation.version = installation.version, version
        installation.state = Lifecycle.ACTIVE
        self.audit.append(AuditEvent("plugin.update", actor, installation_id, {"version": version}))
        return installation

    def disable(self, installation_id: str, actor: str) -> Installation:
        installation = self.installations[installation_id]
        installation.state = Lifecycle.DISABLED
        self.audit.append(AuditEvent("plugin.disable", actor, installation_id))
        return installation

    def rollback(self, installation_id: str, actor: str) -> Installation:
        installation = self.installations[installation_id]
        if not installation.previous_version:
            raise RuntimeError("no previous plugin version is retained")
        installation.version, installation.previous_version = installation.previous_version, installation.version
        installation.state = Lifecycle.ACTIVE
        self.audit.append(AuditEvent("plugin.rollback", actor, installation_id, {"version": installation.version}))
        return installation

    def uninstall(self, installation_id: str, actor: str) -> Installation:
        installation = self.installations[installation_id]
        installation.state = Lifecycle.UNINSTALLED
        self.audit.append(AuditEvent("plugin.uninstall", actor, installation_id))
        return installation


class JobState(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    DEAD = "dead"


@dataclass(slots=True)
class DistributedJob:
    job_id: str
    capability: str
    payload: dict[str, object]
    max_attempts: int = 3
    attempts: int = 0
    state: JobState = JobState.QUEUED
    worker_id: str | None = None
    fencing_token: int = 0
    cancelled: bool = False


class DistributedRuntime:
    """Deterministic lease/fencing/retry/failover/reconciliation contract."""
    def __init__(self) -> None:
        self.jobs: dict[str, DistributedJob] = {}
        self.workers: dict[str, set[str]] = {}
        self.audit: list[AuditEvent] = []

    def register_worker(self, worker_id: str, capabilities: set[str]) -> None:
        self.workers[worker_id] = set(capabilities)

    def submit(self, job: DistributedJob) -> DistributedJob:
        if job.job_id in self.jobs:
            return self.jobs[job.job_id]
        self.jobs[job.job_id] = job
        return job

    def lease(self, worker_id: str) -> tuple[DistributedJob, int] | None:
        capabilities = self.workers.get(worker_id, set())
        for job in self.jobs.values():
            if job.cancelled:
                job.state = JobState.CANCELLED
                continue
            if job.state in {JobState.QUEUED, JobState.RETRY} and job.capability in capabilities:
                job.attempts += 1
                job.fencing_token += 1
                job.worker_id = worker_id
                job.state = JobState.LEASED
                return job, job.fencing_token
        return None

    def complete(self, job_id: str, worker_id: str, token: int) -> DistributedJob:
        job = self._fenced(job_id, worker_id, token)
        job.state = JobState.SUCCEEDED
        return job

    def fail(self, job_id: str, worker_id: str, token: int) -> DistributedJob:
        job = self._fenced(job_id, worker_id, token)
        job.worker_id = None
        job.state = JobState.RETRY if job.attempts < job.max_attempts else JobState.DEAD
        return job

    def cancel(self, job_id: str) -> DistributedJob:
        job = self.jobs[job_id]
        job.cancelled = True
        job.state = JobState.CANCELLED
        job.fencing_token += 1
        job.worker_id = None
        return job

    def failover(self, worker_id: str) -> tuple[str, ...]:
        recovered = []
        for job in self.jobs.values():
            if job.worker_id == worker_id and job.state is JobState.LEASED:
                job.worker_id = None
                job.fencing_token += 1
                job.state = JobState.RETRY
                recovered.append(job.job_id)
        self.workers.pop(worker_id, None)
        return tuple(recovered)

    def reconcile(self) -> dict[str, int]:
        return {state.value: sum(j.state is state for j in self.jobs.values()) for state in JobState}

    def _fenced(self, job_id: str, worker_id: str, token: int) -> DistributedJob:
        job = self.jobs[job_id]
        if job.state is not JobState.LEASED or job.worker_id != worker_id or job.fencing_token != token:
            raise PermissionError("stale or invalid distributed-runtime lease")
        return job


class IntegrationState(str, Enum):
    UNCONFIGURED = "unconfigured"
    DISABLED = "disabled"
    READY = "ready"
    DEGRADED = "degraded"


@dataclass(slots=True)
class IntegrationDefinition:
    integration_id: str
    category: str
    credential_ref: str | None
    endpoint: str
    enabled: bool = False
    scopes: frozenset[str] = field(default_factory=frozenset)
    retries: int = 3


class NonModelIntegrationRegistry:
    """Truthful non-model integration configuration without storing secret values."""
    CATEGORIES = frozenset({"cloud", "source_control", "storage", "webhook", "calendar", "messaging", "enterprise"})

    def __init__(self) -> None:
        self.items: dict[str, IntegrationDefinition] = {}
        self.audit: list[AuditEvent] = []

    def configure(self, item: IntegrationDefinition, actor: str) -> IntegrationDefinition:
        if item.category not in self.CATEGORIES:
            raise ValueError("unsupported non-model integration category")
        parsed = urlparse(item.endpoint)
        if parsed.scheme not in {"https", "ssh"}:
            raise ValueError("integration endpoint must use HTTPS or SSH")
        self.items[item.integration_id] = item
        self.audit.append(AuditEvent("integration.configure", actor, item.integration_id))
        return item

    def health(self, integration_id: str, *, probe_ok: bool | None = None) -> IntegrationState:
        item = self.items[integration_id]
        if not item.credential_ref:
            return IntegrationState.UNCONFIGURED
        if not item.enabled:
            return IntegrationState.DISABLED
        if probe_ok is None:
            return IntegrationState.DEGRADED
        return IntegrationState.READY if probe_ok else IntegrationState.DEGRADED

    def disable(self, integration_id: str, actor: str) -> IntegrationDefinition:
        item = self.items[integration_id]
        item.enabled = False
        self.audit.append(AuditEvent("integration.disable", actor, integration_id))
        return item

    def snapshot(self) -> str:
        payload = [{"id": i.integration_id, "category": i.category, "enabled": i.enabled, "configured": bool(i.credential_ref), "scopes": sorted(i.scopes)} for i in self.items.values()]
        return json.dumps(sorted(payload, key=lambda x: x["id"]), sort_keys=True)
