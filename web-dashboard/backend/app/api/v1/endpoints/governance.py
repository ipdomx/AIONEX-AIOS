"""Tenant-scoped councils, ministries, policies, votes, and approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    GovernanceBody,
    GovernanceDecision,
    GovernanceMembership,
    GovernancePolicy,
    GovernanceVote,
)
from app.services import communications, governance
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class ApprovalCreate(BaseModel):
    target_type: str = Field(min_length=2, max_length=80)
    target_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    risk: Literal["low", "medium", "high"] = "medium"
    required_role: str = Field(default="Owner", min_length=2, max_length=120)
    due_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionCreate(BaseModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    reason: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalResubmit(BaseModel):
    description: str | None = Field(default=None, max_length=10000)


class BodyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kind: Literal["council", "ministry", "committee", "department", "board"]
    charter: str | None = Field(default=None, max_length=20000)
    jurisdiction: str | None = Field(default=None, max_length=240)
    quorum: int = Field(default=1, ge=1, le=100000)
    parent_id: str | None = None


class MembershipCreate(BaseModel):
    user_id: str
    role: str = Field(default="member", min_length=2, max_length=80)
    voting_weight: int = Field(default=1, ge=0, le=100000)


class PolicyCreate(BaseModel):
    code: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    body_id: str | None = None
    scope: str = Field(default="organization", min_length=2, max_length=120)
    enforcement: Literal["mandatory", "advisory", "informational"] = "mandatory"
    policy: dict[str, Any] = Field(default_factory=dict)


class GovernanceDecisionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    rationale: str | None = Field(default=None, max_length=20000)
    body_id: str | None = None
    policy_id: str | None = None
    meeting_id: str | None = None
    decision: dict[str, Any] = Field(default_factory=dict)


class VoteCreate(BaseModel):
    vote: Literal["approve", "reject", "abstain"]
    rationale: str | None = Field(default=None, max_length=5000)


def _can_decide(actor: UserRecord) -> bool:
    return "*" in actor.permissions or "approvals:decide" in actor.permissions or "governance:approve" in actor.permissions


async def _approval(
    session: AsyncSession,
    actor: UserRecord,
    approval_id: str,
) -> ApprovalRequest:
    item = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return item


async def _body(
    session: AsyncSession, actor: UserRecord, body_id: str
) -> GovernanceBody:
    item = await session.scalar(
        select(GovernanceBody).where(
            GovernanceBody.id == body_id,
            GovernanceBody.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Governance body not found")
    return item


async def _policy(
    session: AsyncSession, actor: UserRecord, policy_id: str
) -> GovernancePolicy:
    item = await session.scalar(
        select(GovernancePolicy).where(
            GovernancePolicy.id == policy_id,
            GovernancePolicy.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Governance policy not found")
    return item


async def _governance_decision(
    session: AsyncSession, actor: UserRecord, decision_id: str
) -> GovernanceDecision:
    item = await session.scalar(
        select(GovernanceDecision).where(
            GovernanceDecision.id == decision_id,
            GovernanceDecision.organization_id == actor.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Governance decision not found")
    return item


@router.get("/approvals")
async def list_approvals(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("approvals:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(ApprovalRequest).where(
        ApprovalRequest.organization_id == actor.organization_id
    )
    if not _can_decide(actor):
        statement = statement.where(ApprovalRequest.requester_id == actor.id)
    if status_filter:
        statement = statement.where(ApprovalRequest.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(ApprovalRequest.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [governance.approval_snapshot(row) for row in rows]


@router.post("/approvals", status_code=status.HTTP_201_CREATED)
async def create_approval(
    data: ApprovalCreate,
    actor: UserRecord = Depends(require_permissions("approvals:read")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item, notifications = await governance.create_approval_request(
            session,
            actor,
            target_type=data.target_type,
            target_id=data.target_id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            risk=data.risk,
            required_role=data.required_role,
            due_at=data.due_at,
            metadata=data.metadata,
        )
        await session.commit()
        await session.refresh(item)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return governance.approval_snapshot(item)


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    actor: UserRecord = Depends(require_permissions("approvals:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _approval(session, actor, approval_id)
    if not _can_decide(actor) and item.requester_id != actor.id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    decisions = list(
        (
            await session.scalars(
                select(ApprovalDecision)
                .where(ApprovalDecision.approval_request_id == item.id)
                .order_by(ApprovalDecision.created_at)
            )
        ).all()
    )
    return {
        **governance.approval_snapshot(item),
        "decisions": [governance.decision_snapshot(row) for row in decisions],
    }


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(
    approval_id: str,
    data: ApprovalDecisionCreate,
    actor: UserRecord = Depends(require_permissions("approvals:decide")),
    session: AsyncSession = Depends(get_db),
):
    if not _can_decide(actor):
        raise HTTPException(status_code=403, detail="Approval decision permission is required")
    item = await _approval(session, actor, approval_id)
    try:
        item, record, notifications = await governance.decide_approval(
            session,
            actor,
            item,
            decision=data.decision,
            reason=data.reason,
            metadata=data.metadata,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return {
        **governance.approval_snapshot(item),
        "decision_record": governance.decision_snapshot(record),
    }


@router.post("/approvals/{approval_id}/resubmit")
async def resubmit_approval(
    approval_id: str,
    data: ApprovalResubmit,
    actor: UserRecord = Depends(require_permissions("approvals:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _approval(session, actor, approval_id)
    try:
        item, notifications = await governance.resubmit_approval(
            session, actor, item, description=data.description
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return governance.approval_snapshot(item)


@router.get("/bodies")
async def list_bodies(
    kind: str | None = Query(default=None, max_length=40),
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(GovernanceBody).where(
        GovernanceBody.organization_id == actor.organization_id,
        GovernanceBody.status != "deleted",
    )
    if kind:
        statement = statement.where(GovernanceBody.kind == kind)
    rows = list(
        (
            await session.scalars(statement.order_by(GovernanceBody.name))
        ).all()
    )
    return [governance.body_snapshot(row) for row in rows]


@router.post("/bodies", status_code=status.HTTP_201_CREATED)
async def create_body(
    data: BodyCreate,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await governance.create_body(
            session,
            actor,
            name=data.name,
            kind=data.kind,
            charter=data.charter,
            jurisdiction=data.jurisdiction,
            quorum=data.quorum,
            parent_id=data.parent_id,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return governance.body_snapshot(item)


@router.get("/bodies/{body_id}")
async def get_body(
    body_id: str,
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _body(session, actor, body_id)
    memberships = list(
        (
            await session.scalars(
                select(GovernanceMembership)
                .where(GovernanceMembership.body_id == item.id)
                .order_by(GovernanceMembership.created_at)
            )
        ).all()
    )
    return {
        **governance.body_snapshot(item),
        "memberships": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "role": row.role,
                "voting_weight": row.voting_weight,
                "status": row.status,
                "created_at": governance.iso(row.created_at),
            }
            for row in memberships
        ],
    }


@router.post("/bodies/{body_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    body_id: str,
    data: MembershipCreate,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    body = await _body(session, actor, body_id)
    try:
        item = await governance.add_membership(
            session,
            actor,
            body,
            user_id=data.user_id,
            role=data.role,
            voting_weight=data.voting_weight,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": item.id,
        "body_id": item.body_id,
        "user_id": item.user_id,
        "role": item.role,
        "voting_weight": item.voting_weight,
        "status": item.status,
    }


@router.get("/policies")
async def list_policies(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(GovernancePolicy).where(
        GovernancePolicy.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(GovernancePolicy.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(GovernancePolicy.updated_at.desc())
            )
        ).all()
    )
    return [governance.policy_snapshot(row) for row in rows]


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    data: PolicyCreate,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await governance.create_policy(
            session,
            actor,
            code=data.code,
            title=data.title,
            description=data.description,
            body_id=data.body_id,
            scope=data.scope,
            enforcement=data.enforcement,
            policy=data.policy,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return governance.policy_snapshot(item)


@router.post("/policies/{policy_id}/submit")
async def submit_policy(
    policy_id: str,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _policy(session, actor, policy_id)
    try:
        item, approval, notifications = await governance.submit_policy(
            session, actor, item
        )
        await session.commit()
    except (LookupError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return {
        "policy": governance.policy_snapshot(item),
        "approval": governance.approval_snapshot(approval),
    }


@router.post("/policies/{policy_id}/retire")
async def retire_policy(
    policy_id: str,
    actor: UserRecord = Depends(require_permissions("governance:approve")),
    session: AsyncSession = Depends(get_db),
):
    item = await _policy(session, actor, policy_id)
    try:
        item = await governance.retire_policy(session, actor, item)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return governance.policy_snapshot(item)


@router.get("/decisions")
async def list_decisions(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(GovernanceDecision).where(
        GovernanceDecision.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(GovernanceDecision.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(GovernanceDecision.created_at.desc())
            )
        ).all()
    )
    return [governance.governance_decision_snapshot(row) for row in rows]


@router.post("/decisions", status_code=status.HTTP_201_CREATED)
async def create_decision(
    data: GovernanceDecisionCreate,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await governance.create_governance_decision(
            session,
            actor,
            title=data.title,
            rationale=data.rationale,
            body_id=data.body_id,
            policy_id=data.policy_id,
            meeting_id=data.meeting_id,
            decision=data.decision,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return governance.governance_decision_snapshot(item)


@router.post("/decisions/{decision_id}/submit")
async def submit_decision(
    decision_id: str,
    actor: UserRecord = Depends(require_permissions("governance:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _governance_decision(session, actor, decision_id)
    try:
        item, approval, notifications = await governance.submit_governance_decision(
            session, actor, item
        )
        await session.commit()
    except (LookupError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return {
        "decision": governance.governance_decision_snapshot(item),
        "approval": governance.approval_snapshot(approval) if approval else None,
    }


@router.post("/decisions/{decision_id}/votes", status_code=status.HTTP_201_CREATED)
async def cast_vote(
    decision_id: str,
    data: VoteCreate,
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _governance_decision(session, actor, decision_id)
    try:
        vote, approval, notifications = await governance.cast_vote(
            session,
            actor,
            item,
            vote=data.vote,
            rationale=data.rationale,
        )
        await session.commit()
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return {
        "vote": governance.vote_snapshot(vote),
        "approval": governance.approval_snapshot(approval) if approval else None,
    }


@router.get("/decisions/{decision_id}/votes")
async def list_votes(
    decision_id: str,
    actor: UserRecord = Depends(require_permissions("governance:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _governance_decision(session, actor, decision_id)
    rows = list(
        (
            await session.scalars(
                select(GovernanceVote)
                .where(GovernanceVote.decision_id == item.id)
                .order_by(GovernanceVote.created_at)
            )
        ).all()
    )
    return [governance.vote_snapshot(row) for row in rows]
