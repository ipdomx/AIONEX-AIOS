"""Durable Phase 29E meetings, approvals, councils, ministries, and policies."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Sequence

from app.core.auth import UserRecord
from app.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    GovernanceBody,
    GovernanceDecision,
    GovernanceMembership,
    GovernancePolicy,
    GovernanceVote,
    Meeting,
    MeetingAttendance,
    MeetingMinutes,
    User,
    uuid_str,
)
from app.services.communications import notify_audience
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


APPROVAL_STATUSES = frozenset(
    {"pending", "approved", "rejected", "changes_requested", "cancelled"}
)
DECISIONS = frozenset({"approved", "rejected", "changes_requested"})
BODY_KINDS = frozenset({"council", "ministry", "committee", "department", "board"})


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or uuid_str()[:8]


def approval_snapshot(item: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "requester": item.requester_id,
        "requester_id": item.requester_id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "scope": item.target_id,
        "category": item.target_type,
        "type": item.target_type.replace("_", " ").title(),
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "priority": item.priority,
        "risk": item.risk,
        "required_role": item.required_role,
        "version": item.version,
        "due_at": iso(item.due_at),
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "decidedAt": iso(item.decided_at),
        "decided_at": iso(item.decided_at),
        "metadata": item.approval_metadata,
    }


def decision_snapshot(item: ApprovalDecision) -> dict[str, Any]:
    return {
        "id": item.id,
        "approval_request_id": item.approval_request_id,
        "actor_id": item.actor_id,
        "decision": item.decision,
        "reason": item.reason,
        "metadata": item.decision_metadata,
        "created_at": iso(item.created_at),
    }


def body_snapshot(item: GovernanceBody) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "parent_id": item.parent_id,
        "owner_user_id": item.owner_user_id,
        "name": item.name,
        "slug": item.slug,
        "kind": item.kind,
        "status": item.status,
        "charter": item.charter,
        "jurisdiction": item.jurisdiction,
        "quorum": item.quorum,
        "metadata": item.body_metadata,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def policy_snapshot(item: GovernancePolicy) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "body_id": item.body_id,
        "created_by_id": item.created_by_id,
        "approved_by_id": item.approved_by_id,
        "code": item.code,
        "name": item.title,
        "title": item.title,
        "description": item.description,
        "scope": item.scope,
        "enforcement": item.enforcement,
        "status": item.status,
        "enabled": item.status == "active",
        "version": item.version,
        "policy": item.policy,
        "effective_at": iso(item.effective_at),
        "retired_at": iso(item.retired_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def governance_decision_snapshot(item: GovernanceDecision) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "body_id": item.body_id,
        "policy_id": item.policy_id,
        "meeting_id": item.meeting_id,
        "requested_by_id": item.requested_by_id,
        "decided_by_id": item.decided_by_id,
        "name": item.title,
        "title": item.title,
        "kind": "decision",
        "rationale": item.rationale,
        "body": item.rationale,
        "status": item.status,
        "decision": item.decision,
        "submitted_at": iso(item.submitted_at),
        "decided_at": iso(item.decided_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def vote_snapshot(item: GovernanceVote) -> dict[str, Any]:
    return {
        "id": item.id,
        "decision_id": item.decision_id,
        "voter_id": item.voter_id,
        "vote": item.vote,
        "rationale": item.rationale,
        "weight": item.weight,
        "created_at": iso(item.created_at),
    }


def attendance_snapshot(item: MeetingAttendance) -> dict[str, Any]:
    return {
        "id": item.id,
        "meeting_id": item.meeting_id,
        "user_id": item.user_id,
        "response_status": item.response_status,
        "response_note": item.response_note,
        "responded_at": iso(item.responded_at),
        "attended_at": iso(item.attended_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def minutes_snapshot(item: MeetingMinutes) -> dict[str, Any]:
    return {
        "id": item.id,
        "meeting_id": item.meeting_id,
        "published_by_id": item.published_by_id,
        "summary": item.summary,
        "notes": item.notes,
        "decisions": item.decisions,
        "action_items": item.action_items,
        "status": item.status,
        "published_at": iso(item.published_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


async def create_approval_request(
    session: AsyncSession,
    actor: UserRecord,
    *,
    target_type: str,
    target_id: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    risk: str = "medium",
    required_role: str = "Owner",
    due_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[ApprovalRequest, list]:
    existing = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.organization_id == actor.organization_id,
            ApprovalRequest.target_type == target_type,
            ApprovalRequest.target_id == target_id,
            ApprovalRequest.status.in_({"pending", "changes_requested"}),
        )
    )
    if existing is not None:
        return existing, []
    request = ApprovalRequest(
        id=uuid_str(),
        organization_id=actor.organization_id,
        requester_id=actor.id,
        target_type=target_type,
        target_id=target_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        status="pending",
        priority=priority,
        risk=risk,
        required_role=required_role,
        version=1,
        due_at=due_at,
        approval_metadata=metadata or {},
    )
    session.add(request)
    await session.flush()
    notifications = await notify_audience(
        session,
        organization_id=actor.organization_id,
        audience="owner",
        event_key="owner.approval.required",
        category="approval",
        title=request.title,
        message=request.description or f"Approval request {request.id} requires a decision.",
        severity="critical" if risk == "high" else "warning",
        source_type="approval_request",
        source_id=request.id,
        correlation_id=request.id,
        dedupe_prefix=f"approval-created:{request.id}",
        payload={
            "approval_id": request.id,
            "target_type": target_type,
            "target_id": target_id,
            "risk": risk,
        },
        actor_id=actor.id,
    )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="approval.request.created",
            resource_type="approval_request",
            resource_id=request.id,
            details={
                "target_type": target_type,
                "target_id": target_id,
                "priority": priority,
                "risk": risk,
            },
        )
    )
    return request, notifications


async def _apply_target_decision(
    session: AsyncSession,
    request: ApprovalRequest,
    actor: UserRecord,
    decision: str,
) -> None:
    if request.target_type == "meeting":
        meeting_target = await session.scalar(
            select(Meeting)
            .where(
                Meeting.id == request.target_id,
                Meeting.organization_id == request.organization_id,
            )
            .with_for_update()
        )
        if meeting_target is None:
            raise LookupError("Approval target meeting not found")
        meeting_target.status = {
            "approved": "scheduled",
            "rejected": "rejected",
            "changes_requested": "changes_requested",
        }[decision]
        meeting_target.approved_by_id = actor.id if decision == "approved" else None
        meeting_target.approved_at = now() if decision == "approved" else None
        meeting_target.version += 1
        return
    if request.target_type == "governance_policy":
        policy_target = await session.scalar(
            select(GovernancePolicy)
            .where(
                GovernancePolicy.id == request.target_id,
                GovernancePolicy.organization_id == request.organization_id,
            )
            .with_for_update()
        )
        if policy_target is None:
            raise LookupError("Approval target policy not found")
        policy_target.status = {
            "approved": "active",
            "rejected": "rejected",
            "changes_requested": "changes_requested",
        }[decision]
        policy_target.approved_by_id = actor.id if decision == "approved" else None
        policy_target.effective_at = now() if decision == "approved" else None
        policy_target.version += 1
        return
    if request.target_type == "governance_decision":
        decision_target = await session.scalar(
            select(GovernanceDecision)
            .where(
                GovernanceDecision.id == request.target_id,
                GovernanceDecision.organization_id == request.organization_id,
            )
            .with_for_update()
        )
        if decision_target is None:
            raise LookupError("Approval target governance decision not found")
        decision_target.status = decision
        decision_target.decided_by_id = actor.id
        decision_target.decided_at = now()
        decision_target.decision = {**decision_target.decision, "owner_decision": decision}
        return
    # Generic protected target: retain the immutable decision even when the
    # target is implemented by a later batch.


async def decide_approval(
    session: AsyncSession,
    actor: UserRecord,
    request: ApprovalRequest,
    *,
    decision: str,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[ApprovalRequest, ApprovalDecision, list]:
    if decision not in DECISIONS:
        raise ValueError("Unsupported approval decision")
    locked = await session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == request.id,
            ApprovalRequest.organization_id == request.organization_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Approval request not found")
    if locked.status not in {"pending", "changes_requested"}:
        existing = await session.scalar(
            select(ApprovalDecision)
            .where(
                ApprovalDecision.approval_request_id == locked.id,
                ApprovalDecision.decision == locked.status,
            )
            .order_by(ApprovalDecision.created_at.desc())
        )
        if existing is not None and locked.status == decision:
            return locked, existing, []
        raise ValueError("Approval request has already reached a terminal state")
    await _apply_target_decision(session, locked, actor, decision)
    locked.status = decision
    locked.decided_at = now()
    locked.version += 1
    record = ApprovalDecision(
        id=uuid_str(),
        approval_request_id=locked.id,
        actor_id=actor.id,
        decision=decision,
        reason=reason.strip() or None,
        decision_metadata=metadata or {},
        created_at=now(),
    )
    session.add(record)
    requester = await session.get(User, locked.requester_id)
    notifications = []
    if requester is not None:
        notifications = await notify_audience(
            session,
            organization_id=locked.organization_id,
            audience="user",
            explicit_user_ids=[requester.id],
            event_key=(
                "meeting.approval.decided"
                if locked.target_type == "meeting"
                else "governance.decision.decided"
            ),
            category="approval",
            title=f"Decision: {locked.title}",
            message=f"The request was {decision.replace('_', ' ')}. {reason}".strip(),
            severity="warning" if decision == "changes_requested" else "info",
            source_type="approval_request",
            source_id=locked.id,
            correlation_id=locked.id,
            dedupe_prefix=f"approval-decision:{locked.id}:{locked.version}",
            payload={"approval_id": locked.id, "decision": decision},
            actor_id=actor.id,
        )
    session.add(
        AuditEvent(
            organization_id=locked.organization_id,
            user_id=actor.id,
            action="approval.request.decided",
            resource_type="approval_request",
            resource_id=locked.id,
            details={
                "decision": decision,
                "target_type": locked.target_type,
                "target_id": locked.target_id,
                "reason_present": bool(reason.strip()),
            },
        )
    )
    await session.flush()
    return locked, record, notifications


async def resubmit_approval(
    session: AsyncSession,
    actor: UserRecord,
    request: ApprovalRequest,
    *,
    description: str | None = None,
) -> tuple[ApprovalRequest, list]:
    locked = await session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == request.id,
            ApprovalRequest.organization_id == actor.organization_id,
            ApprovalRequest.requester_id == actor.id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Approval request not found")
    if locked.status != "changes_requested":
        raise ValueError("Only a changes-requested approval can be resubmitted")
    locked.status = "pending"
    locked.description = (description or locked.description or "").strip() or None
    locked.decided_at = None
    locked.version += 1
    notifications = await notify_audience(
        session,
        organization_id=locked.organization_id,
        audience="owner",
        event_key="owner.approval.required",
        category="approval",
        title=f"Resubmitted: {locked.title}",
        message=locked.description or "A revised approval request requires review.",
        severity="warning",
        source_type="approval_request",
        source_id=locked.id,
        correlation_id=locked.id,
        dedupe_prefix=f"approval-resubmitted:{locked.id}:{locked.version}",
        payload={"approval_id": locked.id, "version": locked.version},
        actor_id=actor.id,
    )
    session.add(
        AuditEvent(
            organization_id=locked.organization_id,
            user_id=actor.id,
            action="approval.request.resubmitted",
            resource_type="approval_request",
            resource_id=locked.id,
            details={"version": locked.version},
        )
    )
    return locked, notifications


async def create_body(
    session: AsyncSession,
    actor: UserRecord,
    *,
    name: str,
    kind: str,
    charter: str | None = None,
    jurisdiction: str | None = None,
    quorum: int = 1,
    parent_id: str | None = None,
) -> GovernanceBody:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in BODY_KINDS:
        raise ValueError("Unsupported governance body kind")
    slug = slugify(name)
    existing = await session.scalar(
        select(GovernanceBody).where(
            GovernanceBody.organization_id == actor.organization_id,
            GovernanceBody.slug == slug,
        )
    )
    if existing is not None:
        raise ValueError("Governance body slug already exists")
    if parent_id:
        parent = await session.scalar(
            select(GovernanceBody).where(
                GovernanceBody.id == parent_id,
                GovernanceBody.organization_id == actor.organization_id,
            )
        )
        if parent is None:
            raise LookupError("Parent governance body not found")
    item = GovernanceBody(
        id=uuid_str(),
        organization_id=actor.organization_id,
        parent_id=parent_id,
        owner_user_id=actor.id,
        name=name.strip(),
        slug=slug,
        kind=normalized_kind,
        status="active",
        charter=(charter or "").strip() or None,
        jurisdiction=(jurisdiction or "").strip() or None,
        quorum=max(1, quorum),
        body_metadata={},
    )
    session.add(item)
    await session.flush()
    session.add(
        GovernanceMembership(
            id=uuid_str(),
            body_id=item.id,
            user_id=actor.id,
            role="chair",
            voting_weight=1,
            status="active",
        )
    )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.body.created",
            resource_type="governance_body",
            resource_id=item.id,
            details={"kind": item.kind, "slug": item.slug, "quorum": item.quorum},
        )
    )
    return item


async def add_membership(
    session: AsyncSession,
    actor: UserRecord,
    body: GovernanceBody,
    *,
    user_id: str,
    role: str = "member",
    voting_weight: int = 1,
) -> GovernanceMembership:
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == actor.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise LookupError("Governance member user not found")
    membership = await session.scalar(
        select(GovernanceMembership)
        .where(
            GovernanceMembership.body_id == body.id,
            GovernanceMembership.user_id == user_id,
        )
        .with_for_update()
    )
    if membership is None:
        membership = GovernanceMembership(
            id=uuid_str(),
            body_id=body.id,
            user_id=user_id,
            role=role.strip().lower() or "member",
            voting_weight=max(0, voting_weight),
            status="active",
        )
        session.add(membership)
    else:
        membership.role = role.strip().lower() or membership.role
        membership.voting_weight = max(0, voting_weight)
        membership.status = "active"
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.membership.updated",
            resource_type="governance_body",
            resource_id=body.id,
            details={"member_id": user_id, "role": membership.role},
        )
    )
    await session.flush()
    return membership


async def create_policy(
    session: AsyncSession,
    actor: UserRecord,
    *,
    code: str,
    title: str,
    description: str | None = None,
    body_id: str | None = None,
    scope: str = "organization",
    enforcement: str = "mandatory",
    policy: dict[str, Any] | None = None,
    record_id: str | None = None,
) -> GovernancePolicy:
    normalized_code = re.sub(r"[^A-Z0-9_.-]+", "-", code.strip().upper()).strip("-")
    if len(normalized_code) < 2:
        raise ValueError("Governance policy code is invalid")
    if body_id:
        body = await session.scalar(
            select(GovernanceBody).where(
                GovernanceBody.id == body_id,
                GovernanceBody.organization_id == actor.organization_id,
                GovernanceBody.status == "active",
            )
        )
        if body is None:
            raise LookupError("Governance body not found")
    existing = await session.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.organization_id == actor.organization_id,
            GovernancePolicy.code == normalized_code,
        )
    )
    if existing is not None:
        raise ValueError("Governance policy code already exists")
    item = GovernancePolicy(
        id=record_id or uuid_str(),
        organization_id=actor.organization_id,
        body_id=body_id,
        created_by_id=actor.id,
        code=normalized_code,
        title=title.strip(),
        description=(description or "").strip() or None,
        scope=scope.strip() or "organization",
        enforcement=enforcement,
        status="draft",
        version=1,
        policy=policy or {},
    )
    session.add(item)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.policy.created",
            resource_type="governance_policy",
            resource_id=item.id,
            details={"code": item.code, "scope": item.scope},
        )
    )
    return item


async def submit_policy(
    session: AsyncSession,
    actor: UserRecord,
    policy: GovernancePolicy,
) -> tuple[GovernancePolicy, ApprovalRequest, list]:
    locked = await session.scalar(
        select(GovernancePolicy)
        .where(
            GovernancePolicy.id == policy.id,
            GovernancePolicy.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Governance policy not found")
    if locked.status not in {"draft", "changes_requested", "rejected"}:
        raise ValueError("Policy cannot be submitted from its current state")
    locked.status = "pending"
    locked.version += 1
    request, notifications = await create_approval_request(
        session,
        actor,
        target_type="governance_policy",
        target_id=locked.id,
        title=f"Approve policy {locked.code}: {locked.title}",
        description=locked.description,
        priority="high" if locked.enforcement == "mandatory" else "medium",
        risk="high" if locked.enforcement == "mandatory" else "medium",
        metadata={"policy_code": locked.code, "version": locked.version},
    )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.policy.submitted",
            resource_type="governance_policy",
            resource_id=locked.id,
            details={"approval_id": request.id, "version": locked.version},
        )
    )
    return locked, request, notifications


async def retire_policy(
    session: AsyncSession, actor: UserRecord, policy: GovernancePolicy
) -> GovernancePolicy:
    locked = await session.scalar(
        select(GovernancePolicy)
        .where(
            GovernancePolicy.id == policy.id,
            GovernancePolicy.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Governance policy not found")
    if locked.status != "active":
        raise ValueError("Only an active policy can be retired")
    locked.status = "retired"
    locked.retired_at = now()
    locked.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.policy.retired",
            resource_type="governance_policy",
            resource_id=locked.id,
            details={"version": locked.version},
        )
    )
    return locked


async def create_governance_decision(
    session: AsyncSession,
    actor: UserRecord,
    *,
    title: str,
    rationale: str | None = None,
    body_id: str | None = None,
    policy_id: str | None = None,
    meeting_id: str | None = None,
    decision: dict[str, Any] | None = None,
    record_id: str | None = None,
) -> GovernanceDecision:
    if body_id:
        body = await session.scalar(
            select(GovernanceBody).where(
                GovernanceBody.id == body_id,
                GovernanceBody.organization_id == actor.organization_id,
                GovernanceBody.status == "active",
            )
        )
        if body is None:
            raise LookupError("Governance body not found")
    item = GovernanceDecision(
        id=record_id or uuid_str(),
        organization_id=actor.organization_id,
        body_id=body_id,
        policy_id=policy_id,
        meeting_id=meeting_id,
        requested_by_id=actor.id,
        title=title.strip(),
        rationale=(rationale or "").strip() or None,
        status="draft",
        decision=decision or {},
    )
    session.add(item)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.decision.created",
            resource_type="governance_decision",
            resource_id=item.id,
            details={"body_id": body_id, "policy_id": policy_id},
        )
    )
    return item


async def submit_governance_decision(
    session: AsyncSession,
    actor: UserRecord,
    item: GovernanceDecision,
) -> tuple[GovernanceDecision, ApprovalRequest | None, list]:
    locked = await session.scalar(
        select(GovernanceDecision)
        .where(
            GovernanceDecision.id == item.id,
            GovernanceDecision.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Governance decision not found")
    if locked.status not in {"draft", "changes_requested", "rejected"}:
        raise ValueError("Governance decision cannot be submitted")
    locked.submitted_at = now()
    if locked.body_id:
        body = await session.get(GovernanceBody, locked.body_id)
        if body is None:
            raise LookupError("Governance body not found")
        vote_weight_result = await session.execute(
            select(func.coalesce(func.sum(GovernanceMembership.voting_weight), 0)).where(
                GovernanceMembership.body_id == body.id,
                GovernanceMembership.status == "active",
            )
        )
        vote_weight = int(vote_weight_result.scalar_one())
        if body.quorum > 1 and vote_weight > 0:
            locked.status = "voting"
            session.add(
                AuditEvent(
                    organization_id=actor.organization_id,
                    user_id=actor.id,
                    action="governance.decision.voting_opened",
                    resource_type="governance_decision",
                    resource_id=locked.id,
                    details={"quorum": body.quorum, "eligible_weight": vote_weight},
                )
            )
            return locked, None, []
    locked.status = "pending"
    request, notifications = await create_approval_request(
        session,
        actor,
        target_type="governance_decision",
        target_id=locked.id,
        title=f"Governance decision: {locked.title}",
        description=locked.rationale,
        priority="high",
        risk="high",
        metadata={"body_id": locked.body_id, "policy_id": locked.policy_id},
    )
    return locked, request, notifications


async def cast_vote(
    session: AsyncSession,
    actor: UserRecord,
    item: GovernanceDecision,
    *,
    vote: str,
    rationale: str | None = None,
) -> tuple[GovernanceVote, ApprovalRequest | None, list]:
    if vote not in {"approve", "reject", "abstain"}:
        raise ValueError("Unsupported governance vote")
    locked = await session.scalar(
        select(GovernanceDecision)
        .where(
            GovernanceDecision.id == item.id,
            GovernanceDecision.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked is None or locked.status != "voting" or not locked.body_id:
        raise ValueError("Governance decision is not open for voting")
    membership = await session.scalar(
        select(GovernanceMembership).where(
            GovernanceMembership.body_id == locked.body_id,
            GovernanceMembership.user_id == actor.id,
            GovernanceMembership.status == "active",
        )
    )
    if membership is None:
        raise PermissionError("User is not an active voting member")
    existing = await session.scalar(
        select(GovernanceVote).where(
            GovernanceVote.decision_id == locked.id,
            GovernanceVote.voter_id == actor.id,
        )
    )
    if existing is not None:
        if existing.vote == vote and (existing.rationale or "") == (rationale or ""):
            return existing, None, []
        raise ValueError("A vote has already been recorded")
    record = GovernanceVote(
        id=uuid_str(),
        decision_id=locked.id,
        voter_id=actor.id,
        vote=vote,
        rationale=(rationale or "").strip() or None,
        weight=membership.voting_weight,
        created_at=now(),
    )
    session.add(record)
    await session.flush()
    body = await session.get(GovernanceBody, locked.body_id)
    if body is None:
        raise LookupError("Governance body not found")
    rows = (
        await session.execute(
            select(GovernanceVote.vote, func.sum(GovernanceVote.weight))
            .where(GovernanceVote.decision_id == locked.id)
            .group_by(GovernanceVote.vote)
        )
    ).all()
    totals = {str(name): int(weight or 0) for name, weight in rows}
    cast_weight = sum(totals.values())
    request: ApprovalRequest | None = None
    notifications: list = []
    if cast_weight >= body.quorum:
        if totals.get("approve", 0) <= totals.get("reject", 0):
            locked.status = "rejected"
            locked.decided_at = now()
            locked.decision = {**locked.decision, "vote_totals": totals}
        else:
            locked.status = "pending"
            locked.decision = {**locked.decision, "vote_totals": totals}
            request, notifications = await create_approval_request(
                session,
                actor,
                target_type="governance_decision",
                target_id=locked.id,
                title=f"Ratify governance decision: {locked.title}",
                description=locked.rationale,
                priority="high",
                risk="high",
                metadata={"vote_totals": totals, "quorum": body.quorum},
            )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="governance.vote.cast",
            resource_type="governance_decision",
            resource_id=locked.id,
            details={"vote": vote, "weight": record.weight, "totals": totals},
        )
    )
    return record, request, notifications


async def ensure_meeting_attendance(
    session: AsyncSession,
    meeting: Meeting,
    attendee_ids: Sequence[str],
    *,
    actor_id: str,
) -> list[MeetingAttendance]:
    valid_users = list(
        (
            await session.scalars(
                select(User).where(
                    User.organization_id == meeting.organization_id,
                    User.id.in_(list(dict.fromkeys(attendee_ids))),
                    User.deleted_at.is_(None),
                )
            )
        ).all()
    )
    rows: list[MeetingAttendance] = []
    for user in valid_users:
        item = await session.scalar(
            select(MeetingAttendance).where(
                MeetingAttendance.meeting_id == meeting.id,
                MeetingAttendance.user_id == user.id,
            )
        )
        if item is None:
            item = MeetingAttendance(
                id=uuid_str(),
                meeting_id=meeting.id,
                user_id=user.id,
                response_status="invited",
            )
            session.add(item)
        rows.append(item)
        await notify_audience(
            session,
            organization_id=meeting.organization_id,
            audience="user",
            explicit_user_ids=[user.id],
            event_key="meeting.invited",
            category="meeting",
            title=f"Meeting invitation: {meeting.title}",
            message=f"You were invited to {meeting.title} at {iso(meeting.start_time)}.",
            severity="info",
            source_type="meeting",
            source_id=meeting.id,
            correlation_id=meeting.id,
            dedupe_prefix=f"meeting-invite:{meeting.id}",
            payload={"meeting_id": meeting.id, "start_time": iso(meeting.start_time)},
            actor_id=actor_id,
        )
    await session.flush()
    return rows


async def respond_to_meeting(
    session: AsyncSession,
    actor: UserRecord,
    meeting: Meeting,
    *,
    response_status: str,
    note: str | None = None,
) -> MeetingAttendance:
    if response_status not in {"accepted", "declined", "tentative"}:
        raise ValueError("Unsupported meeting response")
    attendance = await session.scalar(
        select(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.id,
            MeetingAttendance.user_id == actor.id,
        )
        .with_for_update()
    )
    if attendance is None:
        raise PermissionError("User is not invited to this meeting")
    attendance.response_status = response_status
    attendance.response_note = (note or "").strip() or None
    attendance.responded_at = now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="meeting.attendance.responded",
            resource_type="meeting",
            resource_id=meeting.id,
            details={"response_status": response_status},
        )
    )
    return attendance


async def upsert_minutes(
    session: AsyncSession,
    actor: UserRecord,
    meeting: Meeting,
    *,
    summary: str | None,
    notes: str | None,
    decisions: Sequence[dict[str, Any]],
    action_items: Sequence[dict[str, Any]],
    publish: bool,
) -> MeetingMinutes:
    item = await session.scalar(
        select(MeetingMinutes)
        .where(MeetingMinutes.meeting_id == meeting.id)
        .with_for_update()
    )
    if item is None:
        item = MeetingMinutes(id=uuid_str(), meeting_id=meeting.id, status="draft")
        session.add(item)
    item.summary = (summary or "").strip() or None
    item.notes = (notes or "").strip() or None
    item.decisions = list(decisions)
    item.action_items = list(action_items)
    if publish:
        item.status = "published"
        item.published_by_id = actor.id
        item.published_at = now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="meeting.minutes.published" if publish else "meeting.minutes.updated",
            resource_type="meeting",
            resource_id=meeting.id,
            details={
                "minutes_id": item.id,
                "decisions": len(item.decisions),
                "action_items": len(item.action_items),
            },
        )
    )
    await session.flush()
    return item


async def complete_meeting(
    session: AsyncSession, actor: UserRecord, meeting: Meeting
) -> Meeting:
    locked = await session.scalar(
        select(Meeting)
        .where(
            Meeting.id == meeting.id,
            Meeting.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise LookupError("Meeting not found")
    if locked.status not in {"scheduled", "in_progress"}:
        raise ValueError("Meeting cannot be completed from its current state")
    locked.status = "completed"
    locked.completed_at = now()
    locked.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="meeting.completed",
            resource_type="meeting",
            resource_id=locked.id,
            details={"completed_at": iso(locked.completed_at)},
        )
    )
    return locked
