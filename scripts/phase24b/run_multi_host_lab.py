#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from generate_deployment_bundles import HostSpec, generate_material

PROJECT_ROOT = Path("/opt/AIOS")
BASE = Path("/var/tmp/aionex-phase24b")
STATE = BASE / "state/control-plane.sqlite3"
SOURCE = BASE / "source"
CREDENTIALS = BASE / "credentials"
RUNTIME = BASE / "runtime"
EVIDENCE = BASE / "evidence"
SOURCE_PHASE22D = Path(
    "/var/tmp/aionex-phase22d/evidence-closure/phase22d-evidence-closure-v2"
)
COMPOSE_FILE = PROJECT_ROOT / "deploy/phase24b/docker-compose.lab.yml"
PROJECT_NAME = "aionex-phase24b"
NETWORK = "aionex-phase24b-interhost"
EXECUTION_ID = "phase24b-multi-host-lab"
CLUSTER_ID = "aionex-phase24b"
HOSTS = ("host-a", "host-b", "host-c")


def run(
    argv: Sequence[str],
    *,
    cwd: Path = PROJECT_ROOT,
    timeout: int = 180,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"stdout={completed.stdout[-6000:]}\n"
            f"stderr={completed.stderr[-6000:]}"
        )
    return completed


def compose(arguments: Sequence[str], *, timeout: int = 180, check: bool = True):
    return run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            PROJECT_NAME,
            *arguments,
        ],
        timeout=timeout,
        check=check,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_readable_tree(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644)


def chown_tree(root: Path, uid: int = 10001, gid: int = 10001) -> None:
    for path in [root, *root.rglob("*")]:
        os.chown(path, uid, gid, follow_symlinks=False)


def wait_for_container_healthy(container: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        inspected = run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container,
            ],
            timeout=15,
            check=False,
        )
        if inspected.returncode == 0 and inspected.stdout.strip() in {"healthy", "running"}:
            return
        time.sleep(0.5)
    raise TimeoutError(f"container did not become healthy: {container}")


def import_runtime():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from aios.execution_fabric import TaskState
    from aios.multi_host_runtime import HostState, MultiHostProjectCycle

    return TaskState, HostState, MultiHostProjectCycle


