from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ScalingAction(str, Enum):
    SCALE_OUT = "scale_out"
    SCALE_IN = "scale_in"
    HOLD = "hold"


@dataclass(frozen=True)
class ScalingPolicy:
    min_nodes: int = 1
    max_nodes: int = 20
    target_utilization: float = 0.65
    scale_out_threshold: float = 0.80
    scale_in_threshold: float = 0.35
    backlog_per_node: int = 25

    def __post_init__(self) -> None:
        if self.min_nodes < 1:
            raise ValueError("min_nodes must be at least 1")
        if self.max_nodes < self.min_nodes:
            raise ValueError("max_nodes must be greater than or equal to min_nodes")
        if not 0 < self.target_utilization <= 1:
            raise ValueError("target_utilization must be in (0, 1]")
        if not 0 <= self.scale_in_threshold < self.scale_out_threshold <= 1:
            raise ValueError("invalid scale thresholds")
        if self.backlog_per_node < 1:
            raise ValueError("backlog_per_node must be positive")


@dataclass(frozen=True)
class ScalingDecision:
    action: ScalingAction
    current_nodes: int
    desired_nodes: int
    reason: str


class AutoScaler:
    """Produces deterministic scaling recommendations for the runtime cluster."""

    def __init__(self, policy: ScalingPolicy | None = None) -> None:
        self.policy = policy or ScalingPolicy()

    def decide(
        self,
        *,
        current_nodes: int,
        node_utilizations: Iterable[float],
        queued_tasks: int,
        unavailable_nodes: int = 0,
    ) -> ScalingDecision:
        if current_nodes < 0 or queued_tasks < 0 or unavailable_nodes < 0:
            raise ValueError("cluster metrics cannot be negative")

        values = tuple(node_utilizations)
        for value in values:
            if not 0 <= value <= 1:
                raise ValueError("node utilization must be between 0 and 1")

        average = sum(values) / len(values) if values else 0.0
        healthy_nodes = max(0, current_nodes - unavailable_nodes)
        required_for_backlog = (
            (queued_tasks + self.policy.backlog_per_node - 1)
            // self.policy.backlog_per_node
        )
        # Unavailable nodes remain part of current_nodes but provide no capacity.
        # Request one replacement for each unavailable node before considering
        # utilization or backlog pressure, otherwise a degraded cluster can
        # incorrectly HOLD while its healthy capacity has shrunk.
        replacement_target = current_nodes + unavailable_nodes if unavailable_nodes else 0
        desired = max(
            self.policy.min_nodes,
            healthy_nodes,
            required_for_backlog,
            replacement_target,
        )

        if average >= self.policy.scale_out_threshold or desired > current_nodes:
            desired = min(self.policy.max_nodes, max(current_nodes + 1, desired))
            return ScalingDecision(
                ScalingAction.SCALE_OUT,
                current_nodes,
                desired,
                "high utilization, backlog pressure, or unavailable capacity",
            )

        if (
            average <= self.policy.scale_in_threshold
            and queued_tasks == 0
            and current_nodes > self.policy.min_nodes
        ):
            desired = max(self.policy.min_nodes, current_nodes - 1)
            return ScalingDecision(
                ScalingAction.SCALE_IN,
                current_nodes,
                desired,
                "sustained low utilization with no queued work",
            )

        return ScalingDecision(
            ScalingAction.HOLD,
            current_nodes,
            current_nodes,
            "cluster capacity is within policy targets",
        )
