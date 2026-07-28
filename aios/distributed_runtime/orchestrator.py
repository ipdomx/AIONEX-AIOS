from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from uuid import uuid4

from .cluster_manager import ClusterManager, ClusterNode


class WorkflowState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    required_labels: frozenset[str] = field(default_factory=frozenset)
    depends_on: frozenset[str] = field(default_factory=frozenset)
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepAssignment:
    workflow_id: str
    step_id: str
    node_id: str
    lease_token: str


@dataclass(slots=True)
class WorkflowExecution:
    workflow_id: str
    steps: dict[str, WorkflowStep]
    completed_steps: set[str] = field(default_factory=set)
    failed_steps: set[str] = field(default_factory=set)
    assignments: dict[str, StepAssignment] = field(default_factory=dict)
    state: WorkflowState = WorkflowState.PENDING


class DistributedOrchestrator:
    """Coordinates dependency-aware workflows and node failover assignments."""

    def __init__(self, cluster: ClusterManager) -> None:
        self._cluster = cluster
        self._workflows: dict[str, WorkflowExecution] = {}
        self._lock = RLock()

    def submit(self, steps: list[WorkflowStep], *, workflow_id: str | None = None) -> WorkflowExecution:
        workflow_id = workflow_id or str(uuid4())
        step_map = {step.step_id: step for step in steps}
        if len(step_map) != len(steps):
            raise ValueError("workflow step IDs must be unique")
        for step in steps:
            unknown = step.depends_on.difference(step_map)
            if unknown:
                raise ValueError(f"unknown dependencies for {step.step_id}: {sorted(unknown)}")
        execution = WorkflowExecution(workflow_id=workflow_id, steps=step_map)
        with self._lock:
            if workflow_id in self._workflows:
                raise ValueError(f"workflow already exists: {workflow_id}")
            self._workflows[workflow_id] = execution
        return execution

    def schedule_ready(self, workflow_id: str) -> list[StepAssignment]:
        with self._lock:
            execution = self._require(workflow_id)
            assignments: list[StepAssignment] = []
            for step in execution.steps.values():
                if step.step_id in execution.completed_steps or step.step_id in execution.assignments:
                    continue
                if not step.depends_on.issubset(execution.completed_steps):
                    continue
                node = self._cluster.select_node(required_labels=step.required_labels)
                if node is None:
                    continue
                assignment = StepAssignment(
                    workflow_id=workflow_id,
                    step_id=step.step_id,
                    node_id=node.node_id,
                    lease_token=str(uuid4()),
                )
                execution.assignments[step.step_id] = assignment
                assignments.append(assignment)
            if assignments:
                execution.state = WorkflowState.RUNNING
            return assignments

    def complete_step(self, workflow_id: str, step_id: str, lease_token: str) -> WorkflowExecution:
        with self._lock:
            execution = self._require(workflow_id)
            assignment = execution.assignments.get(step_id)
            if assignment is None or assignment.lease_token != lease_token:
                raise PermissionError("invalid workflow step lease")
            execution.assignments.pop(step_id)
            execution.completed_steps.add(step_id)
            execution.failed_steps.discard(step_id)
            if execution.completed_steps == set(execution.steps):
                execution.state = WorkflowState.COMPLETED
            return execution

    def fail_step(self, workflow_id: str, step_id: str, lease_token: str) -> WorkflowExecution:
        with self._lock:
            execution = self._require(workflow_id)
            assignment = execution.assignments.get(step_id)
            if assignment is None or assignment.lease_token != lease_token:
                raise PermissionError("invalid workflow step lease")
            execution.assignments.pop(step_id)
            execution.failed_steps.add(step_id)
            execution.state = WorkflowState.FAILED
            return execution

    def recover_node(self, node_id: str) -> list[str]:
        """Release assignments owned by a failed node so they can be rescheduled."""
        released: list[str] = []
        with self._lock:
            for execution in self._workflows.values():
                for step_id, assignment in list(execution.assignments.items()):
                    if assignment.node_id == node_id:
                        execution.assignments.pop(step_id)
                        execution.failed_steps.discard(step_id)
                        execution.state = WorkflowState.PENDING
                        released.append(f"{execution.workflow_id}:{step_id}")
        return released

    def snapshot(self, workflow_id: str) -> WorkflowExecution:
        with self._lock:
            return self._require(workflow_id)

    def _require(self, workflow_id: str) -> WorkflowExecution:
        execution = self._workflows.get(workflow_id)
        if execution is None:
            raise KeyError(f"unknown workflow: {workflow_id}")
        return execution