def wait_for_host_state(store, host_id: str, expected: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            host = store.get_host(host_id)
        except KeyError:
            time.sleep(0.1)
            continue
        if host.state.value == expected:
            return
        time.sleep(0.1)
    raise TimeoutError(f"host did not reach {expected}: {host_id}")


def wait_for_leader(store, *, excluded: str | None = None, minimum_term: int = 1, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leader = store.get_leader(CLUSTER_ID)
        if leader and leader.term >= minimum_term and leader.host_id != excluded:
            return leader
        time.sleep(0.1)
    raise TimeoutError("eligible multi-host leader was not elected")


def wait_for_recovered_task(cycle, task_id: str, failed_host: str, timeout: float = 45.0):
    TaskState, _, _ = import_runtime()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = cycle.control.fabric.get_task(task_id)
        if (
            task.state == TaskState.SUCCEEDED
            and task.attempts >= 2
            and task.result
            and task.result.get("host_id") != failed_host
        ):
            return task
        if task.state == TaskState.DEAD_LETTER:
            raise RuntimeError("recovered task entered the dead-letter queue")
        time.sleep(0.1)
    raise TimeoutError("partitioned host task was not redistributed")


def cleanup() -> None:
    compose(["down", "--remove-orphans"], timeout=120, check=False)
    run(["docker", "network", "rm", NETWORK], timeout=30, check=False)


def prepare_filesystem() -> dict:
    cleanup()
    if BASE.exists():
        shutil.rmtree(BASE)
    (BASE / "state").mkdir(parents=True, mode=0o2770)
    (BASE / "state").chmod(0o2770)
    RUNTIME.mkdir(parents=True, mode=0o755)
    EVIDENCE.mkdir(parents=True, mode=0o755)
    shutil.copytree(SOURCE_PHASE22D, SOURCE)
    make_readable_tree(SOURCE)

    specs = (
        HostSpec("host-a", "https://host-a:9443", ("architecture",), "lab-docker-host-a"),
        HostSpec(
            "host-b",
            "https://host-b:9443",
            ("backend", "security", "devops"),
            "lab-docker-host-b",
        ),
        HostSpec(
            "host-c",
            "https://host-c:9443",
            ("frontend", "quality", "architecture"),
            "lab-docker-host-c",
        ),
    )
    enrollment = generate_material(CREDENTIALS, CLUSTER_ID, specs)
    chown_tree(CREDENTIALS)
    os.chown(BASE / "state", 10001, 10001)
    return enrollment


def capture_runtime() -> dict:
    artifacts: dict[str, object] = {"log_sha256": {}}
    for host in ("control-plane", *HOSTS):
        container = f"aionex-phase24b-{host}"
        result = run(["docker", "logs", container], timeout=30, check=False)
        log_path = RUNTIME / f"{host}.log"
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        artifacts["log_sha256"][host] = sha256(log_path)
    network = run(["docker", "network", "inspect", NETWORK], timeout=30)
    network_path = RUNTIME / "network-inspect.json"
    network_path.write_text(network.stdout, encoding="utf-8")
    artifacts["network_inspect_sha256"] = sha256(network_path)
    return artifacts


def main() -> int:
    if not SOURCE_PHASE22D.is_dir():
        raise RuntimeError("approved Phase 22D evidence is missing")
    validation_started = time.time()
    os.umask(0o002)
    enrollment = prepare_filesystem()
    TaskState, HostState, MultiHostProjectCycle = import_runtime()

    run(
        [
            "docker",
            "build",
            "-t",
            "aionex-phase24b:local",
            "-f",
            str(PROJECT_ROOT / "deploy/phase24b/Dockerfile"),
            str(PROJECT_ROOT),
        ],
        timeout=900,
    )

    cycle = MultiHostProjectCycle(
        STATE,
        cluster_id=CLUSTER_ID,
        source_directory=SOURCE,
    )
    tasks = cycle.prepare(EXECUTION_ID, slow_department="Architecture", slow_seconds=12.0)
    architecture = next(task for task in tasks if task.payload["department"] == "Architecture")
    chown_tree(BASE / "state")
    (BASE / "state").chmod(0o2770)
    for database_file in (STATE, Path(str(STATE) + "-wal"), Path(str(STATE) + "-shm")):
        if database_file.exists():
            database_file.chmod(0o660)

    try:
        compose(["up", "-d", "control-plane", "host-a"], timeout=180)
        wait_for_container_healthy("aionex-phase24b-control-plane")
        wait_for_host_state(cycle.control, "host-a", HostState.ONLINE.value)
        initial = wait_for_leader(cycle.control, minimum_term=1)
        if initial.host_id != "host-a":
            raise RuntimeError("host-a did not become the deterministic initial leader")
        leased = cycle.wait_for_task_lease(EXECUTION_ID, "Architecture", timeout_seconds=30)
        if leased.lease_owner != "host-a":
            raise RuntimeError("host-a did not lease the controlled slow task")

        compose(["up", "-d", "host-b", "host-c"], timeout=180)
        wait_for_host_state(cycle.control, "host-b", HostState.ONLINE.value)
        wait_for_host_state(cycle.control, "host-c", HostState.ONLINE.value)

        run(["docker", "network", "disconnect", "-f", NETWORK, "aionex-phase24b-host-a"])
        cycle.control.record_event(
            "network-partition-injected",
            "host-a",
            {"network": NETWORK, "task_id": architecture.task_id},
        )
        replacement = wait_for_leader(
            cycle.control,
            excluded="host-a",
            minimum_term=2,
            timeout=30,
        )
        recovered = wait_for_recovered_task(
            cycle,
            architecture.task_id,
            "host-a",
            timeout=45,
        )

        run(["docker", "network", "connect", NETWORK, "aionex-phase24b-host-a"])
        wait_for_host_state(cycle.control, "host-a", HostState.ONLINE.value, timeout=30)
        cycle.control.record_event(
            "network-partition-healed",
            "host-a",
            {"network": NETWORK, "replacement_leader": replacement.host_id},
        )
        cycle.wait_for_terminal(EXECUTION_ID, timeout_seconds=60)
        runtime_artifacts = capture_runtime()
        result = cycle.finalize(
            EXECUTION_ID,
            output_root=EVIDENCE,
            partitioned_host="host-a",
            initial_leader=initial.host_id,
            replacement_leader=replacement.host_id,
            recovered_task_id=recovered.task_id,
            validation_started_at=validation_started,
            deployment_hosts=[item["deployment_host"] for item in enrollment["hosts"]],
            separate_physical_hosts=False,
            runtime_artifacts=runtime_artifacts,
        )
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        if manifest["review"]["foundation_approved"] is not True:
            raise RuntimeError("Phase 24B deployment foundation was not approved")
        if manifest["review"]["activation_approved"] is not False:
            raise RuntimeError("lab simulation must not claim physical-host activation")
        summary = {
            "success": True,
            "execution_id": result.execution_id,
            "foundation_approved": True,
            "activation_approved": False,
            "readiness_score": result.readiness_score,
            "blocking_findings": list(result.blocking_findings),
            "tasks_total": result.tasks_total,
            "tasks_succeeded": result.tasks_succeeded,
            "tasks_dead_lettered": result.tasks_dead_lettered,
            "recovered_tasks": result.recovered_tasks,
            "initial_leader": initial.host_id,
            "replacement_leader": replacement.host_id,
            "partitioned_host": "host-a",
            "hosts_used": list(result.hosts_used),
            "output_directory": str(result.output_directory),
            "production_modified": False,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    except BaseException:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        for host in ("control-plane", *HOSTS):
            container = f"aionex-phase24b-{host}"
            failed = run(["docker", "logs", container], timeout=30, check=False)
            (RUNTIME / f"failure-{host}.log").write_text(
                failed.stdout + failed.stderr,
                encoding="utf-8",
            )
        raise
    finally:
        cleanup()
        if CREDENTIALS.exists():
            shutil.rmtree(CREDENTIALS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
