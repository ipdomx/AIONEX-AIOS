from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from aios.organization import EngineeringOrganization

from .fabric import WorkerAgent, drive_workers_until_terminal
from .models import ProjectCycleResult, TaskRecord, TaskState
from .store import ExecutionFabricStore


DEFAULT_PHASE22D_SOURCE = Path(
    "/var/tmp/aionex-phase22d/evidence-closure/phase22d-evidence-closure-v2"
)
DEFAULT_OUTPUT_ROOT = Path("/var/tmp/aionex-phase23/distributed-project-cycles")
DEFAULT_STATE_PATH = Path("/var/tmp/aionex-phase23/state/execution-fabric.sqlite3")
DEFAULT_EXECUTION_ID = "phase23-distributed-project-cycle"
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DistributedProjectCycleValidationError(ValueError):
    """Raised when the distributed project-cycle evidence contract is invalid."""


class DistributedProjectCycle:
    """Distributes six engineering departments across durable leased workers."""

    def __init__(
        self,
        *,
        store: ExecutionFabricStore | None = None,
        state_path: str | Path = DEFAULT_STATE_PATH,
        organization: EngineeringOrganization | None = None,
        lease_seconds: float = 30.0,
        heartbeat_timeout: float = 30.0,
        maximum_attempts: int = 2,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_timeout <= 0:
            raise ValueError("lease and heartbeat timeouts must be positive")
        if maximum_attempts not in (1, 2, 3):
            raise ValueError("maximum_attempts must be between one and three")
        self.store = store or ExecutionFabricStore(state_path)
        self.organization = organization or EngineeringOrganization()
        self.lease_seconds = float(lease_seconds)
        self.heartbeat_timeout = float(heartbeat_timeout)
        self.maximum_attempts = int(maximum_attempts)

    def execute(
        self,
        *,
        execution_id: str = DEFAULT_EXECUTION_ID,
        source_directory: str | Path = DEFAULT_PHASE22D_SOURCE,
        output_root: str | Path = DEFAULT_OUTPUT_ROOT,
        project: str | None = None,
        objective: str | None = None,
        workers: Sequence[WorkerAgent] | None = None,
    ) -> ProjectCycleResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._execute_async(
                    execution_id=execution_id,
                    source_directory=source_directory,
                    output_root=output_root,
                    project=project,
                    objective=objective,
                    workers=workers,
                )
            )
        raise RuntimeError(
            "DistributedProjectCycle.execute cannot run inside an active event loop"
        )

    async def _execute_async(
        self,
        *,
        execution_id: str,
        source_directory: str | Path,
        output_root: str | Path,
        project: str | None,
        objective: str | None,
        workers: Sequence[WorkerAgent] | None,
    ) -> ProjectCycleResult:
        safe_id = self._validate_execution_id(execution_id)
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")
        if destination.exists():
            raise FileExistsError(f"distributed execution already exists: {safe_id}")
        if staging.exists():
            raise FileExistsError(f"distributed staging already exists: {safe_id}")

        source = Path(source_directory).resolve(strict=True)
        source_manifest, departments = self._validate_source(source)
        selected_project = project or str(source_manifest["project"])
        selected_objective = objective or str(source_manifest["objective"])
        if not selected_project.strip() or not selected_objective.strip():
            raise DistributedProjectCycleValidationError(
                "project and objective must be non-empty"
            )

        lock_name = f"project-cycle:{safe_id}"
        lock_owner = f"phase23-{uuid.uuid4().hex}"
        if not self.store.acquire_lock(
            lock_name,
            lock_owner,
            ttl_seconds=600.0,
        ):
            raise RuntimeError("distributed project-cycle lock is already held")

        started = time.monotonic()
        try:
            blueprint = self.organization.plan(selected_project, selected_objective)
            departments_by_name = {
                str(item["department"]): item for item in departments
            }
            for index, deliverable in enumerate(blueprint.deliverables):
                source_item = departments_by_name[deliverable.department]
                self.store.submit_task(
                    execution_id=safe_id,
                    name="department.verify-evidence",
                    capability=deliverable.department.lower(),
                    priority=10 + index,
                    max_attempts=self.maximum_attempts,
                    idempotency_key=f"{safe_id}:{deliverable.department.lower()}",
                    payload={
                        "execution_id": safe_id,
                        "department": deliverable.department,
                        "acceptance_criteria": list(deliverable.acceptance_criteria),
                        "source_directory": str(source),
                        "source_path": source_item["path"],
                        "source_sha256": source_item["sha256"],
                    },
                )

            active_workers = list(workers or self._default_workers())
            tasks = await drive_workers_until_terminal(
                self.store,
                active_workers,
                safe_id,
                max_rounds=1000,
                idle_round_limit=10,
            )
            task_by_department = {
                str(task.payload["department"]): task for task in tasks
            }

            for deliverable in blueprint.deliverables:
                task = task_by_department[deliverable.department]
                if task.state == TaskState.SUCCEEDED and task.result is not None:
                    result = task.result
                    deliverable.evidence.update(
                        {
                            "passed_criteria": list(result["passed_criteria"]),
                            "tests_passed": bool(result["tests_passed"]),
                            "security_reviewed": bool(result["security_reviewed"]),
                            "distributed_task_id": task.task_id,
                            "distributed_worker_id": result.get("worker_id"),
                            "source_sha256": result["source_sha256"],
                            "verification_receipts": result["verification_receipts"],
                        }
                    )
                else:
                    deliverable.evidence.update(
                        {
                            "passed_criteria": [],
                            "tests_passed": False,
                            "security_reviewed": False,
                            "distributed_task_id": task.task_id,
                        }
                    )
                    deliverable.defects.append(
                        f"distributed task did not succeed: {task.error or task.state.value}"
                    )

            review = self.organization.chief_review(blueprint)
            total_duration = time.monotonic() - started
            staging.mkdir(mode=0o700)
            task_records = [self._task_manifest(task) for task in tasks]
            dead_letters = self.store.list_dead_letters(safe_id)
            workers_used = tuple(
                sorted(
                    {
                        str(task.result.get("worker_id"))
                        for task in tasks
                        if task.result and task.result.get("worker_id")
                    }
                )
            )
            manifest = {
                "schema_version": 1,
                "phase": 23,
                "mode": "distributed-execution-fabric",
                "execution_id": safe_id,
                "project": selected_project,
                "objective": selected_objective,
                "source": {
                    "phase": source_manifest.get("phase"),
                    "execution_id": source_manifest["execution_id"],
                    "directory": str(source),
                    "manifest_sha256": self._sha256(source / "manifest.json"),
                    "approved": source_manifest["review"]["approved"],
                    "readiness_score": source_manifest["review"]["readiness_score"],
                    "immutable": True,
                },
                "fabric": {
                    "store": str(self.store.path),
                    "queue": "sqlite-durable",
                    "claiming": "atomic-BEGIN-IMMEDIATE",
                    "worker_heartbeat": True,
                    "task_leases": True,
                    "lease_seconds": self.lease_seconds,
                    "maximum_attempts": self.maximum_attempts,
                    "idempotency_keys": True,
                    "execution_lock": lock_name,
                    "dead_letter_queue": True,
                    "workers_registered": len(self.store.list_workers()),
                    "workers_used": list(workers_used),
                },
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
                "review": {
                    "approved": review.approved,
                    "readiness_score": review.readiness_score,
                    "blocking_findings": list(review.blocking_findings),
                    "rework_plan": list(review.rework_plan),
                    "rationale": review.rationale,
                    "departments": [
                        {
                            "department": decision.department,
                            "approved": decision.approved,
                            "score": decision.score,
                            "findings": list(decision.findings),
                            "required_actions": list(decision.required_actions),
                            "manager_id": decision.manager_id,
                        }
                        for decision in review.department_decisions
                    ],
                },
                "summary": {
                    "tasks_total": len(tasks),
                    "tasks_succeeded": sum(
                        task.state == TaskState.SUCCEEDED for task in tasks
                    ),
                    "tasks_dead_lettered": sum(
                        task.state == TaskState.DEAD_LETTER for task in tasks
                    ),
                    "retries": sum(max(0, task.attempts - 1) for task in tasks),
                    "workers_used": len(workers_used),
                    "total_duration": round(total_duration, 6),
                },
                "proof": {
                    "multiple_workers_used": len(workers_used) >= 2,
                    "all_six_departments_distributed": len(tasks) == 6,
                    "all_tasks_terminal": all(
                        task.state
                        in {
                            TaskState.SUCCEEDED,
                            TaskState.DEAD_LETTER,
                            TaskState.CANCELLED,
                        }
                        for task in tasks
                    ),
                    "network_used": False,
                    "provider_key_used": False,
                    "cloud_request_sent": False,
                    "fallback_used": False,
                    "production_modified": False,
                    "source_execution_modified": False,
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write_text(manifest_path, self._canonical_json(manifest))
            report_path = staging / "REPORT.md"
            self._atomic_write_text(report_path, self._report(manifest))
            os.replace(staging, destination)
            return ProjectCycleResult(
                execution_id=safe_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                approved=review.approved,
                readiness_score=review.readiness_score,
                blocking_findings=review.blocking_findings,
                rework_plan=review.rework_plan,
                tasks_total=len(tasks),
                tasks_succeeded=sum(
                    task.state == TaskState.SUCCEEDED for task in tasks
                ),
                tasks_dead_lettered=sum(
                    task.state == TaskState.DEAD_LETTER for task in tasks
                ),
                workers_used=workers_used,
                total_duration=round(total_duration, 6),
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            self.store.release_lock(lock_name, lock_owner)

    def _default_workers(self) -> tuple[WorkerAgent, ...]:
        handler = {"department.verify-evidence": self._verify_department_evidence}
        return (
            WorkerAgent(
                self.store,
                "worker-architecture-quality",
                ("architecture", "quality"),
                handlers=handler,
                lease_seconds=self.lease_seconds,
                heartbeat_timeout=self.heartbeat_timeout,
                metadata={"phase": 23, "group": "design-and-quality"},
            ),
            WorkerAgent(
                self.store,
                "worker-product",
                ("backend", "frontend"),
                handlers=handler,
                lease_seconds=self.lease_seconds,
                heartbeat_timeout=self.heartbeat_timeout,
                metadata={"phase": 23, "group": "product-engineering"},
            ),
            WorkerAgent(
                self.store,
                "worker-security-operations",
                ("security", "devops"),
                handlers=handler,
                lease_seconds=self.lease_seconds,
                heartbeat_timeout=self.heartbeat_timeout,
                metadata={"phase": 23, "group": "security-and-operations"},
            ),
        )

    @classmethod
    def _verify_department_evidence(cls, payload: dict[str, Any]) -> dict[str, Any]:
        source_directory = Path(str(payload["source_directory"])).resolve(strict=True)
        relative = Path(str(payload["source_path"]))
        source_path = cls._contained(source_directory, source_directory / relative)
        if not source_path.is_file() or source_path.is_symlink():
            raise DistributedProjectCycleValidationError(
                "department evidence file is missing or unsafe"
            )
        digest = cls._sha256(source_path)
        if digest != str(payload["source_sha256"]):
            raise DistributedProjectCycleValidationError(
                "department evidence hash mismatch"
            )
        try:
            evidence = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DistributedProjectCycleValidationError(
                "department evidence JSON is invalid"
            ) from exc
        if not isinstance(evidence, Mapping):
            raise DistributedProjectCycleValidationError(
                "department evidence must be an object"
            )
        department = str(payload["department"])
        criteria = [str(item) for item in payload["acceptance_criteria"]]
        proven = [str(item) for item in evidence.get("acceptance_criteria_proven", [])]
        if evidence.get("department") != department or set(proven) != set(criteria):
            raise DistributedProjectCycleValidationError(
                "department acceptance evidence is incomplete"
            )
        if evidence.get("model_claims_used_as_execution_proof") is not False:
            raise DistributedProjectCycleValidationError(
                "model claims cannot be used as execution proof"
            )

        receipts: dict[str, dict[str, str]] = {}
        for name in ("test_receipt", "security_review_receipt"):
            receipt_relative = Path(str(evidence.get(name) or ""))
            receipt_path = cls._contained(
                source_directory,
                source_directory / receipt_relative,
            )
            expected_hash = str(evidence.get(f"{name}_sha256") or "")
            if (
                not receipt_path.is_file()
                or receipt_path.is_symlink()
                or cls._sha256(receipt_path) != expected_hash
            ):
                raise DistributedProjectCycleValidationError(
                    f"{name} is missing or has a hash mismatch"
                )
            receipts[name] = {
                "path": str(receipt_relative),
                "sha256": expected_hash,
            }

        return {
            "department": department,
            "passed_criteria": criteria,
            "tests_passed": evidence.get("tests_passed") is True,
            "security_reviewed": evidence.get("security_reviewed") is True,
            "source_path": str(relative),
            "source_sha256": digest,
            "verification_receipts": receipts,
            "network_used": False,
            "production_modified": False,
        }

    @classmethod
    def _validate_source(
        cls, source_directory: Path
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not source_directory.is_dir() or source_directory.is_symlink():
            raise DistributedProjectCycleValidationError(
                "Phase 22D source must be a regular directory"
            )
        manifest_path = source_directory / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise DistributedProjectCycleValidationError(
                "Phase 22D source manifest is missing or unsafe"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DistributedProjectCycleValidationError(
                "Phase 22D source manifest is invalid"
            ) from exc
        if not isinstance(manifest, dict):
            raise DistributedProjectCycleValidationError(
                "Phase 22D source manifest must be an object"
            )
        if manifest.get("phase") not in {"22D", 22, "22d"}:
            raise DistributedProjectCycleValidationError(
                "source is not a Phase 22D evidence closure"
            )
        review = manifest.get("review")
        proof = manifest.get("proof")
        if not isinstance(review, Mapping) or review.get("approved") is not True:
            raise DistributedProjectCycleValidationError(
                "Phase 22D source is not approved"
            )
        if not isinstance(proof, Mapping):
            raise DistributedProjectCycleValidationError(
                "Phase 22D proof is missing"
            )
        required_proof = {
            "tests_passed": True,
            "security_reviewed": True,
            "production_modified": False,
            "fallback_used": False,
        }
        for key, expected in required_proof.items():
            if proof.get(key) is not expected:
                raise DistributedProjectCycleValidationError(
                    f"Phase 22D proof failed: {key}"
                )
        departments = manifest.get("departments")
        if not isinstance(departments, list) or len(departments) != 6:
            raise DistributedProjectCycleValidationError(
                "Phase 22D must contain six department receipts"
            )
        seen: set[str] = set()
        validated: list[dict[str, Any]] = []
        for item in departments:
            if not isinstance(item, Mapping):
                raise DistributedProjectCycleValidationError(
                    "Phase 22D department receipt is invalid"
                )
            department = str(item.get("department") or "")
            if not department or department in seen:
                raise DistributedProjectCycleValidationError(
                    "Phase 22D department receipts are duplicated or unnamed"
                )
            relative = Path(str(item.get("path") or ""))
            path = cls._contained(source_directory, source_directory / relative)
            if (
                not path.is_file()
                or path.is_symlink()
                or cls._sha256(path) != str(item.get("sha256") or "")
            ):
                raise DistributedProjectCycleValidationError(
                    f"Phase 22D department receipt is missing or corrupted: {department}"
                )
            seen.add(department)
            validated.append(
                {
                    "department": department,
                    "path": str(relative),
                    "sha256": str(item["sha256"]),
                }
            )
        expected = set(EngineeringOrganization.DEFAULT_DEPARTMENTS)
        if seen != expected:
            raise DistributedProjectCycleValidationError(
                "Phase 22D department set does not match the engineering organization"
            )
        return manifest, validated

    @staticmethod
    def _task_manifest(task: TaskRecord) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "department": task.payload.get("department"),
            "capability": task.capability,
            "state": task.state.value,
            "attempts": task.attempts,
            "max_attempts": task.max_attempts,
            "worker_id": task.result.get("worker_id") if task.result else None,
            "error": task.error,
            "source_sha256": (
                task.result.get("source_sha256") if task.result else None
            ),
        }

    @staticmethod
    def _prepare_root(output_root: str | Path) -> Path:
        raw = Path(output_root)
        if not raw.is_absolute():
            raise ValueError("output_root must be absolute")
        raw.mkdir(parents=True, exist_ok=True)
        root = raw.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        return root

    @staticmethod
    def _validate_execution_id(execution_id: str) -> str:
        if not _EXECUTION_ID.fullmatch(execution_id) or execution_id in {".", ".."}:
            raise ValueError("execution_id contains unsafe path characters")
        return execution_id

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError("path escapes the allowed root")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
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
    def _report(manifest: Mapping[str, Any]) -> str:
        review = manifest["review"]
        summary = manifest["summary"]
        workers = manifest["fabric"]["workers_used"]
        tasks = "\n".join(
            f"- {item['department']}: `{item['state']}` on `{item['worker_id']}` "
            f"after `{item['attempts']}` attempt(s)"
            for item in manifest["tasks"]
        )
        blockers = review["blocking_findings"] or ["None"]
        rework = review["rework_plan"] or ["None"]
        return (
            "# Phase 23 Distributed Execution Fabric Report\n\n"
            f"- Execution ID: `{manifest['execution_id']}`\n"
            f"- Queue: `{manifest['fabric']['queue']}`\n"
            f"- Workers used: `{len(workers)}`\n"
            f"- Tasks: `{summary['tasks_total']}`\n"
            f"- Succeeded: `{summary['tasks_succeeded']}`\n"
            f"- Dead-lettered: `{summary['tasks_dead_lettered']}`\n"
            f"- Retries: `{summary['retries']}`\n"
            f"- Approved: `{str(review['approved']).lower()}`\n"
            f"- Readiness score: `{review['readiness_score']}`\n"
            f"- Duration: `{summary['total_duration']} seconds`\n"
            "- Network used: `false`\n"
            "- Provider key used: `false`\n"
            "- Cloud request sent: `false`\n"
            "- Production modified: `false`\n\n"
            f"## Tasks\n\n{tasks}\n\n"
            "## Blocking findings\n\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n\n## Rework plan\n\n"
            + "\n".join(f"- {item}" for item in rework)
            + "\n"
        )
