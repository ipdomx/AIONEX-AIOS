"""Owner approval adapter over live meeting and workflow approval records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import runtime_store, utcnow

router = APIRouter(prefix="/owner/approvals", tags=["owner-approvals"])

ApprovalStatus = Literal["pending", "approved", "rejected", "changes_requested"]
ApprovalCategory = Literal["release", "service", "policy", "meeting", "staff"]
ApprovalPriority = Literal["low", "medium", "high", "critical"]


class OwnerApproval(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    requester: str
    scope: str
    category: ApprovalCategory
    status: ApprovalStatus
    priority: ApprovalPriority
    created_at: str = Field(alias="createdAt")


class OwnerApprovalList(BaseModel):
    approvals: list[OwnerApproval]


class ApprovalDecision(BaseModel):
    status: Literal["approved", "rejected", "changes_requested"]
    reason: str = Field(min_length=1, max_length=1000)


def _normalized_role(role: str) -> str:
    return " ".join(role.strip().lower().replace("_", " ").replace("-", " ").split())


def _visible(organization_id: object, actor: UserRecord) -> bool:
    return (
        _normalized_role(actor.role) == "super owner"
        or organization_id == actor.organization_id
    )


def _priority(value: object) -> ApprovalPriority:
    normalized = str(value or "").strip().lower()
    if normalized in {"low", "medium", "high", "critical"}:
        return normalized  # type: ignore[return-value]
    return "medium"


def _approval_status(value: object) -> ApprovalStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"approved", "scheduled", "completed", "passed"}:
        return "approved"
    if normalized in {"rejected", "denied", "failed"}:
        return "rejected"
    if normalized in {"changes_requested", "changes-requested", "needs_changes"}:
        return "changes_requested"
    return "pending"


def _workflow_category(workflow: dict, step: dict) -> ApprovalCategory:
    searchable = " ".join(
        str(value or "").lower()
        for value in (
            workflow.get("id"),
            workflow.get("name"),
            step.get("id"),
            step.get("name"),
            step.get("category"),
        )
    )
    if "release" in searchable or "deploy" in searchable:
        return "release"
    if "policy" in searchable:
        return "policy"
    if "staff" in searchable or "employee" in searchable:
        return "staff"
    return "service"


def _project_for(item: dict) -> dict | None:
    project_id = item.get("project_id")
    if not project_id:
        return None
    project = runtime_store.projects.get(str(project_id))
    if not project or project.get("deleted"):
        return None
    return project


def _meeting_approval(meeting: dict) -> OwnerApproval:
    project = _project_for(meeting)
    status = _approval_status(meeting.get("approval_status") or meeting.get("status"))
    if meeting.get("approved_by_owner") is True:
        status = "approved"
    return OwnerApproval(
        id=f"meeting:{meeting['id']}",
        title=str(meeting.get("title") or meeting["id"]),
        requester=str(
            meeting.get("organizer") or meeting.get("organizer_id") or "Unknown"
        ),
        scope=str(
            (project or {}).get("name")
            or meeting.get("workspace_id")
            or meeting.get("organization_id")
            or meeting["id"]
        ),
        category="meeting",
        status=status,
        priority=_priority((project or {}).get("priority")),
        created_at=str(
            meeting.get("created_at")
            or meeting.get("start_time")
            or datetime.now(timezone.utc).isoformat()
        ),
    )


def _workflow_approval(workflow: dict, step: dict) -> OwnerApproval:
    project = _project_for(workflow)
    return OwnerApproval(
        id=f"workflow:{workflow['id']}:{step['id']}",
        title=str(step.get("name") or step["id"]),
        requester=str(
            workflow.get("requested_by")
            or (project or {}).get("owner")
            or (project or {}).get("owner_id")
            or workflow.get("name")
            or workflow["id"]
        ),
        scope=str(
            (project or {}).get("name")
            or workflow.get("workspace_id")
            or workflow.get("organization_id")
            or workflow["id"]
        ),
        category=_workflow_category(workflow, step),
        status=_approval_status(step.get("status")),
        priority=_priority((project or {}).get("priority")),
        created_at=str(
            step.get("created_at")
            or workflow.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        ),
    )


def list_owner_approvals(actor: UserRecord) -> list[OwnerApproval]:
    approvals: list[OwnerApproval] = []
    for meeting in runtime_store.meetings.values():
        if meeting.get("deleted") or not _visible(
            meeting.get("organization_id"), actor
        ):
            continue
        if (
            meeting.get("status")
            not in {
                "pending_approval",
                "scheduled",
                "approved",
                "rejected",
                "changes_requested",
            }
            and "approval_status" not in meeting
        ):
            continue
        approvals.append(_meeting_approval(meeting))

    for workflow in runtime_store.workflows.values():
        if workflow.get("deleted") or not _visible(
            workflow.get("organization_id"), actor
        ):
            continue
        for step in workflow.get("steps") or []:
            if (
                not isinstance(step, dict)
                or str(step.get("type") or "").lower() != "approval"
            ):
                continue
            if not step.get("id"):
                continue
            approvals.append(_workflow_approval(workflow, step))

    approvals.sort(key=lambda item: item.created_at, reverse=True)
    return approvals


def _decide_meeting(
    meeting_id: str,
    decision: ApprovalDecision,
    actor: UserRecord,
) -> OwnerApproval:
    meeting = runtime_store.meetings.get(meeting_id)
    if (
        not meeting
        or meeting.get("deleted")
        or not _visible(meeting.get("organization_id"), actor)
    ):
        raise HTTPException(status_code=404, detail="Approval request not found")
    current = _meeting_approval(meeting)
    if current.status != "pending":
        raise HTTPException(
            status_code=409, detail="Approval request has already been decided"
        )

    meeting["approval_status"] = decision.status
    meeting["approved_by_owner"] = decision.status == "approved"
    meeting["status"] = (
        "scheduled" if decision.status == "approved" else decision.status
    )
    meeting["decision_reason"] = decision.reason.strip()
    meeting["decided_by"] = actor.id
    meeting["decided_at"] = utcnow()
    meeting["updated_at"] = utcnow()
    runtime_store.add_activity(
        "approval",
        f"Meeting approval {decision.status}",
        str(meeting.get("title") or meeting_id),
        actor.id,
    )
    return _meeting_approval(meeting)


def _decide_workflow(
    workflow_id: str,
    step_id: str,
    decision: ApprovalDecision,
    actor: UserRecord,
) -> OwnerApproval:
    workflow = runtime_store.workflows.get(workflow_id)
    if (
        not workflow
        or workflow.get("deleted")
        or not _visible(workflow.get("organization_id"), actor)
    ):
        raise HTTPException(status_code=404, detail="Approval request not found")
    step = next(
        (
            item
            for item in workflow.get("steps") or []
            if isinstance(item, dict) and str(item.get("id")) == step_id
        ),
        None,
    )
    if not step or str(step.get("type") or "").lower() != "approval":
        raise HTTPException(status_code=404, detail="Approval request not found")
    current = _workflow_approval(workflow, step)
    if current.status != "pending":
        raise HTTPException(
            status_code=409, detail="Approval request has already been decided"
        )

    step["status"] = decision.status
    step["decision_reason"] = decision.reason.strip()
    step["decided_by"] = actor.id
    step["decided_at"] = utcnow()
    workflow["updated_at"] = utcnow()
    if decision.status in {"rejected", "changes_requested"}:
        workflow["status"] = "blocked"
    runtime_store.add_activity(
        "approval",
        f"Workflow approval {decision.status}",
        f"{workflow.get('name') or workflow_id}: {step.get('name') or step_id}",
        actor.id,
    )
    return _workflow_approval(workflow, step)


@router.get("", response_model=OwnerApprovalList)
def get_owner_approvals(
    actor: UserRecord = Depends(current_user),
) -> OwnerApprovalList:
    return OwnerApprovalList(approvals=list_owner_approvals(actor))


@router.patch("/{approval_id}", response_model=OwnerApproval)
def decide_owner_approval(
    approval_id: str,
    decision: ApprovalDecision,
    actor: UserRecord = Depends(current_user),
) -> OwnerApproval:
    if approval_id.startswith("meeting:"):
        return _decide_meeting(approval_id.removeprefix("meeting:"), decision, actor)
    if approval_id.startswith("workflow:"):
        parts = approval_id.split(":", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return _decide_workflow(parts[1], parts[2], decision, actor)
    raise HTTPException(status_code=404, detail="Approval request not found")
