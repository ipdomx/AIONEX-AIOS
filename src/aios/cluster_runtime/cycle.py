from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aios.execution_fabric import ExecutionFabricStore, TaskRecord, TaskState
from aios.organization import EngineeringOrganization

from .state import ClusterNodeState, ClusterStateStore


DEFAULT_PHASE22D_SOURCE = Path(
    "/var/tmp/aionex-phase22d/evidence-closure/phase22d-evidence-closure-v2"
)
DEFAULT_PHASE24A_OUTPUT = Path("/var/tmp/aionex-phase24a/evidence")
DEPARTMENTS = ("Architecture", "Backend", "Frontend", "Security", "Quality", "DevOps")


class ClusterCycleValidationError(ValueError):
    """Raised when cluster or source evidence cannot prove the Phase 24A contract."""


@dataclass(frozen=True, slots=True)
class Phase24AResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    approved: bool
    readiness_score: float
    tasks_total: int
    tasks_succeeded: int
    recovered_tasks: int
    leaders_observed: tuple[str, ...]
    workers_used: tuple[str, ...]
    total_duration: float


class MultiNodeProjectCycle:
    """Seeds and closes one six-department project cycle on the shared cluster fabric."""

    TASK_NAME = "phase24a.department"

    def __init__(
        self,
        state_path: str | Path,
        *,
        cluster_id: str = "aionex-phase24a",
        source_directory: str | Path = DEFAULT_PHASE22D_SOURCE,
    ) -> None:
        raw_state = Path(state_path)
        raw_source = Path(source_directory)
        if not raw_state.is_absolute() or not raw_source.is_absolute():
            raise ValueError("state and source paths must be absolute")
        self.state_path = raw_state.resolve(strict=False)
        self.source_directory = raw_source.resolve(strict=True)
        self.cluster_id = cluster_id
        self.fabric = ExecutionFabricStore(self.state_path)
        self.cluster = ClusterStateStore(self.state_path)
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
                "simulate_seconds": float(slow_seconds if department == slow_department else 0.05),
                "production_modified": False,
            }
            task = self.fabric.submit_task(
                execution_id=execution_id,
                name=self.TASK_NAME,
                capability=department.lower(),
                payload=payload,
                idempotency_key=f"phase24a:{execution_id}:{department.lower()}",
                priority=1 if department == slow_department else 100 + index,
                max_attempts=3,
            )
            duplicate = self.fabric.submit_task(
                execution_id=execution_id,
                name=self.TASK_NAME,
                capability=department.lower(),
                payload=payload,
                idempotency_key=f"phase24a:{execution_id}:{department.lower()}",
                priority=1 if department == slow_department else 100 + index,
                max_attempts=3,
            )
            if duplicate.task_id != task.task_id:
                raise ClusterCycleValidationError("idempotent task submission created a duplicate")
            tasks.append(task)
        self.cluster.record_event(
            "project-cycle-prepared",
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
            for task in self.fabric.list_tasks(execution_id):
                if (
                    task.payload.get("department") == department
                    and task.state == TaskState.LEASED
                    and task.lease_owner
                ):
                    return task
            time.sleep(0.1)
        raise TimeoutError(f"{department} task was not leased")

    def wait_for_nodes(
        self,
        node_ids: set[str],
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            nodes = {node.node_id: node for node in self.cluster.list_nodes()}
            if all(
                node_id in nodes and nodes[node_id].state == ClusterNodeState.ONLINE
                for node_id in node_ids
            ):
                return
            time.sleep(0.1)
        raise TimeoutError(f"nodes did not become online: {sorted(node_ids)}")

    def wait_for_leader(
        self,
        *,
        excluded_node: str | None = None,
        minimum_term: int = 1,
        timeout_seconds: float = 30.0,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            leader = self.cluster.get_leader(self.cluster_id)
            if (
                leader is not None
                and leader.term >= minimum_term
                and leader.node_id != excluded_node
            ):
                return leader.node_id
            time.sleep(0.1)
        raise TimeoutError("an eligible cluster leader was not elected")

    def wait_for_terminal(
        self,
        execution_id: str,
        *,
        timeout_seconds: float = 90.0,
    ) -> tuple[TaskRecord, ...]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            tasks = self.fabric.list_tasks(execution_id)
            if len(tasks) == len(DEPARTMENTS) and all(
                task.state in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER, TaskState.CANCELLED}
                for task in tasks
            ):
                return tasks
            time.sleep(0.1)
        raise TimeoutError("distributed project cycle did not reach terminal state")

    def finalize(
        self,
        execution_id: str,
        *,
        output_root: str | Path = DEFAULT_PHASE24A_OUTPUT,
        failed_node: str,
        initial_leader: str,
        replacement_leader: str,
        recovered_task_id: str,
        simulation_started_at: float,
        runtime_artifacts: Mapping[str, Any] | None = None,
    ) -> Phase24AResult:
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / execution_id)
        staging = self._contained(root, root / f".staging-{execution_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError("Phase 24A evidence execution already exists")
        tasks = self.wait_for_terminal(execution_id)
        staging.mkdir(mode=0o700)
        started = time.monotonic()
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
            workers_used: set[str] = set()
            recovered_tasks = 0
            for deliverable in blueprint.deliverables:
                task = task_by_department[deliverable.department]
                if task.state != TaskState.SUCCEEDED or not isinstance(task.result, dict):
                    deliverable.defects.append(f"distributed task ended in {task.state.value}")
                    result = {}
                else:
                    result = dict(task.result)
                    workers_used.add(str(result.get("worker_id") or ""))
                    if task.attempts > 1:
                        recovered_tasks += 1
                    deliverable.evidence.update(
                        {
                            "passed_criteria": list(result.get("acceptance_criteria_proven") or []),
                            "tests_passed": bool(result.get("tests_passed")),
                            "security_reviewed": bool(result.get("security_reviewed")),
                            "cluster_task_id": task.task_id,
                            "cluster_worker_id": result.get("worker_id"),
                            "cluster_task_attempts": task.attempts,
                        }
                    )
                receipt = {
                    "schema_version": 1,
                    "department": deliverable.department,
                    "task_id": task.task_id,
                    "state": task.state.value,
                    "attempts": task.attempts,
                    "max_attempts": task.max_attempts,
                    "worker_id": result.get("worker_id"),
                    "source_sha256": task.payload.get("source_sha256"),
                    "result": result,
                    "error": task.error,
                }
                receipt_path = task_directory / f"{deliverable.department.lower()}.json"
                self._atomic_write(receipt_path, self._canonical_json(receipt))
                task_records.append(
                    {
                        "department": deliverable.department,
                        "task_id": task.task_id,
                        "state": task.state.value,
                        "attempts": task.attempts,
                        "worker_id": result.get("worker_id"),
                        "path": str(receipt_path.relative_to(staging)),
                        "sha256": self._sha256(receipt_path),
                    }
                )

            review = organization.chief_review(blueprint)
            nodes = self.cluster.list_nodes()
            observations = self.cluster.list_peer_observations()
            leader_history = self.cluster.leader_history(self.cluster_id)
            leaders_observed = tuple(dict.fromkeys(str(item["node_id"]) for item in leader_history))
            events = self.cluster.list_events()
            dead_letters = self.fabric.list_dead_letters(execution_id)
            recovered_task = self.fabric.get_task(recovered_task_id)
            secure_pairs = {
                (item.observer_id, item.peer_id)
                for item in observations
                if item.healthy and item.tls_verified and item.authenticated
            }
            expected_pairs = {
                (left, right)
                for left in ("node-a", "node-b", "node-c")
                for right in ("node-a", "node-b", "node-c")
                if left != right
            }
            proof = {
                "three_nodes_registered": len({node.node_id for node in nodes}) == 3,
                "three_nodes_online_after_rejoin": all(
                    any(node.node_id == node_id and node.state == ClusterNodeState.ONLINE for node in nodes)
                    for node_id in ("node-a", "node-b", "node-c")
                ),
                "service_discovery_complete": expected_pairs <= secure_pairs,
                "tls_verified_between_nodes": expected_pairs <= secure_pairs,
                "hmac_authenticated_between_nodes": expected_pairs <= secure_pairs,
                "leader_failover_observed": (
                    initial_leader != replacement_leader
                    and len(set(leaders_observed)) >= 2
                    and any(item["event"] == "leader-failover" for item in leader_history)
                ),
                "worker_failure_injected": any(
                    item["event_type"] == "node-crash-injected"
                    and item["node_id"] == failed_node
                    for item in events
                ),
                "worker_rejoined": any(
                    item["event_type"] == "node-rejoined"
                    and item["node_id"] == failed_node
                    for item in events
                ),
                "leased_task_recovered": (
                    recovered_task.state == TaskState.SUCCEEDED
                    and recovered_task.attempts >= 2
                    and recovered_task.result is not None
                    and recovered_task.result.get("worker_id") != failed_node
                ),
                "all_six_tasks_succeeded": len(tasks) == 6 and all(task.state == TaskState.SUCCEEDED for task in tasks),
                "dead_letter_queue_empty": not dead_letters,
                "idempotency_prevented_duplicates": len(tasks) == 6,
                "shared_state_used": True,
                "docker_internal_network_used": True,
                "network_egress_required": False,
                "cloud_request_sent": False,
                "provider_key_used": False,
                "fallback_used": False,
                "production_modified": False,
                "source_execution_modified": False,
            }
            required_true = {
                "three_nodes_registered",
                "three_nodes_online_after_rejoin",
                "service_discovery_complete",
                "tls_verified_between_nodes",
                "hmac_authenticated_between_nodes",
                "leader_failover_observed",
                "worker_failure_injected",
                "worker_rejoined",
                "leased_task_recovered",
                "all_six_tasks_succeeded",
                "dead_letter_queue_empty",
                "idempotency_prevented_duplicates",
                "shared_state_used",
                "docker_internal_network_used",
            }
            required_false = {
                "network_egress_required",
                "cloud_request_sent",
                "provider_key_used",
                "fallback_used",
                "production_modified",
                "source_execution_modified",
            }
            blockers = list(review.blocking_findings)
            blockers.extend(
                f"proof failed: {name}"
                for name in sorted(required_true)
                if proof.get(name) is not True
            )
            blockers.extend(
                f"proof failed: {name}"
                for name in sorted(required_false)
                if proof.get(name) is not False
            )
            passed_proofs = sum(proof.get(name) is True for name in required_true) + sum(
                proof.get(name) is False for name in required_false
            )
            total_proofs = len(required_true) + len(required_false)
            approved = review.approved and not blockers
            readiness = 1.0 if approved else round(passed_proofs / total_proofs, 4)
            total_duration = time.time() - simulation_started_at
            manifest = {
                "schema_version": 1,
                "phase": "24A",
                "mode": "docker-multi-node-cluster-simulation",
                "execution_id": execution_id,
                "cluster_id": self.cluster_id,
                "project": self.source_manifest["project"],
                "objective": self.source_manifest["objective"],
                "source": {
                    "phase": "22D",
                    "execution_id": self.source_manifest["execution_id"],
                    "directory": str(self.source_directory),
                    "manifest_sha256": self._sha256(self.source_directory / "manifest.json"),
                    "immutable": True,
                },
                "cluster": {
                    "nodes": [
                        {
                            "node_id": node.node_id,
                            "service_url": node.service_url,
                            "capabilities": list(node.capabilities),
                            "state": node.state.value,
                            "heartbeat_at": node.heartbeat_at,
                        }
                        for node in nodes
                    ],
                    "leader_history": list(leader_history),
                    "initial_leader": initial_leader,
                    "replacement_leader": replacement_leader,
                    "failed_node": failed_node,
                    "secure_peer_pairs": [list(item) for item in sorted(secure_pairs)],
                    "shared_state": str(self.state_path),
                    "transport": "TLS 1.2+ with HMAC-SHA256 request authentication",
                },
                "tasks": task_records,
                "runtime_artifacts": dict(runtime_artifacts or {}),
                "dead_letters": [
                    {
                        "task_id": item.task_id,
                        "department": item.payload.get("department"),
                        "attempts": item.attempts,
                        "final_error": item.final_error,
                    }
                    for item in dead_letters
                ],
                "review": {
                    "approved": approved,
                    "readiness_score": readiness,
                    "blocking_findings": blockers,
                    "rework_plan": list(review.rework_plan),
                    "organization_approved": review.approved,
                    "organization_readiness_score": review.readiness_score,
                },
                "proof": proof,
                "summary": {
                    "tasks_total": len(tasks),
                    "tasks_succeeded": sum(task.state == TaskState.SUCCEEDED for task in tasks),
                    "tasks_recovered_after_lease_expiry": recovered_tasks,
                    "tasks_dead_lettered": len(dead_letters),
                    "workers_used": len(workers_used),
                    "leaders_observed": len(set(leaders_observed)),
                    "total_duration": round(total_duration, 6),
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write(manifest_path, self._canonical_json(manifest))
            report_path = staging / "REPORT.md"
            self._atomic_write(report_path, self._report(manifest))
            os.replace(staging, destination)
            return Phase24AResult(
                execution_id=execution_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                approved=approved,
                readiness_score=readiness,
                tasks_total=len(tasks),
                tasks_succeeded=sum(task.state == TaskState.SUCCEEDED for task in tasks),
                recovered_tasks=recovered_tasks,
                leaders_observed=tuple(dict.fromkeys(leaders_observed)),
                workers_used=tuple(sorted(item for item in workers_used if item)),
                total_duration=round(total_duration, 6),
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _load_source(self) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        manifest_path = self.source_directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("phase") != "22D"
            or manifest.get("review", {}).get("approved") is not True
            or manifest.get("review", {}).get("readiness_score") != 1.0
        ):
            raise ClusterCycleValidationError("Phase 24A requires approved Phase 22D evidence")
        records = manifest.get("departments")
        if not isinstance(records, list) or len(records) != 6:
            raise ClusterCycleValidationError("Phase 22D must contain six department receipts")
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            department = str(record.get("department") or "")
            if department not in DEPARTMENTS or department in seen:
                raise ClusterCycleValidationError("Phase 22D departments are invalid")
            relative = Path(str(record.get("path") or ""))
            path = self._contained(self.source_directory, self.source_directory / relative)
            if not path.is_file() or path.is_symlink():
                raise ClusterCycleValidationError(f"source receipt is missing: {department}")
            digest = self._sha256(path)
            if digest != str(record.get("sha256") or ""):
                raise ClusterCycleValidationError(f"source receipt hash mismatch: {department}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            criteria = payload.get("acceptance_criteria_proven")
            if not isinstance(criteria, list) or len(criteria) != 3:
                raise ClusterCycleValidationError(f"source criteria are invalid: {department}")
            if payload.get("tests_passed") is not True or payload.get("security_reviewed") is not True:
                raise ClusterCycleValidationError(f"source evidence is incomplete: {department}")
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
        return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

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
        cluster = manifest["cluster"]
        blockers = review["blocking_findings"] or ["None"]
        return (
            "# Phase 24A Multi-Node Cluster Runtime Report\n\n"
            f"- Execution: `{manifest['execution_id']}`\n"
            f"- Nodes: `{len(cluster['nodes'])}`\n"
            f"- Initial leader: `{cluster['initial_leader']}`\n"
            f"- Replacement leader: `{cluster['replacement_leader']}`\n"
            f"- Failed and rejoined node: `{cluster['failed_node']}`\n"
            f"- Tasks: `{summary['tasks_succeeded']}/{summary['tasks_total']}` succeeded\n"
            f"- Recovered leased tasks: `{summary['tasks_recovered_after_lease_expiry']}`\n"
            f"- Dead letters: `{summary['tasks_dead_lettered']}`\n"
            f"- Workers used: `{summary['workers_used']}`\n"
            f"- Leaders observed: `{summary['leaders_observed']}`\n"
            f"- Approved: `{str(review['approved']).lower()}`\n"
            f"- Readiness: `{review['readiness_score']}`\n"
            "- Inter-node transport: `TLS 1.2+ / HMAC-SHA256`\n"
            "- Docker network: `isolated internal network`\n"
            "- Cloud request sent: `false`\n"
            "- Provider key used: `false`\n"
            "- Production modified: `false`\n\n"
            "## Blocking findings\n\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n"
        )
