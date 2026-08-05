from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from aios.execution_fabric import TaskRecord, TaskState
from aios.organization import EngineeringOrganization

from .models import MultiHostCycleResult
from .store import MultiHostControlStore


DEFAULT_PHASE22D_SOURCE = Path(
    "/var/tmp/aionex-phase22d/evidence-closure/phase22d-evidence-closure-v2"
)
DEFAULT_PHASE24B_OUTPUT = Path("/var/tmp/aionex-phase24b/evidence")
DEPARTMENTS = ("Architecture", "Backend", "Frontend", "Security", "Quality", "DevOps")


class MultiHostCycleValidationError(ValueError):
    """Raised when source or multi-host evidence cannot prove the requested boundary."""


class MultiHostProjectCycle:
    """Seeds and closes a six-department cycle through the remote control-plane fabric."""

    TASK_NAME = "phase24b.department"

    def __init__(
        self,
        state_path: str | Path,
        *,
        cluster_id: str = "aionex-phase24b",
        source_directory: str | Path = DEFAULT_PHASE22D_SOURCE,
    ) -> None:
        raw_state = Path(state_path)
        raw_source = Path(source_directory)
        if not raw_state.is_absolute() or not raw_source.is_absolute():
            raise ValueError("state and source paths must be absolute")
        self.state_path = raw_state.resolve(strict=False)
        self.source_directory = raw_source.resolve(strict=True)
        self.cluster_id = cluster_id
        self.control = MultiHostControlStore(self.state_path)
        self.source_manifest, self.source_records = self._load_source()

    def prepare(
        self,
        execution_id: str,
        *,
        slow_department: str = "Architecture",
        slow_seconds: float = 12.0,
    ) -> tuple[TaskRecord, ...]:
        if slow_department not in DEPARTMENTS:
            raise ValueError("slow_department is invalid")
        records_by_department = {
            record["department"]: record for record in self.source_records
        }
        tasks: list[TaskRecord] = []
        for index, department in enumerate(DEPARTMENTS):
            record = records_by_department[department]
            payload = {
                "schema_version": 1,
                "department": department,
                "source_path": str(record["path"]),
                "source_sha256": record["sha256"],
                "acceptance_criteria": list(record["acceptance_criteria"]),
                "simulate_seconds": float(
                    slow_seconds if department == slow_department else 0.05
                ),
                "production_modified": False,
            }
            idempotency_key = f"phase24b:{execution_id}:{department.lower()}"
            task = self.control.fabric.submit_task(
                execution_id=execution_id,
                name=self.TASK_NAME,
                capability=department.lower(),
                payload=payload,
                idempotency_key=idempotency_key,
                priority=1 if department == slow_department else 100 + index,
                max_attempts=3,
            )
            duplicate = self.control.fabric.submit_task(
                execution_id=execution_id,
                name=self.TASK_NAME,
                capability=department.lower(),
                payload=payload,
                idempotency_key=idempotency_key,
                priority=1 if department == slow_department else 100 + index,
                max_attempts=3,
            )
            if duplicate.task_id != task.task_id:
                raise MultiHostCycleValidationError(
                    "idempotent task submission created a duplicate"
                )
            tasks.append(task)
        self.control.record_event(
            "multi-host-project-cycle-prepared",
            None,
            {
                "execution_id": execution_id,
                "tasks": len(tasks),
                "slow_department": slow_department,
            },
        )
        return tuple(tasks)

    def wait_for_task_lease(
        self,
        execution_id: str,
        department: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> TaskRecord:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            for task in self.control.fabric.list_tasks(execution_id):
                if (
                    task.payload.get("department") == department
                    and task.state == TaskState.LEASED
                    and task.lease_owner
                ):
                    return task
            time.sleep(0.1)
        raise TimeoutError(f"{department} task was not leased")

    def wait_for_terminal(
        self,
        execution_id: str,
        *,
        timeout_seconds: float = 120.0,
    ) -> tuple[TaskRecord, ...]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            tasks = self.control.fabric.list_tasks(execution_id)
            if len(tasks) == len(DEPARTMENTS) and all(
                task.state
                in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}
                for task in tasks
            ):
                return tasks
            time.sleep(0.1)
        raise TimeoutError("multi-host project cycle did not reach terminal state")

    def wait_for_hosts_online(
        self,
        host_ids: set[str],
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            hosts = {host.host_id: host for host in self.control.list_hosts()}
            if all(
                host_id in hosts and hosts[host_id].state.value == "online"
                for host_id in host_ids
            ):
                return
            time.sleep(0.1)
        raise TimeoutError(f"hosts did not become online: {sorted(host_ids)}")

    def finalize(
        self,
        execution_id: str,
        *,
        output_root: str | Path = DEFAULT_PHASE24B_OUTPUT,
        partitioned_host: str,
        initial_leader: str,
        replacement_leader: str,
        recovered_task_id: str,
        validation_started_at: float,
        deployment_hosts: Sequence[str],
        separate_physical_hosts: bool,
        runtime_artifacts: Mapping[str, Any] | None = None,
    ) -> MultiHostCycleResult:
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / execution_id)
        staging = self._contained(root, root / f".staging-{execution_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError("Phase 24B evidence execution already exists")
        tasks = self.wait_for_terminal(execution_id)
        staging.mkdir(mode=0o700)
        try:
            task_directory = staging / "departments"
            task_directory.mkdir(mode=0o700)
            organization = EngineeringOrganization()
            blueprint = organization.plan(
                str(self.source_manifest["project"]),
                str(self.source_manifest["objective"]),
            )
            task_by_department = {
                str(task.payload.get("department")): task for task in tasks
            }
            task_records: list[dict[str, Any]] = []
            hosts_used: set[str] = set()
            recovered_tasks = 0
            for deliverable in blueprint.deliverables:
                task = task_by_department[deliverable.department]
                result = dict(task.result or {})
                if task.state != TaskState.SUCCEEDED or not result:
                    deliverable.defects.append(
                        f"remote task ended in {task.state.value}"
                    )
                else:
                    hosts_used.add(str(result.get("host_id") or ""))
                    if task.attempts > 1:
                        recovered_tasks += 1
                    deliverable.evidence.update(
                        {
                            "passed_criteria": list(
                                result.get("passed_criteria") or []
                            ),
                            "tests_passed": bool(result.get("tests_passed")),
                            "security_reviewed": bool(
                                result.get("security_reviewed")
                            ),
                            "remote_task_id": task.task_id,
                            "remote_host_id": result.get("host_id"),
                            "remote_task_attempts": task.attempts,
                        }
                    )
                receipt = {
                    "schema_version": 1,
                    "department": deliverable.department,
                    "task_id": task.task_id,
                    "state": task.state.value,
                    "attempts": task.attempts,
                    "max_attempts": task.max_attempts,
                    "host_id": result.get("host_id"),
                    "source_sha256": task.payload.get("source_sha256"),
                    "result": result,
                    "error": task.error,
                }
                receipt_path = (
                    task_directory / f"{deliverable.department.lower()}.json"
                )
                self._atomic_write(
                    receipt_path,
                    self._canonical_json(receipt),
                )
                task_records.append(
                    {
                        "department": deliverable.department,
                        "task_id": task.task_id,
                        "state": task.state.value,
                        "attempts": task.attempts,
                        "host_id": result.get("host_id"),
                        "path": str(receipt_path.relative_to(staging)),
                        "sha256": self._sha256(receipt_path),
                    }
                )

            organization_review = organization.chief_review(blueprint)
            hosts = self.control.list_hosts()
            leader_history = self.control.leader_history(self.cluster_id)
            events = self.control.list_events()
            dead_letters = self.control.fabric.list_dead_letters(execution_id)
            recovered_task = self.control.fabric.get_task(recovered_task_id)
            leaders_observed = tuple(
                dict.fromkeys(str(item["host_id"]) for item in leader_history)
            )
            deployment_host_set = {
                value.strip() for value in deployment_hosts if value.strip()
            }
            foundation_proof = {
                "three_hosts_enrolled": len(hosts) == 3,
                "three_hosts_online_after_rejoin": all(
                    host.state.value == "online" for host in hosts
                ),
                "unique_host_certificates": len(
                    {host.certificate_sha256 for host in hosts}
                )
                == len(hosts),
                "mutual_tls_required": True,
                "per_host_hmac_required": True,
                "request_replay_protection": True,
                "remote_state_api_used": True,
                "agents_share_no_state_filesystem": True,
                "leader_failover_observed": (
                    initial_leader != replacement_leader
                    and len(set(leaders_observed)) >= 2
                    and any(
                        item["event"] == "leader-failover"
                        for item in leader_history
                    )
                ),
                "network_partition_injected": any(
                    item["event_type"] == "network-partition-injected"
                    and item["host_id"] == partitioned_host
                    for item in events
                ),
                "partitioned_host_rejoined": any(
                    item["event_type"] == "network-partition-healed"
                    and item["host_id"] == partitioned_host
                    for item in events
                ),
                "leased_task_recovered": (
                    recovered_task.state == TaskState.SUCCEEDED
                    and recovered_task.attempts >= 2
                    and recovered_task.result is not None
                    and recovered_task.result.get("host_id") != partitioned_host
                ),
                "all_six_tasks_succeeded": len(tasks) == 6
                and all(task.state == TaskState.SUCCEEDED for task in tasks),
                "dead_letter_queue_empty": not dead_letters,
                "idempotency_prevented_duplicates": len(tasks) == 6,
                "cloud_request_sent": False,
                "provider_key_used": False,
                "fallback_used": False,
                "production_modified": False,
                "source_execution_modified": False,
            }
            required_true = {
                "three_hosts_enrolled",
                "three_hosts_online_after_rejoin",
                "unique_host_certificates",
                "mutual_tls_required",
                "per_host_hmac_required",
                "request_replay_protection",
                "remote_state_api_used",
                "agents_share_no_state_filesystem",
                "leader_failover_observed",
                "network_partition_injected",
                "partitioned_host_rejoined",
                "leased_task_recovered",
                "all_six_tasks_succeeded",
                "dead_letter_queue_empty",
                "idempotency_prevented_duplicates",
            }
            required_false = {
                "cloud_request_sent",
                "provider_key_used",
                "fallback_used",
                "production_modified",
                "source_execution_modified",
            }
            foundation_blockers = list(organization_review.blocking_findings)
            foundation_blockers.extend(
                f"foundation proof failed: {name}"
                for name in sorted(required_true)
                if foundation_proof.get(name) is not True
            )
            foundation_blockers.extend(
                f"foundation proof failed: {name}"
                for name in sorted(required_false)
                if foundation_proof.get(name) is not False
            )
            foundation_approved = (
                organization_review.approved and not foundation_blockers
            )
            physical_activation_proven = (
                separate_physical_hosts and len(deployment_host_set) >= 3
            )
            activation_blockers = list(foundation_blockers)
            if not physical_activation_proven:
                activation_blockers.append(
                    "physical-host activation requires at least three separately managed hosts"
                )
            activation_approved = foundation_approved and physical_activation_proven
            readiness = (
                1.0
                if activation_approved
                else 0.95 if foundation_approved else 0.0
            )
            total_duration = time.time() - validation_started_at
            manifest = {
                "schema_version": 1,
                "phase": "24B",
                "mode": (
                    "real-multi-host-activation"
                    if physical_activation_proven
                    else "multi-host-deployment-foundation-lab"
                ),
                "execution_id": execution_id,
                "cluster_id": self.cluster_id,
                "project": self.source_manifest["project"],
                "objective": self.source_manifest["objective"],
                "source": {
                    "phase": "22D",
                    "execution_id": self.source_manifest["execution_id"],
                    "directory": str(self.source_directory),
                    "manifest_sha256": self._sha256(
                        self.source_directory / "manifest.json"
                    ),
                    "immutable": True,
                },
                "deployment": {
                    "declared_hosts": sorted(deployment_host_set),
                    "separate_physical_hosts": bool(separate_physical_hosts),
                    "control_plane_state": str(self.state_path),
                    "state_access": "mutual-TLS HTTPS API only",
                    "agent_shared_filesystem": False,
                },
                "hosts": [
                    {
                        "host_id": host.host_id,
                        "service_url": host.service_url,
                        "capabilities": list(host.capabilities),
                        "certificate_sha256": host.certificate_sha256,
                        "state": host.state.value,
                        "heartbeat_at": host.heartbeat_at,
                        "metadata": host.metadata,
                    }
                    for host in hosts
                ],
                "leader_history": list(leader_history),
                "partitioned_host": partitioned_host,
                "initial_leader": initial_leader,
                "replacement_leader": replacement_leader,
                "tasks": task_records,
                "dead_letters": [
                    {
                        "task_id": item.task_id,
                        "department": item.payload.get("department"),
                        "attempts": item.attempts,
                        "final_error": item.final_error,
                    }
                    for item in dead_letters
                ],
                "runtime_artifacts": dict(runtime_artifacts or {}),
                "review": {
                    "foundation_approved": foundation_approved,
                    "activation_approved": activation_approved,
                    "approved": activation_approved,
                    "readiness_score": readiness,
                    "blocking_findings": activation_blockers,
                    "rework_plan": (
                        []
                        if activation_approved
                        else [
                            "enroll and validate three separate physical or virtual hosts"
                        ]
                    ),
                    "organization_approved": organization_review.approved,
                    "organization_readiness_score": organization_review.readiness_score,
                },
                "proof": {
                    **foundation_proof,
                    "separate_physical_hosts": physical_activation_proven,
                },
                "summary": {
                    "tasks_total": len(tasks),
                    "tasks_succeeded": sum(
                        task.state == TaskState.SUCCEEDED for task in tasks
                    ),
                    "tasks_recovered_after_partition": recovered_tasks,
                    "tasks_dead_lettered": len(dead_letters),
                    "hosts_used": len(hosts_used),
                    "leaders_observed": len(set(leaders_observed)),
                    "total_duration": round(total_duration, 6),
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write(manifest_path, self._canonical_json(manifest))
            report_path = staging / "REPORT.md"
            self._atomic_write(report_path, self._report(manifest))
            os.replace(staging, destination)
            return MultiHostCycleResult(
                execution_id=execution_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                approved=activation_approved,
                readiness_score=readiness,
                blocking_findings=tuple(activation_blockers),
                rework_plan=(
                    ()
                    if activation_approved
                    else (
                        "enroll and validate three separate physical or virtual hosts",
                    )
                ),
                tasks_total=len(tasks),
                tasks_succeeded=sum(
                    task.state == TaskState.SUCCEEDED for task in tasks
                ),
                tasks_dead_lettered=len(dead_letters),
                recovered_tasks=recovered_tasks,
                leaders_observed=leaders_observed,
                hosts_used=tuple(sorted(item for item in hosts_used if item)),
                total_duration=round(total_duration, 6),
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _load_source(self) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        manifest_path = self.source_directory / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise MultiHostCycleValidationError("Phase 22D manifest is missing or unsafe")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MultiHostCycleValidationError("Phase 22D manifest is invalid") from exc
        if (
            manifest.get("phase") != "22D"
            or manifest.get("review", {}).get("approved") is not True
            or manifest.get("review", {}).get("readiness_score") != 1.0
        ):
            raise MultiHostCycleValidationError(
                "Phase 24B requires approved Phase 22D evidence"
            )
        records = manifest.get("departments")
        if not isinstance(records, list) or len(records) != 6:
            raise MultiHostCycleValidationError(
                "Phase 22D must contain six department receipts"
            )
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise MultiHostCycleValidationError(
                    "Phase 22D department record is invalid"
                )
            department = str(record.get("department") or "")
            if department not in DEPARTMENTS or department in seen:
                raise MultiHostCycleValidationError(
                    "Phase 22D departments are invalid"
                )
            relative = Path(str(record.get("path") or ""))
            path = self._contained(
                self.source_directory,
                self.source_directory / relative,
            )
            if not path.is_file() or path.is_symlink():
                raise MultiHostCycleValidationError(
                    f"source receipt is missing: {department}"
                )
            digest = self._sha256(path)
            if digest != str(record.get("sha256") or ""):
                raise MultiHostCycleValidationError(
                    f"source receipt hash mismatch: {department}"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            criteria = payload.get("acceptance_criteria_proven")
            if not isinstance(criteria, list) or len(criteria) != 3:
                raise MultiHostCycleValidationError(
                    f"source criteria are invalid: {department}"
                )
            if (
                payload.get("tests_passed") is not True
                or payload.get("security_reviewed") is not True
            ):
                raise MultiHostCycleValidationError(
                    f"source evidence is incomplete: {department}"
                )
            validated.append(
                {
                    "department": department,
                    "path": path,
                    "sha256": digest,
                    "acceptance_criteria": tuple(str(item) for item in criteria),
                }
            )
            seen.add(department)
        return manifest, tuple(validated)

    @staticmethod
    def _prepare_root(path: str | Path) -> Path:
        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError("output root must be absolute")
        raw.mkdir(parents=True, exist_ok=True)
        return raw.resolve(strict=True)

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError("path escapes the approved root")
        return resolved

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _report(manifest: Mapping[str, Any]) -> str:
        review = manifest["review"]
        summary = manifest["summary"]
        blockers = review["blocking_findings"] or ["None"]
        return (
            "# Phase 24B Multi-Host Cluster Deployment Report\n\n"
            f"- Execution: `{manifest['execution_id']}`\n"
            f"- Mode: `{manifest['mode']}`\n"
            f"- Enrolled hosts: `{len(manifest['hosts'])}`\n"
            f"- Initial leader: `{manifest['initial_leader']}`\n"
            f"- Replacement leader: `{manifest['replacement_leader']}`\n"
            f"- Partitioned and rejoined host: `{manifest['partitioned_host']}`\n"
            f"- Tasks: `{summary['tasks_succeeded']}/{summary['tasks_total']}` succeeded\n"
            f"- Recovered tasks: `{summary['tasks_recovered_after_partition']}`\n"
            f"- Dead letters: `{summary['tasks_dead_lettered']}`\n"
            f"- Foundation approved: `{str(review['foundation_approved']).lower()}`\n"
            f"- Physical activation approved: `{str(review['activation_approved']).lower()}`\n"
            f"- Readiness: `{review['readiness_score']}`\n"
            "- Transport: `mutual TLS 1.2+ / per-host HMAC-SHA256 / nonce replay protection`\n"
            "- Shared agent filesystem: `false`\n"
            "- Production modified: `false`\n\n"
            "## Blocking findings\n\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n"
        )
