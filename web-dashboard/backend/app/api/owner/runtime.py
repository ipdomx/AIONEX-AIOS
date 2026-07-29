"""Owner runtime projection backed by the shared dashboard stores."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import UserRecord, current_user
from app.core.identity_store import identity_store
from app.core.runtime_store import runtime_store

router = APIRouter(prefix="/owner/runtime", tags=["owner-runtime"])

ProjectStatus = Literal["active", "paused", "completed", "blocked"]
OrganizationStatus = Literal["active", "suspended", "pending"]
UserStatus = Literal["active", "suspended", "invited"]


class OwnerProject(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    organization: str
    status: ProjectStatus
    progress: int = Field(ge=0, le=100)
    updated_at: str = Field(alias="updatedAt")


class OwnerOrganization(BaseModel):
    id: str
    name: str
    users: int = Field(ge=0)
    projects: int = Field(ge=0)
    status: OrganizationStatus


class OwnerUser(BaseModel):
    id: str
    name: str
    email: str
    role: str
    organization: str
    status: UserStatus


class OwnerRuntimeSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    projects: list[OwnerProject]
    organizations: list[OwnerOrganization]
    users: list[OwnerUser]


def _normalized_role(role: str) -> str:
    return " ".join(role.strip().lower().replace("_", " ").replace("-", " ").split())


def _is_super_owner(actor: UserRecord) -> bool:
    return _normalized_role(actor.role) == "super owner"


def _project_status(value: object) -> ProjectStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"active", "running", "online", "in_progress"}:
        return "active"
    if normalized in {"completed", "complete", "done", "released"}:
        return "completed"
    if normalized in {"blocked", "failed", "error"}:
        return "blocked"
    return "paused"


def _organization_status(value: object) -> OrganizationStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"active", "online"}:
        return "active"
    if normalized in {"pending", "invited"}:
        return "pending"
    return "suspended"


def _user_status(value: object) -> UserStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"active", "online"}:
        return "active"
    if normalized in {"pending", "invited"}:
        return "invited"
    return "suspended"


def build_owner_runtime_snapshot(actor: UserRecord) -> OwnerRuntimeSnapshot:
    """Project existing runtime and identity state into the Owner UI contract."""

    super_owner = _is_super_owner(actor)
    project_rows = [
        project
        for project in runtime_store.projects.values()
        if not project.get("deleted")
        and (project.get("updated_at") or project.get("created_at"))
        and (super_owner or project.get("organization_id") == actor.organization_id)
    ]

    organization_records = [
        organization
        for organization in identity_store.organizations.values()
        if super_owner or organization.id == actor.organization_id
    ]
    organization_names = {
        organization.id: organization.name for organization in organization_records
    }
    organization_names.setdefault(actor.organization_id, actor.organization_name)

    identity_users = [
        user
        for user in identity_store.users.values()
        if user.deleted_at is None
        and (super_owner or user.organization_id == actor.organization_id)
    ]
    users = [
        OwnerUser(
            id=user.id,
            name=user.name,
            email=user.email,
            role=identity_store.get_role(user.role_id).name,
            organization=organization_names.get(
                user.organization_id, user.organization_id
            ),
            status=_user_status(user.status),
        )
        for user in identity_users
    ]
    if not any(user.id == actor.id for user in users):
        users.append(
            OwnerUser(
                id=actor.id,
                name=actor.name,
                email=actor.email,
                role=actor.role,
                organization=actor.organization_name,
                status=_user_status(actor.status),
            )
        )

    projects = [
        OwnerProject(
            id=str(project["id"]),
            name=str(project.get("name") or project["id"]),
            organization=str(
                project.get("organization")
                or organization_names.get(
                    str(project.get("organization_id") or ""), "Unknown organization"
                )
            ),
            status=_project_status(project.get("status")),
            progress=max(0, min(100, int(project.get("progress") or 0))),
            updated_at=str(project.get("updated_at") or project.get("created_at")),
        )
        for project in sorted(
            project_rows,
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
    ]

    organization_ids = set(organization_names)
    organizations = [
        OwnerOrganization(
            id=organization_id,
            name=organization_names[organization_id],
            users=sum(
                1
                for user in users
                if user.organization == organization_names[organization_id]
            ),
            projects=sum(
                1
                for project in project_rows
                if project.get("organization_id") == organization_id
            ),
            status=_organization_status(
                identity_store.organizations[organization_id].status
                if organization_id in identity_store.organizations
                else actor.status
            ),
        )
        for organization_id in sorted(organization_ids)
    ]

    return OwnerRuntimeSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        projects=projects,
        organizations=organizations,
        users=users,
    )


@router.get("", response_model=OwnerRuntimeSnapshot)
def get_owner_runtime(
    actor: UserRecord = Depends(current_user),
) -> OwnerRuntimeSnapshot:
    return build_owner_runtime_snapshot(actor)
