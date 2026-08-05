import asyncio
import hashlib
import inspect
import json
import time
from pathlib import Path

import pytest

import aios.execution_fabric.project_cycle as project_cycle_module
from aios.execution_fabric import (
    DistributedProjectCycle,
    DistributedProjectCycleValidationError,
    ExecutionFabricStore,
    TaskState,
    WorkerAgent,
    WorkerState,
)
from aios.organization import EngineeringOrganization


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def create_phase22d_source(tmp_path: Path) -> Path:
    root = tmp_path / "phase22d-source"
    departments_dir = root / "departments"
    evidence_dir = root / "evidence"
    departments_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)

    test_receipt = evidence_dir / "controlled-regression.json"
    security_receipt = evidence_dir / "security-review.json"
    write_json(
        test_receipt,
        {
            "passed": True,
            "passed_count": 107,
            "exit_code": 0,
            "network_required": False,
            "production_modified": False,
        },
    )
    write_json(
        security_receipt,
        {
            "approved": True,
            "finding_count": 0,
            "network_used": False,
            "production_modified": False,
        },
    )

    organization = EngineeringOrganization()
    blueprint = organization.plan("AIONEX-AIOS", "Run a distributed project cycle")
    records = []
    for deliverable in blueprint.deliverables:
        path = departments_dir / f"{deliverable.department.lower()}.json"
        write_json(
            path,
            {
                "schema_version": 1,
                "department": deliverable.department,
                "acceptance_criteria": list(deliverable.acceptance_criteria),
                "acceptance_criteria_proven": list(deliverable.acceptance_criteria),
                "tests_passed": True,
                "security_review_required": deliverable.department
                in {"Backend", "Security", "DevOps"},
                "security_reviewed": True,
                "test_receipt": "evidence/controlled-regression.json",
                "test_receipt_sha256": sha256(test_receipt),
                "security_review_receipt": "evidence/security-review.json",
                "security_review_receipt_sha256": sha256(security_receipt),
                "model_claims_used_as_execution_proof": False,
            },
        )
        records.append(
            {
                "department": deliverable.department,
                "path": f"departments/{path.name}",
                "sha256": sha256(path),
                "tests_passed": True,
                "security_reviewed": True,
            }
        )

    write_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "phase": "22D",
            "execution_id": "phase22d-fixture",
            "project": "AIONEX-AIOS",
            "objective": "Run a distributed project cycle",
            "departments": records,
            "review": {
                "approved": True,
                "readiness_score": 1.0,
                "blocking_findings": [],
                "rework_plan": [],
            },
            "proof": {
                "tests_passed": True,
                "security_reviewed": True,
                "production_modified": False,
                "fallback_used": False,
            },
        },
    )
    return root


def make_store(tmp_path: Path) -> ExecutionFabricStore:
    return ExecutionFabricStore(tmp_path / "state" / "fabric.sqlite3")


def test_store_requires_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        ExecutionFabricStore("relative.sqlite3")


def test_worker_registry_heartbeat_and_expiration(tmp_path):
    store = make_store(tmp_path)
    worker = store.register_worker(
        "worker-a",
        ("backend",),
        max_concurrency=2,
        now=100.0,
    )
    assert worker.state == WorkerState.ONLINE
    assert worker.capabilities == ("backend",)
    assert store.expire_stale_workers(10.0, now=109.0) == ()
    assert store.expire_stale_workers(10.0, now=111.0) == ("worker-a",)
    assert store.get_worker("worker-a").state == WorkerState.OFFLINE
    revived = store.heartbeat_worker("worker-a", state=WorkerState.ONLINE, now=112.0)
    assert revived.state == WorkerState.ONLINE


def test_task_submission_is_idempotent_and_binding_is_strict(tmp_path):
    store = make_store(tmp_path)
    first = store.submit_task(
        execution_id="e1",
        name="job",
        capability="backend",
        payload={"x": 1},
        idempotency_key="e1:backend",
    )
    second = store.submit_task(
        execution_id="e1",
        name="job",
        capability="backend",
        payload={"x": 1},
        idempotency_key="e1:backend",
    )
    assert second.task_id == first.task_id
    with pytest.raises(ValueError, match="different task data"):
        store.submit_task(
            execution_id="e1",
            name="job",
            capability="backend",
            payload={"x": 2},
            idempotency_key="e1:backend",
        )


