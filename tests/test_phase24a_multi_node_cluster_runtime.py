from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from aios.cluster_runtime import (
    ClusterAuthenticationError,
    ClusterAuthenticator,
    ClusterCycleValidationError,
    ClusterNodeConfig,
    ClusterNodeState,
    ClusterStateStore,
    MultiNodeProjectCycle,
)
from aios.execution_fabric import ExecutionFabricStore, TaskState, WorkerState
from aios.organization import EngineeringOrganization


NODES = ("node-a", "node-b", "node-c")
CAPABILITIES = ("architecture", "backend", "frontend", "security", "quality", "devops")


def make_phase22d_source(tmp_path: Path) -> Path:
    root = tmp_path / "phase22d"
    departments = root / "departments"
    departments.mkdir(parents=True)
    organization = EngineeringOrganization()
    blueprint = organization.plan("AIONEX-AIOS", "Distributed project-cycle validation")
    records = []
    for deliverable in blueprint.deliverables:
        payload = {
            "schema_version": 1,
            "department": deliverable.department,
            "acceptance_criteria": list(deliverable.acceptance_criteria),
            "acceptance_criteria_proven": list(deliverable.acceptance_criteria),
            "tests_passed": True,
            "security_reviewed": True,
            "model_claims_used_as_execution_proof": False,
        }
        path = departments / f"{deliverable.department.lower()}.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        records.append(
            {
                "department": deliverable.department,
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
        "objective": "Distributed project-cycle validation",
        "departments": records,
        "review": {
            "approved": True,
            "readiness_score": 1.0,
            "blocking_findings": [],
            "rework_plan": [],
        },
        "proof": {"production_modified": False},
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return root


def make_credential_files(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for name, content in {
        "secret": "a" * 64,
        "ca": "ca",
        "cert": "cert",
        "key": "key",
    }.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        paths[name] = path
    return paths


def complete_direct_cluster_cycle(
    cycle: MultiNodeProjectCycle,
    execution_id: str,
    output_root: Path,
):
    tasks = cycle.prepare(execution_id, slow_seconds=1.0)
    base = time.time()
    for index, node_id in enumerate(NODES):
        cycle.cluster.register_node(
            node_id,
            f"https://{node_id}:8443",
            CAPABILITIES,
            now=base + index / 10,
        )
        cycle.fabric.register_worker(
            node_id,
            CAPABILITIES,
            max_concurrency=1,
            now=base + index / 10,
        )
    first = cycle.cluster.elect_or_renew_leader(
        "aionex-phase24a",
        "node-a",
        lease_seconds=1.0,
        now=base,
    )
    assert first.term == 1

    architecture = next(
        task for task in tasks if task.payload["department"] == "Architecture"
    )
    cycle.fabric.heartbeat_worker("node-a", now=base)
    claimed = cycle.fabric.claim_task(
        "node-a",
        lease_seconds=1.0,
        heartbeat_timeout=10.0,
        now=base,
    )
    assert claimed and claimed.task_id == architecture.task_id
    cycle.cluster.record_event(
        "node-crash-injected",
        "node-a",
        {"task_id": claimed.task_id, "signal": "SIGKILL"},
        now=base + 0.2,
    )
    cycle.cluster.set_node_state("node-a", ClusterNodeState.FAILED, now=base + 0.2)
    cycle.fabric.set_worker_state("node-a", WorkerState.FAILED)
    cycle.fabric.recover_expired_leases(now=base + 1.1)
    second = cycle.cluster.elect_or_renew_leader(
        "aionex-phase24a",
        "node-b",
        lease_seconds=2.0,
        now=base + 1.1,
    )
    assert second.term == 2

    cycle.fabric.heartbeat_worker("node-b", now=base + 1.1)
    recovered = cycle.fabric.claim_task(
        "node-b",
        lease_seconds=2.0,
        heartbeat_timeout=10.0,
        now=base + 1.1,
    )
    assert recovered and recovered.task_id == architecture.task_id
    cycle.fabric.complete_task(
        recovered.task_id,
        "node-b",
        {
            "department": "Architecture",
            "acceptance_criteria_proven": recovered.payload["acceptance_criteria"],
            "tests_passed": True,
            "security_reviewed": True,
            "worker_id": "node-b",
            "tls_used": True,
            "hmac_authenticated": True,
        },
        now=base + 1.2,
    )

    for index in range(5):
        worker = "node-b" if index % 2 == 0 else "node-c"
        now = base + 2.0 + index
        cycle.fabric.heartbeat_worker(worker, now=now)
        task = cycle.fabric.claim_task(
            worker,
            lease_seconds=2.0,
            heartbeat_timeout=10.0,
            now=now,
        )
        assert task is not None
        cycle.fabric.complete_task(
            task.task_id,
            worker,
            {
                "department": task.payload["department"],
                "acceptance_criteria_proven": task.payload["acceptance_criteria"],
                "tests_passed": True,
                "security_reviewed": True,
                "worker_id": worker,
                "tls_used": True,
                "hmac_authenticated": True,
            },
            now=now + 0.1,
        )

    cycle.cluster.register_node(
        "node-a",
        "https://node-a:8443",
        CAPABILITIES,
        now=base + 10.0,
    )
    cycle.cluster.record_event(
        "node-rejoined",
        "node-a",
        {"replacement_leader": "node-b"},
        now=base + 10.0,
    )
    for observer in NODES:
        for peer in NODES:
            if observer == peer:
                continue
            cycle.cluster.record_peer_observation(
                observer,
                peer,
                healthy=True,
                tls_verified=True,
                authenticated=True,
                latency_ms=1.0,
                now=base + 10.0,
            )
    return cycle.finalize(
        execution_id,
        output_root=output_root,
        failed_node="node-a",
        initial_leader="node-a",
        replacement_leader="node-b",
        recovered_task_id=architecture.task_id,
        simulation_started_at=time.time() - 1.0,
    )


def test_authenticator_signs_and_verifies_exact_request():
    auth = ClusterAuthenticator(b"x" * 32)
    body = b'{"node":"a"}'
    headers = auth.sign("node-a", "POST", "/v1/cluster/heartbeat", body, timestamp=100)
    identity = auth.verify(
        headers,
        "POST",
        "/v1/cluster/heartbeat",
        body,
        now=100,
    )
    assert identity.node_id == "node-a"
    assert identity.timestamp == 100
    assert len(identity.body_sha256) == 64


def test_authenticator_rejects_body_tampering():
    auth = ClusterAuthenticator(b"x" * 32)
    headers = auth.sign("node-a", "POST", "/x", b"original", timestamp=100)
    with pytest.raises(ClusterAuthenticationError, match="signature"):
        auth.verify(headers, "POST", "/x", b"tampered", now=100)


def test_authenticator_rejects_stale_timestamp():
    auth = ClusterAuthenticator(b"x" * 32, maximum_clock_skew_seconds=5)
    headers = auth.sign("node-a", "GET", "/x", timestamp=100)
    with pytest.raises(ClusterAuthenticationError, match="stale"):
        auth.verify(headers, "GET", "/x", now=106)


def test_authenticator_requires_strong_secret():
    with pytest.raises(ValueError, match="32 bytes"):
        ClusterAuthenticator(b"short")


def test_authenticator_repr_never_contains_secret():
    secret = b"z" * 32
    assert secret.decode() not in repr(ClusterAuthenticator(secret))
    assert "[REDACTED]" in repr(ClusterAuthenticator(secret))


def test_cluster_state_registers_membership_and_secure_discovery(tmp_path):
    store = ClusterStateStore(tmp_path / "cluster.sqlite3")
    for node in NODES:
        store.register_node(node, f"https://{node}:8443", CAPABILITIES)
    store.record_peer_observation(
        "node-a",
        "node-b",
        healthy=True,
        tls_verified=True,
        authenticated=True,
        latency_ms=2.5,
    )
    summary = store.summary("cluster")
    assert summary["nodes_total"] == 3
    assert summary["nodes"]["online"] == 3
    assert summary["secure_peer_observations"] == 1


def test_leader_election_renews_without_changing_term(tmp_path):
    store = ClusterStateStore(tmp_path / "cluster.sqlite3")
    store.register_node("node-a", "https://node-a:8443", CAPABILITIES, now=1)
    first = store.elect_or_renew_leader("cluster", "node-a", lease_seconds=3, now=1)
    renewed = store.elect_or_renew_leader("cluster", "node-a", lease_seconds=3, now=2)
    assert first.term == renewed.term == 1
    assert renewed.node_id == "node-a"
    assert len(store.leader_history("cluster")) == 1


def test_leader_failover_increments_term(tmp_path):
    store = ClusterStateStore(tmp_path / "cluster.sqlite3")
    store.register_node("node-a", "https://node-a:8443", CAPABILITIES, now=1)
    store.register_node("node-b", "https://node-b:8443", CAPABILITIES, now=1)
    store.elect_or_renew_leader("cluster", "node-a", lease_seconds=1, now=1)
    failover = store.elect_or_renew_leader("cluster", "node-b", lease_seconds=2, now=2.1)
    assert failover.node_id == "node-b"
    assert failover.term == 2
    assert [item["event"] for item in store.leader_history("cluster")] == [
        "leader-elected",
        "leader-failover",
    ]


def test_live_leader_cannot_be_preempted(tmp_path):
    store = ClusterStateStore(tmp_path / "cluster.sqlite3")
    store.register_node("node-a", "https://node-a:8443", CAPABILITIES, now=1)
    store.register_node("node-b", "https://node-b:8443", CAPABILITIES, now=1)
    store.elect_or_renew_leader("cluster", "node-a", lease_seconds=10, now=1)
    observed = store.elect_or_renew_leader("cluster", "node-b", lease_seconds=10, now=2)
    assert observed.node_id == "node-a"
    assert observed.term == 1


def test_stale_nodes_expire(tmp_path):
    store = ClusterStateStore(tmp_path / "cluster.sqlite3")
    store.register_node("node-a", "https://node-a:8443", CAPABILITIES, now=1)
    assert store.expire_stale_nodes(2, now=4) == ("node-a",)
    assert store.get_node("node-a").state == ClusterNodeState.OFFLINE


def test_cluster_and_execution_fabric_share_one_sqlite_database(tmp_path):
    path = tmp_path / "cluster.sqlite3"
    cluster = ClusterStateStore(path)
    fabric = ExecutionFabricStore(path)
    cluster.register_node("node-a", "https://node-a:8443", CAPABILITIES)
    fabric.register_worker("node-a", CAPABILITIES)
    assert cluster.get_node("node-a").node_id == fabric.get_worker("node-a").worker_id


def test_node_config_requires_https_and_absolute_paths(tmp_path):
    credentials = make_credential_files(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    config = ClusterNodeConfig(
        cluster_id="cluster",
        node_id="node-a",
        service_url="http://node-a:8443",
        peers={},
        capabilities=CAPABILITIES,
        state_path=tmp_path / "state.sqlite3",
        secret_file=credentials["secret"],
        ca_file=credentials["ca"],
        cert_file=credentials["cert"],
        key_file=credentials["key"],
        source_root=source,
    )
    with pytest.raises(ValueError, match="HTTPS"):
        config.validate()


def test_node_config_rejects_unsafe_timing(tmp_path):
    credentials = make_credential_files(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    config = ClusterNodeConfig(
        cluster_id="cluster",
        node_id="node-a",
        service_url="https://node-a:8443",
        peers={},
        capabilities=CAPABILITIES,
        state_path=tmp_path / "state.sqlite3",
        secret_file=credentials["secret"],
        ca_file=credentials["ca"],
        cert_file=credentials["cert"],
        key_file=credentials["key"],
        source_root=source,
        heartbeat_interval=4,
        heartbeat_timeout=3,
    )
    with pytest.raises(ValueError, match="shorter"):
        config.validate()


def test_cycle_prepares_exactly_six_idempotent_tasks(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiNodeProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    first = cycle.prepare("execution")
    second = cycle.prepare("execution")
    assert len(first) == len(second) == 6
    assert [task.task_id for task in first] == [task.task_id for task in second]
    assert {task.payload["department"] for task in first} == set(
        EngineeringOrganization.DEFAULT_DEPARTMENTS
    )


def test_cycle_rejects_tampered_phase22d_receipt(tmp_path):
    source = make_phase22d_source(tmp_path)
    (source / "departments/backend.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ClusterCycleValidationError, match="hash mismatch"):
        MultiNodeProjectCycle(tmp_path / "state.sqlite3", source_directory=source)


def test_lease_expiry_redistributes_task_without_duplicate_success(tmp_path):
    store = ExecutionFabricStore(tmp_path / "state.sqlite3")
    store.register_worker("node-a", CAPABILITIES, now=1)
    store.register_worker("node-b", CAPABILITIES, now=1)
    task = store.submit_task(
        execution_id="execution",
        name="phase24a.department",
        capability="architecture",
        payload={"department": "Architecture"},
        idempotency_key="execution:architecture",
        max_attempts=3,
        now=1,
    )
    claimed = store.claim_task("node-a", lease_seconds=1, heartbeat_timeout=10, now=1)
    assert claimed and claimed.task_id == task.task_id
    assert store.recover_expired_leases(now=2.1) == (task.task_id,)
    recovered = store.claim_task("node-b", lease_seconds=2, heartbeat_timeout=10, now=2.1)
    assert recovered and recovered.attempts == 2
    completed = store.complete_task(task.task_id, "node-b", {"worker_id": "node-b"}, now=2.2)
    assert completed.state == TaskState.SUCCEEDED
    assert len(store.list_tasks("execution")) == 1
    with pytest.raises(RuntimeError, match="not leased"):
        store.complete_task(task.task_id, "node-a", {"worker_id": "node-a"}, now=2.3)


def test_full_direct_cycle_proves_failover_and_closes_review(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiNodeProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    result = complete_direct_cluster_cycle(cycle, "phase24a-test", tmp_path / "output")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.tasks_total == result.tasks_succeeded == 6
    assert result.recovered_tasks == 1
    assert set(result.leaders_observed) == {"node-a", "node-b"}
    assert manifest["proof"]["leader_failover_observed"] is True
    assert manifest["proof"]["leased_task_recovered"] is True
    assert manifest["proof"]["service_discovery_complete"] is True
    assert manifest["proof"]["production_modified"] is False


def test_cycle_output_is_immutable_by_execution_id(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiNodeProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    complete_direct_cluster_cycle(cycle, "phase24a-test", tmp_path / "output")
    with pytest.raises(FileExistsError):
        cycle.finalize(
            "phase24a-test",
            output_root=tmp_path / "output",
            failed_node="node-a",
            initial_leader="node-a",
            replacement_leader="node-b",
            recovered_task_id=cycle.fabric.list_tasks("phase24a-test")[0].task_id,
            simulation_started_at=time.time(),
        )


def test_compose_uses_internal_network_loopback_ports_and_read_only_mounts():
    compose = Path("deploy/phase24a/docker-compose.yml").read_text(encoding="utf-8")
    assert "internal: true" in compose
    assert '"127.0.0.1:19401:8443"' in compose
    assert '"127.0.0.1:19402:8443"' in compose
    assert '"127.0.0.1:19403:8443"' in compose
    assert "read_only: true" in compose
    assert 'user: "10001:10001"' in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "no-new-privileges:true" in compose
    assert compose.count("read_only: true") >= 4


def test_compose_defines_exactly_three_cluster_nodes():
    compose = Path("deploy/phase24a/docker-compose.yml").read_text(encoding="utf-8")
    for node in NODES:
        assert f"  {node}:" in compose
        assert f"AIOS_CLUSTER_NODE_ID: {node}" in compose
    assert "web-dashboard" not in compose
    assert ".env.production" not in compose


def test_dockerfile_runs_as_non_root_and_drops_bytecode():
    dockerfile = Path("deploy/phase24a/Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001:10001" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "aios.cluster_runtime.node"]' in dockerfile


def test_simulation_injects_sigkill_and_always_tears_down():
    script = Path("scripts/phase24a/run_docker_simulation.py").read_text(encoding="utf-8")
    assert '"kill", "--signal", "KILL"' in script
    assert 'compose(["down", "--remove-orphans"]' in script
    assert "finally:" in script
    assert "shell=True" not in script


def test_cluster_runtime_source_contains_no_provider_key_or_cloud_endpoint():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/aios/cluster_runtime").glob("*.py")
    )
    assert "OPENAI_API_KEY" not in source
    assert "api.openai.com" not in source
    assert "provider_key_used\": False" in source


def test_phase24a_manifest_never_claims_production_mutation(tmp_path):
    source = make_phase22d_source(tmp_path)
    cycle = MultiNodeProjectCycle(tmp_path / "state.sqlite3", source_directory=source)
    result = complete_direct_cluster_cycle(cycle, "phase24a-test", tmp_path / "output")
    encoded = result.manifest_path.read_text(encoding="utf-8")
    assert '"production_modified": false' in encoded
    assert '"cloud_request_sent": false' in encoded
    assert '"provider_key_used": false' in encoded
