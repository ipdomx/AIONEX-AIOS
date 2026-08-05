from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from aios.cluster_runtime import ClusterStateStore, MultiNodeProjectCycle
from aios.execution_fabric import TaskState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "deploy/phase24a/docker-compose.yml"
DEFAULT_ROOT = Path("/var/tmp/aionex-phase24a")
PHASE22D_SOURCE = Path("/var/tmp/aionex-phase22d/evidence-closure/phase22d-evidence-closure-v2")
EXECUTION_ID = "phase24a-multi-node-project-cycle"
NODE_CONTAINERS = {
    "node-a": "aionex-phase24a-node-a",
    "node-b": "aionex-phase24a-node-b",
    "node-c": "aionex-phase24a-node-c",
}


def run(
    argv: Sequence[str],
    *,
    timeout: int = 300,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env or os.environ.copy(),
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"stdout={completed.stdout[-4000:]}\nstderr={completed.stderr[-4000:]}"
        )
    return completed


def compose(
    arguments: Sequence[str],
    *,
    root: Path,
    timeout: int = 600,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AIOS_PHASE24A_ROOT"] = str(root)
    return run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            "aionex-phase24a",
            *arguments,
        ],
        timeout=timeout,
        check=check,
        env=env,
    )


def generate_tls(root: Path) -> None:
    certs = root / "certs"
    private = root / ".private-ca"
    secrets_dir = root / "secrets"
    certs.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)
    secrets_dir.mkdir(parents=True, mode=0o700)

    (secrets_dir / "cluster.key").write_text(secrets.token_hex(48) + "\n", encoding="ascii")
    extension = private / "extensions.cnf"
    extension.write_text(
        "subjectAltName=DNS:node-a,DNS:node-b,DNS:node-c,DNS:localhost,IP:127.0.0.1\n"
        "extendedKeyUsage=serverAuth\n"
        "keyUsage=digitalSignature,keyEncipherment\n",
        encoding="ascii",
    )
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private / "ca.key"),
            "-out",
            str(certs / "ca.crt"),
            "-subj",
            "/CN=AIONEX Phase24A Simulation CA",
            "-days",
            "2",
            "-sha256",
        ],
        timeout=120,
    )
    run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(certs / "cluster.key"),
            "-out",
            str(private / "cluster.csr"),
            "-subj",
            "/CN=node-a",
            "-sha256",
        ],
        timeout=120,
    )
    run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(private / "cluster.csr"),
            "-CA",
            str(certs / "ca.crt"),
            "-CAkey",
            str(private / "ca.key"),
            "-CAcreateserial",
            "-out",
            str(certs / "cluster.crt"),
            "-days",
            "2",
            "-sha256",
            "-extfile",
            str(extension),
        ],
        timeout=120,
    )
    shutil.rmtree(private)
    for path in (certs / "ca.crt", certs / "cluster.crt"):
        path.chmod(0o444)
        os.chown(path, 10001, 10001)
    for path in (certs / "cluster.key", secrets_dir / "cluster.key"):
        path.chmod(0o400)
        os.chown(path, 10001, 10001)
    certs.chmod(0o500)
    secrets_dir.chmod(0o500)
    os.chown(certs, 10001, 10001)
    os.chown(secrets_dir, 10001, 10001)


