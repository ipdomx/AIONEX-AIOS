from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest

from aios.execution_fabric import TaskState
from aios.multi_host_runtime import (
    HostRequestAuthenticator,
    HostState,
    MultiHostAuthenticationError,
    MultiHostControlPlane,
    MultiHostControlStore,
    MultiHostCycleValidationError,
    MultiHostProjectCycle,
)
from aios.multi_host_runtime.client import MultiHostControlClient


DEPARTMENTS = ("Architecture", "Backend", "Frontend", "Security", "Quality", "DevOps")
CRITERIA = {
    "Architecture": ("architecture documented", "dependencies mapped", "failure modes reviewed"),
    "Backend": ("interfaces implemented", "data integrity verified", "performance tested"),
    "Frontend": ("user flows complete", "accessibility checked", "rendering performance tested"),
    "Security": ("threat model complete", "critical findings resolved", "controls verified"),
    "Quality": ("test plan complete", "regression suite passed", "evidence archived"),
    "DevOps": ("deployment reproducible", "rollback tested", "observability enabled"),
}


def make_phase22d_source(tmp_path: Path) -> Path:
    root = tmp_path / "phase22d"
    departments = root / "departments"
    departments.mkdir(parents=True)
    records = []
    for department in DEPARTMENTS:
        payload = {
            "schema_version": 1,
            "department": department,
            "acceptance_criteria": list(CRITERIA[department]),
            "acceptance_criteria_proven": list(CRITERIA[department]),
            "tests_passed": True,
            "security_reviewed": True,
            "production_modified": False,
        }
        path = departments / f"{department.lower()}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        records.append(
            {
                "department": department,
                "path": f"departments/{path.name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "tests_passed": True,
                "security_reviewed": True,
            }
        )
    manifest = {
        "schema_version": 1,
        "phase": "22D",
        "execution_id": "phase22d-test",
        "project": "AIONEX-AIOS",
        "objective": "Validate a multi-host project cycle",
        "departments": records,
        "review": {
            "approved": True,
            "readiness_score": 1.0,
            "blocking_findings": [],
            "rework_plan": [],
        },
        "proof": {"production_modified": False},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def fingerprint(index: int) -> str:
    return f"{index:064x}"


def enroll_and_register(store: MultiHostControlStore, now: float = 100.0) -> None:
    specifications = (
        ("host-a", ("architecture",), fingerprint(1)),
        ("host-b", ("backend", "security", "devops"), fingerprint(2)),
        ("host-c", ("frontend", "quality", "architecture"), fingerprint(3)),
    )
    for offset, (host_id, capabilities, cert) in enumerate(specifications):
        store.enroll_host(
            host_id,
            f"https://{host_id}:9443",
            capabilities,
            cert,
            metadata={"deployment_host": f"server-{host_id}"},
            now=now + offset / 10,
        )
        store.register_host(
            host_id,
            cert,
            service_url=f"https://{host_id}:9443",
            capabilities=capabilities,
            now=now + offset / 10,
        )


def task_result(task, host_id: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": task.task_id,
        "host_id": host_id,
        "department": task.payload["department"],
        "source_path": task.payload["source_path"],
        "source_sha256": task.payload["source_sha256"],
        "passed_criteria": list(task.payload["acceptance_criteria"]),
        "tests_passed": True,
        "security_reviewed": True,
        "production_modified": False,
        "source_execution_modified": False,
    }


def complete_direct_lab(cycle: MultiHostProjectCycle, execution_id: str, output: Path):
    tasks = cycle.prepare(execution_id, slow_seconds=1.0)
    base = time.time() + 0.5
    enroll_and_register(cycle.control, now=base)
    initial = cycle.control.elect_or_renew_leader(
        cycle.cluster_id,
        "host-a",
        lease_seconds=1.0,
        now=base,
    )
    architecture = next(task for task in tasks if task.payload["department"] == "Architecture")
    claimed = cycle.control.fabric.claim_task(
        "host-a",
        lease_seconds=1.0,
        heartbeat_timeout=10.0,
        now=base,
    )
    assert claimed and claimed.task_id == architecture.task_id
    cycle.control.record_event(
        "network-partition-injected",
        "host-a",
        {"task_id": architecture.task_id},
        now=base + 0.5,
    )
    cycle.control.heartbeat_host("host-b", fingerprint(2), now=base + 2.0)
    cycle.control.heartbeat_host("host-c", fingerprint(3), now=base + 2.0)
    maintenance = cycle.control.maintenance(1.5, now=base + 2.0)
    assert architecture.task_id in maintenance["recovered_tasks"]
    replacement = cycle.control.elect_or_renew_leader(
        cycle.cluster_id,
        "host-b",
        lease_seconds=1.0,
        now=base + 2.0,
    )
    assert replacement.term == initial.term + 1

    recovered = cycle.control.fabric.claim_task(
        "host-c",
        lease_seconds=5.0,
        heartbeat_timeout=10.0,
        now=base + 2.0,
    )
    assert recovered and recovered.task_id == architecture.task_id
    cycle.control.fabric.complete_task(
        recovered.task_id,
        "host-c",
        task_result(recovered, "host-c"),
        now=base + 2.1,
    )

    for _ in range(10):
        progress = False
        for host_id in ("host-b", "host-c"):
            cycle.control.fabric.heartbeat_worker(host_id, now=base + 2.2)
            task = cycle.control.fabric.claim_task(
                host_id,
                lease_seconds=5.0,
                heartbeat_timeout=10.0,
                now=base + 2.2,
            )
            if task is None:
                continue
            cycle.control.fabric.complete_task(
                task.task_id,
                host_id,
                task_result(task, host_id),
                now=base + 2.3,
            )
            progress = True
        if not progress:
            break

    cycle.control.heartbeat_host("host-a", fingerprint(1), now=base + 3.0)
    cycle.control.record_event(
        "network-partition-healed",
        "host-a",
        {"replacement_leader": replacement.host_id},
        now=base + 3.0,
    )
    result = cycle.finalize(
        execution_id,
        output_root=output,
        partitioned_host="host-a",
        initial_leader=initial.host_id,
        replacement_leader=replacement.host_id,
        recovered_task_id=architecture.task_id,
        validation_started_at=time.time() - 1,
        deployment_hosts=("lab-a", "lab-b", "lab-c"),
        separate_physical_hosts=False,
        runtime_artifacts={"lab": True},
    )
    return result


def test_host_authenticator_signs_and_verifies_and_redacts_secret():
    auth = HostRequestAuthenticator("host-a", b"a" * 32)
    body = b'{"x":1}'
    headers = auth.sign("POST", "/v1/tasks/claim", body, timestamp=100, nonce="n-1")
    verified = auth.verify(headers, "POST", "/v1/tasks/claim", body, now=100)
    assert verified.host_id == "host-a"
    assert verified.nonce == "n-1"
    assert "a" * 32 not in repr(auth)


def test_host_authenticator_rejects_tamper_stale_and_wrong_identity():
    auth = HostRequestAuthenticator("host-a", b"b" * 32, maximum_clock_skew_seconds=5)
    headers = auth.sign("POST", "/x", b"body", timestamp=100, nonce="n")
    with pytest.raises(MultiHostAuthenticationError):
        auth.verify(headers, "POST", "/x", b"tampered", now=100)
    with pytest.raises(MultiHostAuthenticationError):
        auth.verify(headers, "POST", "/x", b"body", now=106)
    headers["X-AIOS-Host"] = "host-b"
    with pytest.raises(MultiHostAuthenticationError):
        auth.verify(headers, "POST", "/x", b"body", now=100)


def test_nonce_replay_is_rejected_by_durable_store(tmp_path):
    store = MultiHostControlStore(tmp_path / "state.sqlite3")
    store.enroll_host("host-a", "https://host-a:9443", ("architecture",), fingerprint(1))
    assert store.consume_nonce("host-a", "nonce", now=100) is True
    assert store.consume_nonce("host-a", "nonce", now=100) is False
    assert store.consume_nonce("host-a", "nonce", now=401) is True


def test_enrollment_binds_host_to_certificate_and_attributes(tmp_path):
    store = MultiHostControlStore(tmp_path / "state.sqlite3")
    enrolled = store.enroll_host(
        "host-a",
        "https://host-a:9443",
        ("architecture",),
        fingerprint(1),
    )
    assert enrolled.state == HostState.ENROLLED
    registered = store.register_host(
        "host-a",
        fingerprint(1),
        service_url="https://host-a:9443",
        capabilities=("architecture",),
    )
    assert registered.state == HostState.ONLINE
    with pytest.raises(PermissionError):
        store.heartbeat_host("host-a", fingerprint(2))
    with pytest.raises(ValueError):
        store.enroll_host(
            "host-a",
            "https://changed:9443",
            ("architecture",),
            fingerprint(1),
        )


def test_leader_terms_and_fencing_tokens_change_after_expiry(tmp_path):
    store = MultiHostControlStore(tmp_path / "state.sqlite3")
    enroll_and_register(store)
    first = store.elect_or_renew_leader("cluster", "host-a", lease_seconds=1, now=100)
    blocked = store.elect_or_renew_leader("cluster", "host-b", lease_seconds=1, now=100.5)
    second = store.elect_or_renew_leader("cluster", "host-b", lease_seconds=1, now=101.1)
    assert blocked.host_id == "host-a"
    assert second.host_id == "host-b"
    assert second.term == first.term + 1
    assert second.fencing_token != first.fencing_token
    assert [row["event"] for row in store.leader_history("cluster")] == [
        "leader-elected",
        "leader-failover",
    ]


def test_stale_host_expiration_recovers_leased_task(tmp_path):
    store = MultiHostControlStore(tmp_path / "state.sqlite3")
    enroll_and_register(store)
    task = store.fabric.submit_task(
        execution_id="e",
        name="phase24b.department",
        capability="architecture",
        payload={"department": "Architecture"},
        idempotency_key="e:architecture",
        max_attempts=2,
        now=100,
    )
    claimed = store.fabric.claim_task(
        "host-a",
        lease_seconds=1,
        heartbeat_timeout=10,
        now=100,
    )
    assert claimed and claimed.task_id == task.task_id
    maintenance = store.maintenance(1.5, now=102)
    assert "host-a" in maintenance["expired_hosts"]
    assert task.task_id in maintenance["recovered_tasks"]
    assert store.fabric.get_task(task.task_id).state == TaskState.RETRY_WAIT


def test_control_plane_direct_registration_claim_and_completion(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "host-a.key").write_text((b"x" * 32).hex(), encoding="utf-8")
    runtime = MultiHostControlPlane(tmp_path / "state.sqlite3", "cluster", secrets)
    runtime.store.enroll_host(
        "host-a",
        "https://host-a:9443",
        ("architecture",),
        fingerprint(1),
    )
    registered = runtime.register_host(
        "host-a",
        fingerprint(1),
        {"service_url": "https://host-a:9443", "capabilities": ["architecture"]},
    )
    assert registered["accepted"] is True
    task = runtime.store.fabric.submit_task(
        execution_id="e",
        name="phase24b.department",
        capability="architecture",
        payload={"department": "Architecture"},
        idempotency_key="e:architecture",
    )
    claimed = runtime.claim_task("host-a", fingerprint(1))["task"]
    assert claimed["task_id"] == task.task_id
    completed = runtime.complete_task(
        "host-a",
        fingerprint(1),
        {"task_id": task.task_id, "result": {"ok": True}},
    )["task"]
    assert completed["state"] == "succeeded"


def test_client_rejects_non_https_or_path_base_url(tmp_path):
    for name in ("ca.crt", "host.crt", "host.key"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    auth = HostRequestAuthenticator("host-a", b"x" * 32)
    with pytest.raises(ValueError):
        MultiHostControlClient(
            "http://control-plane:9443",
            auth,
            tmp_path / "ca.crt",
            tmp_path / "host.crt",
            tmp_path / "host.key",
        )
    with pytest.raises(ValueError):
        MultiHostControlClient(
            "https://control-plane:9443/api",
            auth,
            tmp_path / "ca.crt",
            tmp_path / "host.crt",
            tmp_path / "host.key",
        )


def test_phase22d_tamper_is_rejected(tmp_path):
    source = make_phase22d_source(tmp_path)
    path = source / "departments/backend.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(MultiHostCycleValidationError, match="hash mismatch"):
        MultiHostProjectCycle(tmp_path / "state.sqlite3", source_directory=source)


def test_full_foundation_lab_cycle_is_approved_but_physical_activation_is_not(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiHostProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    result = complete_direct_lab(cycle, "phase24b-test", tmp_path / "output")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.approved is False
    assert result.readiness_score == 0.95
    assert result.tasks_succeeded == 6
    assert result.tasks_dead_lettered == 0
    assert result.recovered_tasks == 1
    assert manifest["review"]["foundation_approved"] is True
    assert manifest["review"]["activation_approved"] is False
    assert manifest["proof"]["leased_task_recovered"] is True
    assert manifest["proof"]["separate_physical_hosts"] is False
    assert manifest["proof"]["production_modified"] is False
    assert "physical-host activation" in " ".join(result.blocking_findings)


def test_cycle_output_is_immutable(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiHostProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    complete_direct_lab(cycle, "phase24b-test", tmp_path / "output")
    with pytest.raises(FileExistsError):
        cycle.finalize(
            "phase24b-test",
            output_root=tmp_path / "output",
            partitioned_host="host-a",
            initial_leader="host-a",
            replacement_leader="host-b",
            recovered_task_id=cycle.control.fabric.list_tasks("phase24b-test")[0].task_id,
            validation_started_at=time.time(),
            deployment_hosts=("a", "b", "c"),
            separate_physical_hosts=False,
        )


def test_deployment_bundle_generator_creates_unique_certificates_and_external_secrets(tmp_path):
    root = tmp_path / "bundles"
    completed = subprocess.run(
        [
            "python3",
            "scripts/phase24b/generate_deployment_bundles.py",
            "--root",
            str(root),
            "--cluster-id",
            "test-cluster",
            "--host",
            "host-a|https://host-a:9443|architecture|server-a",
            "--host",
            "host-b|https://host-b:9443|backend|server-b",
            "--host",
            "host-c|https://host-c:9443|frontend|server-c",
        ],
        cwd="/opt/AIOS",
        text=True,
        capture_output=True,
        check=True,
    )
    manifest = json.loads((root / "control-plane/enrollment.json").read_text())
    fingerprints = {item["certificate_sha256"] for item in manifest["hosts"]}
    assert len(fingerprints) == 3
    assert manifest["private_keys_committed"] is False
    assert not (root / "pki/ca.key").exists()
    for host in ("host-a", "host-b", "host-c"):
        assert (root / host / "host-private.key").stat().st_mode & 0o777 == 0o600
        assert (root / host / "host.key").stat().st_mode & 0o777 == 0o600
        assert "CONTROL_PLANE_HOST" in (root / host / "agent.env").read_text()
    assert "test-cluster" in completed.stdout


def test_phase24b_compose_is_internal_non_root_and_read_only():
    compose = Path("deploy/phase24b/docker-compose.lab.yml").read_text(encoding="utf-8")
    assert "internal: true" in compose
    assert 'user: "10001:10001"' in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "127.0.0.1:19600:9443" in compose
    assert "/opt/AIOS/web-dashboard" not in compose
    assert "AIOS_MULTI_HOST_CONTROL_PLANE_URL: https://control-plane:9443" in compose


def test_control_plane_requires_client_certificates_and_nonce_authentication():
    source = Path("src/aios/multi_host_runtime/control_plane.py").read_text(encoding="utf-8")
    assert "context.verify_mode = ssl.CERT_REQUIRED" in source
    assert "consume_nonce" in source
    assert "certificate_sha256" in source
    assert "peer certificate does not match host enrollment" in source


def test_agent_has_no_shared_state_path_and_uses_remote_api():
    source = Path("src/aios/multi_host_runtime/agent.py").read_text(encoding="utf-8")
    assert "ExecutionFabricStore" not in source
    assert "ClusterStateStore" not in source
    assert "AIOS_MULTI_HOST_STATE_PATH" not in source
    assert "/v1/tasks/claim" in source
    assert "/v1/tasks/renew" in source
    assert "/v1/tasks/complete" in source


def test_lab_runner_injects_partition_and_cleans_up():
    source = Path("scripts/phase24b/run_multi_host_lab.py").read_text(encoding="utf-8")
    assert "docker\", \"network\", \"disconnect" in source
    assert "docker\", \"network\", \"connect" in source
    assert "network-partition-injected" in source
    assert "network-partition-healed" in source
    assert "cleanup()" in source
    assert "separate_physical_hosts=False" in source


def test_phase24b_sources_do_not_contain_production_mutation_commands():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/aios/multi_host_runtime").glob("*.py")
    )
    forbidden = (
        "docker-compose.production.yml",
        ".env.production",
        "systemctl restart nginx",
        "web-dashboard-backend-1",
        "cloudflared tunnel",
        "OPENAI_API_KEY",
    )
    assert not any(value in combined for value in forbidden)


def test_generator_includes_control_plane_service_and_runtime_environment(tmp_path):
    root = tmp_path / "bundles"
    subprocess.run(
        [
            "python3",
            "scripts/phase24b/generate_deployment_bundles.py",
            "--root",
            str(root),
            "--cluster-id",
            "test-cluster",
            "--host",
            "host-a|https://host-a:9443|architecture|server-a",
            "--host",
            "host-b|https://host-b:9443|backend|server-b",
            "--host",
            "host-c|https://host-c:9443|frontend|server-c",
        ],
        cwd="/opt/AIOS",
        check=True,
        text=True,
        capture_output=True,
    )
    control_env = (root / "control-plane/control-plane.env").read_text()
    control_unit = (root / "control-plane/aionex-phase24b-control-plane.service").read_text()
    agent_unit = (root / "host-a/aionex-phase24b-agent.service").read_text()
    assert "AIOS_MULTI_HOST_STATE_PATH=/var/lib/aionex/phase24b/control-plane.sqlite3" in control_env
    assert "PYTHONPATH=/opt/aionex-phase24b/src" in control_env
    assert "ExecStart=/usr/bin/python3 -m aios.multi_host_runtime.control_plane" in control_unit
    assert "ExecStart=/usr/bin/python3 -m aios.multi_host_runtime.agent" in agent_unit
    assert "NoNewPrivileges=true" in control_unit
    assert "ProtectSystem=strict" in control_unit


def test_remote_inventory_deployment_is_dry_run_by_default(tmp_path):
    root = tmp_path / "bundles"
    subprocess.run(
        [
            "python3",
            "scripts/phase24b/generate_deployment_bundles.py",
            "--root",
            str(root),
            "--cluster-id",
            "test-cluster",
            "--host",
            "host-a|https://host-a:9443|architecture|server-a",
            "--host",
            "host-b|https://host-b:9443|backend|server-b",
            "--host",
            "host-c|https://host-c:9443|frontend|server-c",
        ],
        cwd="/opt/AIOS",
        check=True,
        text=True,
        capture_output=True,
    )
    inventory = {
        "control_plane": {"host_id": "control-plane", "ssh_target": "root@control.example"},
        "hosts": [
            {"host_id": "host-a", "ssh_target": "root@a.example"},
            {"host_id": "host-b", "ssh_target": "root@b.example"},
            {"host_id": "host-c", "ssh_target": "root@c.example"},
        ],
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    completed = subprocess.run(
        [
            "python3",
            "scripts/phase24b/deploy_inventory.py",
            "--inventory",
            str(inventory_path),
            "--bundle-root",
            str(root),
            "--project-root",
            "/opt/AIOS",
        ],
        cwd="/opt/AIOS",
        check=True,
        text=True,
        capture_output=True,
    )
    plan = json.loads(completed.stdout)
    assert plan["mode"] == "dry-run"
    assert len(plan["targets"]) == 4
    assert plan["production_modified"] is False
    rendered = json.dumps(plan["commands"])
    assert "StrictHostKeyChecking=yes" in rendered
    assert "systemctl enable --now aionex-phase24b-control-plane.service" in rendered
    assert "systemctl enable --now aionex-phase24b-agent.service" in rendered