def test_atomic_claim_respects_capability_priority_and_worker_capacity(tmp_path):
    store = make_store(tmp_path)
    store.register_worker("backend-worker", ("backend",), max_concurrency=1)
    low = store.submit_task(
        execution_id="e1",
        name="job",
        capability="backend",
        payload={"name": "low"},
        idempotency_key="e1:low",
        priority=100,
    )
    high = store.submit_task(
        execution_id="e1",
        name="job",
        capability="backend",
        payload={"name": "high"},
        idempotency_key="e1:high",
        priority=1,
    )
    store.submit_task(
        execution_id="e1",
        name="job",
        capability="frontend",
        payload={"name": "frontend"},
        idempotency_key="e1:frontend",
        priority=0,
    )
    claimed = store.claim_task("backend-worker")
    assert claimed is not None
    assert claimed.task_id == high.task_id
    assert claimed.attempts == 1
    assert store.claim_task("backend-worker") is None
    completed = store.complete_task(claimed.task_id, "backend-worker", {"ok": True})
    assert completed.state == TaskState.SUCCEEDED
    next_task = store.claim_task("backend-worker")
    assert next_task is not None
    assert next_task.task_id == low.task_id


def test_retry_then_dead_letter_records_final_failure(tmp_path):
    store = make_store(tmp_path)
    store.register_worker("worker", ("security",))
    task = store.submit_task(
        execution_id="e1",
        name="job",
        capability="security",
        payload={"department": "Security"},
        idempotency_key="e1:security",
        max_attempts=2,
    )
    first = store.claim_task("worker")
    assert first is not None
    retried = store.fail_task(first.task_id, "worker", "first failure")
    assert retried.state == TaskState.RETRY_WAIT
    second = store.claim_task("worker")
    assert second is not None
    dead = store.fail_task(second.task_id, "worker", "final failure")
    assert dead.state == TaskState.DEAD_LETTER
    letters = store.list_dead_letters("e1")
    assert len(letters) == 1
    assert letters[0].task_id == task.task_id
    assert letters[0].attempts == 2
    assert letters[0].final_error == "final failure"


def test_expired_lease_is_recovered_without_duplicate_completion(tmp_path):
    store = make_store(tmp_path)
    store.register_worker("worker-a", ("quality",), now=100.0)
    store.register_worker("worker-b", ("quality",), now=100.0)
    task = store.submit_task(
        execution_id="e1",
        name="job",
        capability="quality",
        payload={},
        idempotency_key="e1:quality",
        max_attempts=2,
        now=100.0,
    )
    first = store.claim_task(
        "worker-a", lease_seconds=5.0, heartbeat_timeout=30.0, now=100.0
    )
    assert first is not None
    recovered = store.recover_expired_leases(now=106.0)
    assert recovered == (task.task_id,)
    second = store.claim_task(
        "worker-b", lease_seconds=5.0, heartbeat_timeout=30.0, now=106.0
    )
    assert second is not None
    assert second.attempts == 2
    done = store.complete_task(second.task_id, "worker-b", {"ok": True})
    assert done.state == TaskState.SUCCEEDED
    with pytest.raises(RuntimeError, match="not leased"):
        store.complete_task(first.task_id, "worker-a", {"late": True})


def test_execution_lock_prevents_competing_owner_and_can_be_renewed(tmp_path):
    store = make_store(tmp_path)
    assert store.acquire_lock("cycle:e1", "owner-a", ttl_seconds=10, now=100.0)
    assert not store.acquire_lock("cycle:e1", "owner-b", ttl_seconds=10, now=105.0)
    assert store.renew_lock("cycle:e1", "owner-a", ttl_seconds=10, now=106.0)
    assert store.release_lock("cycle:e1", "owner-a")
    assert store.acquire_lock("cycle:e1", "owner-b", ttl_seconds=10, now=107.0)


def test_worker_agent_runs_async_handler_and_attaches_assignment(tmp_path):
    store = make_store(tmp_path)

    async def handler(payload):
        await asyncio.sleep(0)
        return {"value": payload["value"] + 1}

    agent = WorkerAgent(
        store,
        "worker",
        ("backend",),
        handlers={"increment": handler},
    )
    task = store.submit_task(
        execution_id="e1",
        name="increment",
        capability="backend",
        payload={"value": 2},
        idempotency_key="e1:increment",
    )
    result = asyncio.run(agent.run_once())
    assert result is not None
    assert result.state == TaskState.SUCCEEDED
    assert result.result == {
        "value": 3,
        "worker_id": "worker",
        "task_id": task.task_id,
    }