def wait_secure_discovery(
    store: ClusterStateStore,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    expected = {
        (left, right)
        for left in NODE_CONTAINERS
        for right in NODE_CONTAINERS
        if left != right
    }
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        secure = {
            (item.observer_id, item.peer_id)
            for item in store.list_peer_observations()
            if item.healthy and item.tls_verified and item.authenticated
        }
        if expected <= secure:
            return
        time.sleep(0.2)
    raise TimeoutError("secure service discovery did not cover all node pairs")


def capture_runtime_artifacts(root: Path) -> dict[str, Any]:
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    logs: dict[str, str] = {}
    for node_id, container in NODE_CONTAINERS.items():
        completed = run(
            ["docker", "logs", "--tail", "2000", container],
            timeout=60,
            check=False,
        )
        path = runtime / f"{node_id}.log"
        path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        logs[node_id] = hashlib.sha256(path.read_bytes()).hexdigest()
    inspect = run(
        ["docker", "network", "inspect", "aionex-phase24a-internal"],
        timeout=60,
        check=False,
    )
    network_path = runtime / "network-inspect.json"
    network_path.write_text(inspect.stdout, encoding="utf-8")
    return {
        "log_sha256": logs,
        "network_inspect_sha256": hashlib.sha256(network_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=False)
    if root == Path("/") or not str(root).startswith("/var/tmp/aionex-phase24a"):
        raise ValueError("simulation root must remain under /var/tmp/aionex-phase24a")

    compose(["down", "--remove-orphans"], root=root, timeout=180, check=False)
    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, mode=0o700)
    for directory in (root / "state", root / "runtime"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_copy = root / "source/phase22d"
    source_copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(PHASE22D_SOURCE, source_copy)
    for directory in [source_copy, *[item for item in source_copy.rglob("*") if item.is_dir()]]:
        os.chown(directory, 10001, 10001)
        directory.chmod(0o500)
    for file_path in [item for item in source_copy.rglob("*") if item.is_file()]:
        os.chown(file_path, 10001, 10001)
        file_path.chmod(0o400)
    os.chown(source_copy.parent, 10001, 10001)
    source_copy.parent.chmod(0o500)
    generate_tls(root)

    state_path = root / "state/cluster.sqlite3"
    cycle = MultiNodeProjectCycle(state_path)
    tasks = cycle.prepare(EXECUTION_ID, slow_department="Architecture", slow_seconds=12.0)
    architecture_task = next(
        task for task in tasks if task.payload.get("department") == "Architecture"
    )
    os.chown(root / "state", 10001, 10001)
    (root / "state").chmod(0o700)
    os.chown(state_path, 10001, 10001)
    state_path.chmod(0o600)

    simulation_started_at = time.time()
    initial_leader = ""
    failed_node = ""
    replacement_leader = ""
    runtime_artifacts: dict[str, Any] = {}
    try:
        compose(["build", "node-a"], root=root, timeout=900)
        compose(["up", "-d", "node-a"], root=root, timeout=180)
        cycle.wait_for_nodes({"node-a"}, timeout_seconds=30)
        initial_leader = cycle.wait_for_leader(timeout_seconds=20)
        if initial_leader != "node-a":
            raise RuntimeError(f"node-a was not the initial leader: {initial_leader}")
        leased = cycle.wait_for_task_lease(
            EXECUTION_ID,
            "Architecture",
            timeout_seconds=30,
        )
        if leased.task_id != architecture_task.task_id or leased.lease_owner != "node-a":
            raise RuntimeError("node-a did not lease the controlled recovery task")

        compose(["up", "-d", "node-b", "node-c"], root=root, timeout=180)
        cycle.wait_for_nodes(set(NODE_CONTAINERS), timeout_seconds=30)
        wait_secure_discovery(cycle.cluster, timeout_seconds=30)

        failed_node = leased.lease_owner or ""
        cycle.cluster.record_event(
            "node-crash-injected",
            failed_node,
            {"task_id": leased.task_id, "leader": initial_leader, "signal": "SIGKILL"},
        )
        run(
            ["docker", "kill", "--signal", "KILL", NODE_CONTAINERS[failed_node]],
            timeout=60,
        )
        replacement_leader = cycle.wait_for_leader(
            excluded_node=failed_node,
            minimum_term=2,
            timeout_seconds=30,
        )
        terminal = cycle.wait_for_terminal(EXECUTION_ID, timeout_seconds=90)
        recovered = next(task for task in terminal if task.task_id == leased.task_id)
        if (
            recovered.state != TaskState.SUCCEEDED
            or recovered.attempts < 2
            or not recovered.result
            or recovered.result.get("worker_id") == failed_node
        ):
            raise RuntimeError("the failed node task was not redistributed successfully")

        compose(["up", "-d", "node-a"], root=root, timeout=180)
        cycle.wait_for_nodes(set(NODE_CONTAINERS), timeout_seconds=30)
        wait_secure_discovery(cycle.cluster, timeout_seconds=30)
        cycle.cluster.record_event(
            "node-rejoined",
            failed_node,
            {"replacement_leader": replacement_leader},
        )
        time.sleep(1.0)
        runtime_artifacts = capture_runtime_artifacts(root)
        result = cycle.finalize(
            EXECUTION_ID,
            output_root=root / "evidence",
            failed_node=failed_node,
            initial_leader=initial_leader,
            replacement_leader=replacement_leader,
            recovered_task_id=leased.task_id,
            simulation_started_at=simulation_started_at,
            runtime_artifacts=runtime_artifacts,
        )
        payload = {
            "success": result.approved,
            "execution_id": result.execution_id,
            "output_directory": str(result.output_directory),
            "approved": result.approved,
            "readiness_score": result.readiness_score,
            "tasks_total": result.tasks_total,
            "tasks_succeeded": result.tasks_succeeded,
            "recovered_tasks": result.recovered_tasks,
            "leaders_observed": list(result.leaders_observed),
            "workers_used": list(result.workers_used),
            "failed_node": failed_node,
            "initial_leader": initial_leader,
            "replacement_leader": replacement_leader,
            "runtime_artifacts": runtime_artifacts,
            "production_modified": False,
            "total_duration": result.total_duration,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        if not result.approved:
            return 2
        return 0
    finally:
        if not runtime_artifacts:
            try:
                capture_runtime_artifacts(root)
            except BaseException:
                pass
        compose(["down", "--remove-orphans"], root=root, timeout=180, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
