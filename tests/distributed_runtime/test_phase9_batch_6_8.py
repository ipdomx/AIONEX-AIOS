from datetime import datetime, timedelta, timezone

from aios.distributed_runtime.cluster_manager import ClusterManager, ClusterNode, NodeState
from aios.distributed_runtime.orchestrator import DistributedOrchestrator, WorkflowState, WorkflowStep
from aios.distributed_runtime.service_discovery import ServiceDiscoveryRegistry, ServiceInstance


def test_service_discovery_filters_stale_and_capabilities() -> None:
    now = datetime.now(timezone.utc)
    registry = ServiceDiscoveryRegistry(stale_after=timedelta(seconds=30))
    registry.register(ServiceInstance("runtime", "a", "http://a", frozenset({"gpu"}), last_seen_at=now))
    registry.register(ServiceInstance("runtime", "b", "http://b", frozenset(), last_seen_at=now - timedelta(minutes=1)))

    matches = registry.discover("runtime", required_capabilities={"gpu"}, now=now)
    assert [item.instance_id for item in matches] == ["a"]
    assert [item.instance_id for item in registry.remove_stale(now=now)] == ["b"]


def test_cluster_selects_least_loaded_node_and_drains() -> None:
    cluster = ClusterManager()
    cluster.join(ClusterNode("a", "http://a", "zone-a", 4, frozenset({"python"}), active_tasks=3))
    cluster.join(ClusterNode("b", "http://b", "zone-b", 4, frozenset({"python"}), active_tasks=1))

    assert cluster.select_node(required_labels=frozenset({"python"})).node_id == "b"
    drained = cluster.drain("b")
    assert drained.state is NodeState.DRAINING
    assert cluster.select_node(required_labels=frozenset({"python"})).node_id == "a"


def test_orchestrator_dependencies_and_failover() -> None:
    cluster = ClusterManager()
    cluster.join(ClusterNode("node-1", "http://node-1", "zone-a", 2, frozenset({"python"})))
    cluster.join(ClusterNode("node-2", "http://node-2", "zone-b", 2, frozenset({"python"})))
    orchestrator = DistributedOrchestrator(cluster)
    workflow = orchestrator.submit([
        WorkflowStep("prepare", frozenset({"python"})),
        WorkflowStep("build", frozenset({"python"}), frozenset({"prepare"})),
    ], workflow_id="wf-1")

    first = orchestrator.schedule_ready("wf-1")
    assert [item.step_id for item in first] == ["prepare"]
    released = orchestrator.recover_node(first[0].node_id)
    assert released == ["wf-1:prepare"]

    retried = orchestrator.schedule_ready("wf-1")
    assert len(retried) == 1
    orchestrator.complete_step("wf-1", "prepare", retried[0].lease_token)
    second = orchestrator.schedule_ready("wf-1")
    assert [item.step_id for item in second] == ["build"]
    completed = orchestrator.complete_step("wf-1", "build", second[0].lease_token)
    assert completed.state is WorkflowState.COMPLETED
    assert workflow.completed_steps == {"prepare", "build"}
