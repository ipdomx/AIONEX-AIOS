"""Protected Owner entity operations backed by the existing endpoint services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.v1.endpoints.organizations import (
    OrganizationCreate,
    OrganizationUpdate,
    create_organization,
    deactivate_organization,
    update_organization,
)
from app.api.v1.endpoints.projects import (
    ProjectCreate,
    ProjectUpdate,
    create_project,
    delete_project,
    update_project,
)
from app.api.v1.endpoints.users import (
    UserCreate,
    UserUpdate,
    create_user,
    delete_user,
    update_user,
)
from app.core.auth import UserRecord, current_user
from app.core.identity_store import identity_store
from app.core.runtime_store import runtime_store

router = APIRouter(prefix="/owner/operations", tags=["owner-operations"])

OwnerEntityKind = Literal["project", "organization", "user"]
OwnerOperation = Literal["create", "update", "suspend", "restore", "delete"]


class OwnerOperationRequest(BaseModel):
    entity: OwnerEntityKind
    operation: OwnerOperation
    id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class OwnerOperationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ok: bool
    operation_id: str = Field(alias="operationId")
    message: str
    completed_at: str = Field(alias="completedAt")


def _validated(model: type[BaseModel], payload: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False),
        ) from exc


def _require_id(request: OwnerOperationRequest) -> str:
    if not request.id or not request.id.strip():
        raise HTTPException(
            status_code=422,
            detail=f"Record ID is required for {request.operation}",
        )
    return request.id.strip()


def _require_updates(model: BaseModel) -> None:
    if not model.model_dump(exclude_unset=True):
        raise HTTPException(
            status_code=422, detail="At least one update field is required"
        )


def _new_audit_event(
    before_runtime: set[str],
    before_identity: set[str],
) -> tuple[str, str]:
    for event in runtime_store.activities:
        if str(event.get("id")) not in before_runtime:
            return str(event["id"]), str(event.get("timestamp"))
    for event in identity_store.audit_events:
        if str(event.get("id")) not in before_identity:
            return str(event["id"]), str(event.get("timestamp"))
    raise HTTPException(
        status_code=500,
        detail="Operation completed without an audit record",
    )


async def _project_operation(
    request: OwnerOperationRequest,
    actor: UserRecord,
) -> str:
    if request.operation == "create":
        if request.id:
            raise HTTPException(
                status_code=422, detail="Record ID is not accepted for create"
            )
        data = _validated(ProjectCreate, request.payload)
        created = await create_project(data, actor)  # type: ignore[arg-type]
        return f"Project {created['id']} created"

    project_id = _require_id(request)
    if request.operation == "update":
        data = _validated(ProjectUpdate, request.payload)
        _require_updates(data)
        await update_project(project_id, data, actor)  # type: ignore[arg-type]
        return f"Project {project_id} updated"
    if request.operation == "suspend":
        await update_project(project_id, ProjectUpdate(status="paused"), actor)
        return f"Project {project_id} suspended"
    if request.operation == "restore":
        await update_project(project_id, ProjectUpdate(status="active"), actor)
        return f"Project {project_id} restored"

    await delete_project(project_id, actor)
    return f"Project {project_id} deleted"


async def _organization_operation(
    request: OwnerOperationRequest,
    actor: UserRecord,
) -> str:
    if request.operation == "create":
        if request.id:
            raise HTTPException(
                status_code=422, detail="Record ID is not accepted for create"
            )
        data = _validated(OrganizationCreate, request.payload)
        created = await create_organization(data, actor)  # type: ignore[arg-type]
        return f"Organization {created['id']} created"

    organization_id = _require_id(request)
    if request.operation == "update":
        data = _validated(OrganizationUpdate, request.payload)
        _require_updates(data)
        await update_organization(organization_id, data, actor)  # type: ignore[arg-type]
        return f"Organization {organization_id} updated"
    if request.operation == "suspend":
        await update_organization(
            organization_id,
            OrganizationUpdate(status="suspended"),
            actor,
        )
        return f"Organization {organization_id} suspended"
    if request.operation == "restore":
        await update_organization(
            organization_id,
            OrganizationUpdate(status="active"),
            actor,
        )
        return f"Organization {organization_id} restored"

    await deactivate_organization(organization_id, actor)
    return f"Organization {organization_id} deactivated"


async def _user_operation(
    request: OwnerOperationRequest,
    actor: UserRecord,
) -> str:
    if request.operation == "create":
        if request.id:
            raise HTTPException(
                status_code=422, detail="Record ID is not accepted for create"
            )
        if not str(request.payload.get("password") or "").strip():
            raise HTTPException(
                status_code=422,
                detail="An explicit password is required by the Owner operations contract",
            )
        data = _validated(UserCreate, request.payload)
        created = await create_user(data, actor)  # type: ignore[arg-type]
        return f"User {created['user']['id']} created"

    user_id = _require_id(request)
    if request.operation == "update":
        data = _validated(UserUpdate, request.payload)
        _require_updates(data)
        await update_user(user_id, data, actor)  # type: ignore[arg-type]
        return f"User {user_id} updated"
    if request.operation == "suspend":
        await update_user(user_id, UserUpdate(status="suspended"), actor)
        return f"User {user_id} suspended"
    if request.operation == "restore":
        await update_user(user_id, UserUpdate(status="active"), actor)
        return f"User {user_id} restored"

    await delete_user(user_id, actor)
    return f"User {user_id} deleted"


@router.post("", response_model=OwnerOperationResult)
async def execute_owner_operation(
    request: OwnerOperationRequest,
    actor: UserRecord = Depends(current_user),
) -> OwnerOperationResult:
    before_runtime = {
        str(event.get("id")) for event in runtime_store.activities if event.get("id")
    }
    before_identity = {
        str(event.get("id")) for event in identity_store.audit_events if event.get("id")
    }

    if request.entity == "project":
        message = await _project_operation(request, actor)
    elif request.entity == "organization":
        message = await _organization_operation(request, actor)
    else:
        message = await _user_operation(request, actor)

    operation_id, completed_at = _new_audit_event(before_runtime, before_identity)
    return OwnerOperationResult(
        ok=True,
        operation_id=operation_id,
        message=message,
        completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
    )
