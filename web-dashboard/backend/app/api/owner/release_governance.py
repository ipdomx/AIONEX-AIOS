"""Owner release governance adapter over live dashboard workflow state."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import UserRecord, current_user
from app.core.production_runtime import production_runtime
from app.core.runtime_store import runtime_store, utcnow
from app.integration.aios_bridge import aios_bridge

router = APIRouter(prefix="/owner/releases", tags=["owner-release-governance"])

GateStatus = Literal["passed", "warning", "blocked", "pending"]
ReleaseEnvironment = Literal["staging", "production"]
ReleaseStatus = Literal["ready", "blocked", "deploying", "released"]


class OwnerReleaseGate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    status: GateStatus
    owner_required: bool = Field(alias="ownerRequired")
    updated_at: str = Field(alias="updatedAt")


class OwnerReleaseCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    version: str
    environment: ReleaseEnvironment
    status: ReleaseStatus
    requested_by: str = Field(alias="requestedBy")
    created_at: str = Field(alias="createdAt")
    gates: list[OwnerReleaseGate]


class OwnerReleaseDecision(BaseModel):
    decision: Literal["approve", "reject", "rollback"]
    note: str = Field(min_length=1, max_length=2000)


def _normalized_role(role: str) -> str:
    return " ".join(role.strip().lower().replace("_", " ").replace("-", " ").split())


def _is_super_owner(actor: UserRecord) -> bool:
    return _normalized_role(actor.role) == "super owner"


def _visible(workflow: dict, actor: UserRecord) -> bool:
    return (
        _is_super_owner(actor)
        or workflow.get("organization_id") == actor.organization_id
    )


def _project_for(workflow: dict) -> dict | None:
    project_id = workflow.get("project_id")
    if not project_id:
        return None
    project = runtime_store.projects.get(str(project_id))
    if not project or project.get("deleted"):
        return None
    return project


def _step_text(step: dict) -> str:
    return " ".join(
        str(step.get(key) or "").strip().lower()
        for key in ("id", "name", "type", "category")
    )


def _is_deployment_step(step: dict) -> bool:
    searchable = _step_text(step)
    return (
        str(step.get("type") or "").strip().lower()
        in {"deployment", "deploy", "release"}
        or "deploy" in searchable
        or "release" in searchable
        or "rollback" in searchable
    )


def _is_owner_gate(step: dict) -> bool:
    searchable = _step_text(step)
    return (
        str(step.get("type") or "").strip().lower() == "approval"
        or "owner" in searchable
    )


def _is_release_workflow(workflow: dict) -> bool:
    explicit_kind = (
        str(
            workflow.get("category")
            or workflow.get("kind")
            or workflow.get("type")
            or ""
        )
        .strip()
        .lower()
    )
    searchable = " ".join(
        str(workflow.get(key) or "").strip().lower()
        for key in ("id", "name", "description")
    )
    steps = [step for step in workflow.get("steps") or [] if isinstance(step, dict)]
    return (
        explicit_kind in {"release", "deployment"}
        or "release" in searchable
        or "deploy" in searchable
        or any(_is_deployment_step(step) for step in steps)
    )


def _gate_status(value: object) -> GateStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {
        "passed",
        "pass",
        "approved",
        "completed",
        "complete",
        "done",
        "released",
        "success",
        "succeeded",
    }:
        return "passed"
    if normalized in {"warning", "warn", "running", "in_progress", "deploying"}:
        return "warning"
    if normalized in {
        "blocked",
        "failed",
        "failure",
        "rejected",
        "changes_requested",
        "changes-requested",
        "error",
        "rolled_back",
        "rollback",
    }:
        return "blocked"
    return "pending"


def _release_environment(workflow: dict, project: dict | None) -> ReleaseEnvironment:
    explicit = str(workflow.get("environment") or "").strip().lower()
    if explicit == "production":
        return "production"
    if explicit == "staging":
        return "staging"
    tags = {str(tag).strip().lower() for tag in ((project or {}).get("tags") or [])}
    return "production" if "production" in tags else "staging"


def _workflow_steps(workflow: dict) -> list[dict]:
    return [step for step in workflow.get("steps") or [] if isinstance(step, dict)]


def _candidate_status(workflow: dict) -> ReleaseStatus:
    steps = _workflow_steps(workflow)
    workflow_status = str(workflow.get("status") or "").strip().lower()
    deployment_steps = [step for step in steps if _is_deployment_step(step)]
    deployment_statuses = {
        _gate_status(step.get("status")) for step in deployment_steps
    }

    if (
        workflow_status in {"released", "completed", "complete", "done"}
        and deployment_steps
        and deployment_statuses == {"passed"}
    ):
        return "released"
    if workflow_status in {"deploying", "running", "in_progress"} or any(
        str(step.get("status") or "").strip().lower()
        in {"deploying", "running", "in_progress"}
        for step in deployment_steps
    ):
        return "deploying"

    owner_gates = [step for step in steps if _is_owner_gate(step)]
    prerequisites = [
        step
        for step in steps
        if not _is_owner_gate(step) and not _is_deployment_step(step)
    ]
    if (
        owner_gates
        and all(_gate_status(step.get("status")) == "passed" for step in prerequisites)
        and all(
            _gate_status(step.get("status")) in {"passed", "pending"}
            for step in owner_gates
        )
    ):
        return "ready"
    return "blocked"


def _candidate_version(workflow: dict, project: dict | None) -> str:
    version = workflow.get("version") or (project or {}).get("version")
    if version:
        return str(version).strip().removeprefix("v")
    return aios_bridge.status().version.removeprefix("v")


def _requested_by(workflow: dict, project: dict | None) -> str:
    return str(
        workflow.get("requested_by")
        or (project or {}).get("owner")
        or (project or {}).get("owner_id")
        or workflow.get("created_by")
        or ""
    )


def _serialize_candidate(workflow: dict) -> OwnerReleaseCandidate:
    project = _project_for(workflow)
    created_at = str(workflow.get("created_at") or workflow.get("updated_at") or "")
    gates = [
        OwnerReleaseGate(
            id=str(step.get("id") or f"step-{index}"),
            name=str(step.get("name") or step.get("id") or f"Step {index + 1}"),
            status=_gate_status(step.get("status")),
            owner_required=_is_owner_gate(step),
            updated_at=str(
                step.get("updated_at")
                or workflow.get("updated_at")
                or workflow.get("created_at")
                or ""
            ),
        )
        for index, step in enumerate(_workflow_steps(workflow))
    ]
    return OwnerReleaseCandidate(
        id=str(workflow["id"]),
        version=_candidate_version(workflow, project),
        environment=_release_environment(workflow, project),
        status=_candidate_status(workflow),
        requested_by=_requested_by(workflow, project),
        created_at=created_at,
        gates=gates,
    )


def list_release_candidates(actor: UserRecord) -> list[OwnerReleaseCandidate]:
    candidates = [
        _serialize_candidate(workflow)
        for workflow in runtime_store.workflows.values()
        if workflow.get("id")
        and not workflow.get("deleted")
        and _visible(workflow, actor)
        and _is_release_workflow(workflow)
    ]
    candidates.sort(key=lambda candidate: candidate.created_at, reverse=True)
    return candidates


def _find_release_workflow(candidate_id: str, actor: UserRecord) -> dict:
    workflow = runtime_store.workflows.get(candidate_id)
    if (
        not workflow
        or workflow.get("deleted")
        or not _visible(workflow, actor)
        or not _is_release_workflow(workflow)
    ):
        raise HTTPException(status_code=404, detail="Release candidate not found")
    return workflow


def _record_decision(
    workflow: dict,
    decision: OwnerReleaseDecision,
    actor: UserRecord,
    decided_at: str,
) -> None:
    workflow["release_decision"] = {
        "decision": decision.decision,
        "note": decision.note.strip(),
        "actor_id": actor.id,
        "actor": actor.name,
        "decided_at": decided_at,
    }
    workflow["updated_at"] = decided_at
    runtime_store.add_activity(
        "approval",
        f"Release {decision.decision}",
        str(workflow.get("name") or workflow["id"]),
        actor.id,
    )
    production_runtime.audit(
        actor.id,
        f"release.{decision.decision}",
        str(workflow["id"]),
        {
            "note": decision.note.strip(),
            "organization_id": workflow.get("organization_id"),
        },
    )


def apply_release_decision(
    candidate_id: str,
    decision: OwnerReleaseDecision,
    actor: UserRecord,
) -> OwnerReleaseCandidate:
    workflow = _find_release_workflow(candidate_id, actor)
    steps = _workflow_steps(workflow)
    owner_gates = [step for step in steps if _is_owner_gate(step)]
    deployment_steps = [step for step in steps if _is_deployment_step(step)]
    now = utcnow()

    if decision.decision == "approve":
        if _candidate_status(workflow) != "ready":
            raise HTTPException(
                status_code=409,
                detail="Release prerequisites have not passed",
            )
        pending_owner_gates = [
            step
            for step in owner_gates
            if _gate_status(step.get("status")) == "pending"
        ]
        if not owner_gates or not deployment_steps:
            raise HTTPException(
                status_code=409,
                detail="Release workflow has no owner gate or deployment step",
            )
        for step in pending_owner_gates:
            step.update(
                {
                    "status": "approved",
                    "decision_note": decision.note.strip(),
                    "decided_by": actor.id,
                    "decided_at": now,
                    "updated_at": now,
                }
            )
        for step in deployment_steps:
            step.update(
                {
                    "status": "released",
                    "released_by": actor.id,
                    "released_at": now,
                    "updated_at": now,
                }
            )
        workflow["status"] = "released"
    elif decision.decision == "reject":
        pending_owner_gates = [
            step
            for step in owner_gates
            if _gate_status(step.get("status")) == "pending"
        ]
        if not pending_owner_gates:
            raise HTTPException(
                status_code=409,
                detail="Release has no pending owner decision",
            )
        for step in pending_owner_gates:
            step.update(
                {
                    "status": "rejected",
                    "decision_note": decision.note.strip(),
                    "decided_by": actor.id,
                    "decided_at": now,
                    "updated_at": now,
                }
            )
        for step in deployment_steps:
            step.update({"status": "blocked", "updated_at": now})
        workflow["status"] = "blocked"
    else:
        if _candidate_status(workflow) != "released":
            raise HTTPException(
                status_code=409,
                detail="Only a released candidate can be rolled back",
            )
        if not deployment_steps:
            raise HTTPException(
                status_code=409,
                detail="Release workflow has no deployment step",
            )
        for step in deployment_steps:
            step.update(
                {
                    "status": "rolled_back",
                    "rollback_note": decision.note.strip(),
                    "rolled_back_by": actor.id,
                    "rolled_back_at": now,
                    "updated_at": now,
                }
            )
        workflow["status"] = "blocked"

    _record_decision(workflow, decision, actor, now)
    return _serialize_candidate(workflow)


@router.get("", response_model=list[OwnerReleaseCandidate])
def get_release_candidates(
    actor: UserRecord = Depends(current_user),
) -> list[OwnerReleaseCandidate]:
    return list_release_candidates(actor)


@router.post(
    "/{candidate_id}/decision",
    response_model=OwnerReleaseCandidate,
)
def decide_release(
    candidate_id: str,
    decision: OwnerReleaseDecision,
    actor: UserRecord = Depends(current_user),
) -> OwnerReleaseCandidate:
    return apply_release_decision(candidate_id, decision, actor)