def test_distributed_project_cycle_uses_three_workers_and_reaches_approval(tmp_path):
    source = create_phase22d_source(tmp_path)
    store = make_store(tmp_path)
    cycle = DistributedProjectCycle(store=store)
    result = cycle.execute(
        execution_id="phase23-test",
        source_directory=source,
        output_root=tmp_path / "output",
    )
    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.blocking_findings == ()
    assert result.rework_plan == ()
    assert result.tasks_total == 6
    assert result.tasks_succeeded == 6
    assert result.tasks_dead_lettered == 0
    assert result.workers_used == (
        "worker-architecture-quality",
        "worker-product",
        "worker-security-operations",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == 23
    assert manifest["fabric"]["queue"] == "sqlite-durable"
    assert manifest["fabric"]["task_leases"] is True
    assert manifest["fabric"]["idempotency_keys"] is True
    assert manifest["fabric"]["dead_letter_queue"] is True
    assert manifest["summary"]["tasks_succeeded"] == 6
    assert manifest["proof"]["multiple_workers_used"] is True
    assert manifest["proof"]["all_six_departments_distributed"] is True
    assert manifest["proof"]["network_used"] is False
    assert manifest["proof"]["production_modified"] is False
    assert all(item["state"] == "succeeded" for item in manifest["tasks"])
    assert result.report_path.is_file()


def test_dead_lettered_department_blocks_chief_review_truthfully(tmp_path):
    source = create_phase22d_source(tmp_path)
    store = make_store(tmp_path)
    cycle = DistributedProjectCycle(store=store, maximum_attempts=2)
    good = cycle._verify_department_evidence

    def handler(payload):
        if payload["department"] == "Backend":
            raise RuntimeError("simulated backend worker failure")
        return good(payload)

    handlers = {"department.verify-evidence": handler}
    workers = (
        WorkerAgent(store, "w1", ("architecture", "quality"), handlers=handlers),
        WorkerAgent(store, "w2", ("backend", "frontend"), handlers=handlers),
        WorkerAgent(store, "w3", ("security", "devops"), handlers=handlers),
    )
    result = cycle.execute(
        execution_id="phase23-dead-letter",
        source_directory=source,
        output_root=tmp_path / "output",
        workers=workers,
    )
    assert result.approved is False
    assert result.tasks_dead_lettered == 1
    assert any("Backend" in item for item in result.blocking_findings)
    letters = store.list_dead_letters("phase23-dead-letter")
    assert len(letters) == 1
    assert letters[0].payload["department"] == "Backend"
    assert letters[0].attempts == 2


def test_source_hash_mismatch_is_rejected_before_tasks_are_submitted(tmp_path):
    source = create_phase22d_source(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    target = source / manifest["departments"][0]["path"]
    target.write_text(target.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    store = make_store(tmp_path)
    cycle = DistributedProjectCycle(store=store)
    with pytest.raises(DistributedProjectCycleValidationError, match="corrupted"):
        cycle.execute(
            execution_id="phase23-tampered",
            source_directory=source,
            output_root=tmp_path / "output",
        )
    assert store.list_tasks("phase23-tampered") == ()


@pytest.mark.parametrize("execution_id", ("../escape", "nested/path", "/absolute", "..", ".", "a\\b"))
def test_execution_id_path_traversal_is_rejected(tmp_path, execution_id):
    source = create_phase22d_source(tmp_path)
    cycle = DistributedProjectCycle(store=make_store(tmp_path))
    with pytest.raises(ValueError):
        cycle.execute(
            execution_id=execution_id,
            source_directory=source,
            output_root=tmp_path / "output",
        )


def test_output_root_must_be_absolute(tmp_path, monkeypatch):
    source = create_phase22d_source(tmp_path)
    cycle = DistributedProjectCycle(store=make_store(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        cycle.execute(
            execution_id="phase23-relative",
            source_directory=source,
            output_root="relative-output",
        )


def test_existing_execution_is_not_replaced(tmp_path):
    source = create_phase22d_source(tmp_path)
    cycle = DistributedProjectCycle(store=make_store(tmp_path))
    result = cycle.execute(
        execution_id="phase23-once",
        source_directory=source,
        output_root=tmp_path / "output",
    )
    before = result.manifest_path.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        cycle.execute(
            execution_id="phase23-once",
            source_directory=source,
            output_root=tmp_path / "output",
        )
    assert result.manifest_path.read_bytes() == before


def test_project_cycle_source_has_no_shell_network_or_provider_dependency():
    source = inspect.getsource(project_cycle_module)
    forbidden = (
        "import subprocess",
        "from subprocess",
        "os.system(",
        "shell=True",
        "urllib",
        "requests.",
        "OpenAI",
        "Anthropic",
        "Ollama",
    )
    assert not any(item in source for item in forbidden)
