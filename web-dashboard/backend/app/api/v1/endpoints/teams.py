"""Organization-scoped teams and membership lifecycle."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from app.api.v1.endpoints.users import serialize_user
from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Organization, Team, TeamMembership, User, Workspace
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "team"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    organization_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    workspace_id: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    workspace_id: str | None = None
    status: Literal["active", "inactive"] | None = None


class TeamMemberUpsert(BaseModel):
    membership_role: Literal["lead", "member"] = "member"


async def _unique_slug(
    session: AsyncSession,
    organization_id: str,
    name: str,
    *,
    exclude_id: str | None = None,
) -> str:
    base = _slugify(name)
    candidate = base
    suffix = 2
    while True:
        query = select(Team.id).where(
            Team.organization_id == organization_id,
            Team.slug == candidate,
        )
        if exclude_id:
            query = query.where(Team.id != exclude_id)
        if await session.scalar(query) is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def _workspace(
    session: AsyncSession,
    workspace_id: str | None,
    organization_id: str,
) -> Workspace | None:
    if workspace_id is None:
        return None
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
            Workspace.status != "deleted",
        )
    )
    if workspace is None:
        raise HTTPException(status_code=422, detail="Workspace does not belong to this organization")
    return workspace


async def _team(session: AsyncSession, team_id: str, actor: UserRecord) -> Team:
    team = await session.scalar(
        select(Team).where(Team.id == team_id, Team.status != "deleted")
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if actor.role != "Super Owner" and team.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _audit(actor: UserRecord, team: Team, action: str, details: dict[str, Any] | None = None) -> AuditEvent:
    return AuditEvent(
        organization_id=team.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="team",
        resource_id=team.id,
        details=details or {},
    )


async def _serialize(session: AsyncSession, team: Team) -> dict[str, Any]:
    member_count = await session.scalar(
        select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team.id)
    )
    workspace = await session.get(Workspace, team.workspace_id) if team.workspace_id else None
    return {
        "id": team.id,
        "organization_id": team.organization_id,
        "workspace_id": team.workspace_id,
        "workspace": workspace.name if workspace else None,
        "name": team.name,
        "slug": team.slug,
        "description": team.description,
        "status": team.status,
        "member_count": int(member_count or 0),
        "created_at": _iso(team.created_at),
        "updated_at": _iso(team.updated_at),
    }


@router.get("")
async def list_teams(
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    query = select(Team).where(Team.status != "deleted")
    if actor.role != "Super Owner":
        query = query.where(Team.organization_id == actor.organization_id)
    teams = list((await session.scalars(query.order_by(func.lower(Team.name)))).all())
    return [await _serialize(session, team) for team in teams]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    data: TeamCreate,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    organization_id = data.organization_id or actor.organization_id
    if actor.role != "Super Owner" and organization_id != actor.organization_id:
        raise HTTPException(status_code=403, detail="Cannot create teams outside your organization")
    organization = await session.get(Organization, organization_id)
    if organization is None or organization.status != "active":
        raise HTTPException(status_code=422, detail="Organization is not active")
    workspace = await _workspace(session, data.workspace_id, organization_id)
    team = Team(
        organization_id=organization_id,
        workspace_id=workspace.id if workspace else None,
        name=data.name.strip(),
        slug=await _unique_slug(session, organization_id, data.name),
        description=data.description.strip() if data.description else None,
        status="active",
    )
    session.add(team)
    await session.flush()
    session.add(_audit(actor, team, "team.create"))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A team with this name already exists") from exc
    return await _serialize(session, team)


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    return await _serialize(session, await _team(session, team_id, actor))


@router.put("/{team_id}")
async def update_team(
    team_id: str,
    data: TeamUpdate,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    team = await _team(session, team_id, actor)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        name = str(updates.pop("name")).strip()
        team.name = name
        team.slug = await _unique_slug(
            session, team.organization_id, name, exclude_id=team.id
        )
    if "description" in updates:
        value = updates.pop("description")
        team.description = value.strip() if value else None
    if "workspace_id" in updates:
        workspace = await _workspace(session, updates.pop("workspace_id"), team.organization_id)
        team.workspace_id = workspace.id if workspace else None
    if "status" in updates:
        team.status = updates.pop("status")
    session.add(_audit(actor, team, "team.update"))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A team with this name already exists") from exc
    return await _serialize(session, team)


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    team = await _team(session, team_id, actor)
    team.status = "deleted"
    await session.execute(
        delete(TeamMembership).where(TeamMembership.team_id == team.id)
    )
    session.add(_audit(actor, team, "team.delete"))
    await session.commit()
    return {"message": "Team deleted successfully"}


@router.get("/{team_id}/members")
async def list_team_members(
    team_id: str,
    actor: UserRecord = Depends(require_permissions("users:read")),
    session: AsyncSession = Depends(get_db),
):
    team = await _team(session, team_id, actor)
    rows = (
        await session.execute(
            select(TeamMembership, User)
            .join(User, User.id == TeamMembership.user_id)
            .where(
                TeamMembership.team_id == team.id,
                User.deleted_at.is_(None),
            )
            .order_by(TeamMembership.membership_role, func.lower(User.name))
        )
    ).all()
    result = []
    for membership, user in rows:
        serialized = await serialize_user(session, user)
        serialized["membership_role"] = membership.membership_role
        serialized["membership_id"] = membership.id
        result.append(serialized)
    return result


@router.put("/{team_id}/members/{user_id}")
async def upsert_team_member(
    team_id: str,
    user_id: str,
    data: TeamMemberUpsert,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    team = await _team(session, team_id, actor)
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == team.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=422, detail="User does not belong to this organization")
    membership = await session.scalar(
        select(TeamMembership).where(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = TeamMembership(
            team_id=team.id,
            user_id=user.id,
            membership_role=data.membership_role,
        )
        session.add(membership)
    else:
        membership.membership_role = data.membership_role
    session.add(
        _audit(
            actor,
            team,
            "team.member.upsert",
            {"user_id": user.id, "membership_role": data.membership_role},
        )
    )
    await session.commit()
    return {"team_id": team.id, "user_id": user.id, "membership_role": membership.membership_role}


@router.delete("/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: str,
    user_id: str,
    actor: UserRecord = Depends(require_permissions("users:write")),
    session: AsyncSession = Depends(get_db),
):
    team = await _team(session, team_id, actor)
    membership = await session.scalar(
        select(TeamMembership).where(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Team membership not found")
    await session.delete(membership)
    session.add(_audit(actor, team, "team.member.remove", {"user_id": user_id}))
    await session.commit()
    return {"message": "Team member removed successfully"}
