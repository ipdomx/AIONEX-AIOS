from packages.distributed_runtime.load_balancer import LoadBalancer, RuntimeNode
from packages.distributed_runtime.scaling import AutoScaler, ScalingAction, ScalingPolicy


def test_autoscaler_scales_out_for_backlog() -> None:
    scaler = AutoScaler(ScalingPolicy(min_nodes=1, max_nodes=10, backlog_per_node=10))
    decision = scaler.decide(
        current_nodes=2,
        node_utilizations=[0.55, 0.60],
        queued_tasks=37,
    )
    assert decision.action is ScalingAction.SCALE_OUT
    assert decision.desired_nodes == 4


def test_autoscaler_scales_in_when_idle() -> None:
    scaler = AutoScaler(ScalingPolicy(min_nodes=2, max_nodes=10))
    decision = scaler.decide(
        current_nodes=4,
        node_utilizations=[0.10, 0.20, 0.15, 0.12],
        queued_tasks=0,
    )
    assert decision.action is ScalingAction.SCALE_IN
    assert decision.desired_nodes == 3


def test_autoscaler_replaces_unavailable_capacity() -> None:
    scaler = AutoScaler(ScalingPolicy(min_nodes=2, max_nodes=10))
    decision = scaler.decide(
        current_nodes=3,
        node_utilizations=[0.30, 0.35],
        queued_tasks=40,
        unavailable_nodes=1,
    )
    assert decision.action is ScalingAction.SCALE_OUT
    assert decision.desired_nodes >= 4


def test_load_balancer_skips_unhealthy_and_draining_nodes() -> None:
    balancer = LoadBalancer()
    selected = balancer.select(
        [
            RuntimeNode("node-a", capacity=8, active_tasks=1, healthy=False),
            RuntimeNode("node-b", capacity=8, active_tasks=1, draining=True),
            RuntimeNode("node-c", capacity=8, active_tasks=3),
            RuntimeNode("node-d", capacity=8, active_tasks=2),
        ]
    )
    assert selected is not None
    assert selected.node_id == "node-d"


def test_load_balancer_uses_stable_tie_breaker() -> None:
    ranked = LoadBalancer().rank(
        [
            RuntimeNode("node-b", capacity=4, active_tasks=1),
            RuntimeNode("node-a", capacity=4, active_tasks=1),
        ]
    )
    assert [node.node_id for node in ranked] == ["node-a", "node-b"]
