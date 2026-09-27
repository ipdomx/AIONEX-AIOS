"""Transactional Owner policy and durable project-conversation admission.

Existing OwnerControlRecord and Job tables provide permanent scoped persistence;
no in-memory quota/session authority, schema rewrite, or provider call is used.
Policy hierarchy is global -> plan -> user for numeric limits, while a disabled
layer, account or organization always denies. One accepted turn costs one message
credit (not money); failed/ambiguous provider work is never automatically replayed.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, NoReturn
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ACTIVE_ORGANIZATION_STATUSES, UserRecord, auth_service
from app.db.models import AIAgent, AIProvider, AuditEvent, Job, Organization, OwnerControlRecord, Project, Role, User
from app.services.host_maintenance_admission import (
    HostMaintenanceClosed, HostMaintenanceUnavailable, require_admission_open,
)

POLICY = "conversation-governance-policy"
USAGE = "conversation-governance-usage"
THREAD_PREFIX = "project-conversation:"
JOB_TYPE = "governed_project_conversation"
GLOBAL = "global:default"
TERMINAL = frozenset({"completed", "failed", "cancelled", "needs_review"})


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
    max_projects: int = Field(default=1000, ge=0, le=100000)
    max_open_conversations: int = Field(default=20, ge=0, le=1000)
    max_open_conversations_per_project: int = Field(default=10, ge=0, le=1000)
    conversation_seconds: int = Field(default=3600, ge=1, le=31536000)
    messages_per_conversation: int = Field(default=1000, ge=0, le=100000)
    messages_per_day: int = Field(default=10000, ge=0, le=1000000)
    lifetime_message_credits: int = Field(default=-1, ge=-1, le=1000000000)
    max_message_characters: int = Field(default=12000, ge=1, le=50000)
    priority: int = Field(default=50, ge=0, le=100)
    default_agent_id: str = Field(default="", max_length=36, pattern=r"^[A-Za-z0-9_-]{0,36}$")


DEFAULTS = Limits().model_dump()


def _deny(code: str, status: int = 429) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code, "message": code.replace("_", " ").lower()})


def _uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail="A UUID identifier is required") from None
    if parsed != value.lower():
        raise HTTPException(status_code=422, detail="Canonical UUID identifier required")
    return parsed


def _entity_id(value: str) -> str:
    # The deployed schema deliberately retains legacy IDs such as owner-1.
    # New conversation IDs are UUIDs, but existing entity identifiers must not
    # be rewritten or rejected solely because they predate UUID defaults.
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,36}", value) is None:
        raise HTTPException(status_code=422, detail="A bounded entity identifier is required")
    return value


def scope_key(scope: str, identifier: str) -> str:
    if scope == "global" and identifier == "default":
        return GLOBAL
    if scope == "user":
        return "user:" + _entity_id(identifier)
    if scope == "plan" and re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", identifier):
        return "plan:" + identifier
    raise HTTPException(status_code=422, detail="Unsupported governance scope")


def _validate_values(value: Any, *, partial: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        _deny("GOVERNANCE_POLICY_INVALID", 503)
    try:
        normalized = Limits.model_validate({**DEFAULTS, **value}).model_dump()
    except ValidationError:
        _deny("GOVERNANCE_POLICY_INVALID", 503)
    return {key: normalized[key] for key in value} if partial else normalized


async def _clock(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime) or value.tzinfo is None:
        _deny("GOVERNANCE_CLOCK_UNAVAILABLE", 503)
    return value.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _record(session: AsyncSession, domain: str, resource: str,
                  *, lock: bool = False) -> OwnerControlRecord | None:
    statement = select(OwnerControlRecord).where(OwnerControlRecord.domain == domain,
                                                OwnerControlRecord.resource_id == resource)
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement.execution_options(populate_existing=True))


async def _global_guard(session: AsyncSession, *, exclusive: bool = False) -> OwnerControlRecord:
    statement = select(OwnerControlRecord).where(OwnerControlRecord.domain == POLICY,
                                                OwnerControlRecord.resource_id == GLOBAL)
    found = await session.scalar(statement)
    if found is None:
        now = await _clock(session)
        await session.execute(pg_insert(OwnerControlRecord).values(
            id=str(uuid4()), domain=POLICY, resource_id=GLOBAL, status="active", enabled=True,
            payload={"schema": 1, "values": DEFAULTS}, version=1, created_at=now, updated_at=now,
        ).on_conflict_do_nothing(constraint="uq_owner_control_domain_resource"))
    result = await session.scalar(statement.with_for_update(read=not exclusive)
                                  .execution_options(populate_existing=True))
    if result is None:
        _deny("GOVERNANCE_AUTHORITY_UNAVAILABLE", 503)
    return result


async def effective_policy(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    keys = [GLOBAL, "plan:" + actor.organization_plan.strip().lower(), "user:" + actor.id]
    rows = list((await session.scalars(select(OwnerControlRecord).where(
        OwnerControlRecord.domain == POLICY, OwnerControlRecord.resource_id.in_(keys),
    ).execution_options(populate_existing=True))).all())
    records = {row.resource_id: row for row in rows}
    values = dict(DEFAULTS)
    allowed = True
    versions: dict[str, int] = {}
    for key in keys:
        row = records.get(key)
        if row is None:
            versions[key] = 0
            continue
        if set(row.payload) != {"schema", "values"} or row.payload["schema"] != 1:
            _deny("GOVERNANCE_POLICY_INVALID", 503)
        patch = _validate_values(row.payload["values"], partial=True)
        if row.status not in {"active", "suspended"}:
            _deny("GOVERNANCE_POLICY_INVALID", 503)
        allowed = allowed and row.enabled and row.status == "active" and patch.get("enabled", True)
        values.update(patch)
        versions[key] = row.version
    values["enabled"] = bool(allowed)
    return {"values": values, "versions": versions,
            "hierarchy": "global -> plan -> user; disabled layers cannot be overridden",
            "credit_unit": "one accepted user turn; not currency"}


async def require_stream_allowed(session: AsyncSession, actor: UserRecord) -> None:
    if not (await effective_policy(session, actor))["values"]["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)


async def current_actor(session: AsyncSession, actor: UserRecord, *, lock: bool = False, permission: str | None = "projects:write") -> UserRecord:
    statement = select(User).where(User.id == actor.id, User.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement.execution_options(populate_existing=True))
    if row is None or row.organization_id != actor.organization_id or row.auth_version != actor.auth_version:
        _deny("USER_AUTHORITY_CHANGED", 403)
    await session.scalar(select(Organization).where(Organization.id == row.organization_id)
                         .execution_options(populate_existing=True))
    if row.role_id:
        await session.scalar(select(Role).where(Role.id == row.role_id)
                             .execution_options(populate_existing=True))
    fresh = await auth_service.get_user_by_id(session, actor.id)
    if permission is not None and "*" not in fresh.permissions and permission not in fresh.permissions:
        _deny("PROJECT_PERMISSION_REQUIRED", 403)
    return fresh


async def owner_target_actor(session: AsyncSession, owner: UserRecord, user_id: str,
                             *, lock: bool = False) -> UserRecord:
    """Administrative identity only; this must never authorize user dispatch.

    Banned users can still be inspected or have their conversations closed by a
    current Super Owner. Resume goes through normal live-user admission instead.
    """
    from app.core.auth import require_super_owner
    await require_super_owner(await current_actor(session, owner, permission=None))
    statement = select(User).where(User.id == _entity_id(user_id), User.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        _deny("USER_NOT_FOUND", 404)
    organization = await session.get(Organization, row.organization_id)
    role = await session.get(Role, row.role_id) if row.role_id else None
    if organization is None:
        _deny("ORGANIZATION_UNAVAILABLE", 503)
    return UserRecord(id=row.id, email=row.email, name=row.name,
        role=role.name if role else "Unassigned", password_hash="",
        organization_id=row.organization_id, organization_name=organization.name,
        organization_plan=organization.plan, permissions=[], status=row.status,
        auth_version=row.auth_version)


async def admission(session: AsyncSession, actor: UserRecord, *, permission: str = "projects:write") -> tuple[UserRecord, dict[str, Any], datetime]:
    try:
        await require_admission_open(session, required_scope="project_execution")
    except (HostMaintenanceClosed, HostMaintenanceUnavailable):
        _deny("MAINTENANCE_ADMISSION_CLOSED", 503)
    await _global_guard(session)
    actor = await current_actor(session, actor, lock=True, permission=permission)
    policy = (await effective_policy(session, actor))["values"]
    if not policy["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)
    return actor, policy, await _clock(session)


async def update_policy(session: AsyncSession, owner: UserRecord, *, scope: str,
                        identifier: str, values: dict[str, Any], expected_version: int) -> dict[str, Any]:
    from app.core.auth import require_super_owner
    fresh_owner = await current_actor(session, owner, permission=None)
    if fresh_owner.auth_version != owner.auth_version:
        _deny("OWNER_AUTHORITY_CHANGED", 403)
    await require_super_owner(fresh_owner)
    key = scope_key(scope, identifier)
    if not values:
        raise HTTPException(status_code=422, detail="At least one policy field is required")
    try:
        Limits.model_validate({**DEFAULTS, **values})
    except ValidationError:
        raise HTTPException(status_code=422, detail="Unsupported governance policy fields or values") from None
    if values.get("default_agent_id"):
        shared = await session.get(AIAgent, values["default_agent_id"])
        if shared is None or shared.organization_id != fresh_owner.organization_id:
            _deny("DEFAULT_ASSISTANT_MUST_BE_PLATFORM_OWNED", 422)
    gate = await _global_guard(session, exclusive=True)
    if scope == "user" and await session.get(User, identifier) is None:
        raise HTTPException(status_code=404, detail="User not found")
    row = gate if key == GLOBAL else await _record(session, POLICY, key, lock=True)
    actual = row.version if row else 0
    # Initialization is internal; the Owner may create the first default policy
    # with expected version zero only while its untouched baseline is present.
    baseline = key == GLOBAL and actual == 1 and row is not None and row.payload == {"schema": 1, "values": DEFAULTS}
    if expected_version != actual and not (expected_version == 0 and baseline):
        raise HTTPException(status_code=409, detail="Governance policy changed; refresh before editing")
    if row is None:
        row = OwnerControlRecord(id=str(uuid4()), domain=POLICY, resource_id=key,
                                 payload={"schema": 1, "values": {}}, version=0)
        session.add(row)
    old = dict(row.payload.get("values", {}))
    _validate_values(old, partial=True)
    merged = {**old, **values}
    row.payload = {"schema": 1, "values": _validate_values(merged, partial=True)}
    row.enabled = bool(merged.get("enabled", True))
    row.status = "active" if row.enabled else "suspended"
    row.version += 1
    session.add(AuditEvent(organization_id=owner.organization_id, user_id=owner.id,
        action="owner.conversation_governance.policy_updated", resource_type="governance_policy",
        resource_id=key, details={"scope": scope, "fields": sorted(values), "version": row.version}))
    await session.flush()
    return {"scope": scope, "identifier": identifier, "version": row.version,
            "values": dict(row.payload["values"])}


async def policy_records(session: AsyncSession) -> list[dict[str, Any]]:
    rows = list((await session.scalars(select(OwnerControlRecord).where(
        OwnerControlRecord.domain == POLICY).order_by(OwnerControlRecord.resource_id).limit(1000))).all())
    return [{"scope": row.resource_id.split(":", 1)[0], "identifier": row.resource_id.split(":", 1)[1],
             "version": row.version, "values": _validate_values(row.payload.get("values"), partial=True)} for row in rows]


async def _usage(session: AsyncSession, actor: UserRecord, *, lock: bool) -> OwnerControlRecord:
    row = await _record(session, USAGE, actor.id, lock=lock)
    if row is None:
        now = await _clock(session)
        await session.execute(pg_insert(OwnerControlRecord).values(
            id=str(uuid4()), domain=USAGE, resource_id=actor.id, status="active", enabled=True,
            payload={"schema": 1, "organization_id": actor.organization_id,
                     "day": now.date().isoformat(), "day_messages": 0, "total_messages": 0},
            version=1, created_at=now, updated_at=now,
        ).on_conflict_do_nothing(constraint="uq_owner_control_domain_resource"))
        row = await _record(session, USAGE, actor.id, lock=lock)
    if row is None:
        _deny("USAGE_UNAVAILABLE", 503)
    if row.payload.get("schema") != 1 or row.payload.get("organization_id") != actor.organization_id:
        _deny("USAGE_AUTHORITY_CHANGED", 503)
    for key in ("day_messages", "total_messages"):
        if type(row.payload.get(key)) is not int or row.payload[key] < 0:
            _deny("USAGE_COUNTER_INVALID", 503)
    try:
        date.fromisoformat(row.payload["day"])
    except (KeyError, ValueError, TypeError):
        _deny("USAGE_PERIOD_INVALID", 503)
    return row


async def consume_turn(session: AsyncSession, actor: UserRecord, policy: dict[str, Any], now: datetime) -> None:
    row = await _usage(session, actor, lock=True)
    payload = dict(row.payload)
    if date.fromisoformat(payload["day"]) > now.date():
        _deny("USAGE_PERIOD_IN_FUTURE", 503)
    if payload["day"] != now.date().isoformat():
        payload["day"] = now.date().isoformat()
        payload["day_messages"] = 0
    if payload["day_messages"] >= policy["messages_per_day"]:
        _deny("DAILY_MESSAGE_LIMIT")
    if policy["lifetime_message_credits"] >= 0 and payload["total_messages"] >= policy["lifetime_message_credits"]:
        _deny("MESSAGE_CREDITS_EXHAUSTED")
    payload["day_messages"] += 1
    payload["total_messages"] += 1
    row.payload = payload
    row.version += 1


async def usage_snapshot(session: AsyncSession, actor: UserRecord,
                         *, owner: UserRecord | None = None) -> dict[str, Any]:
    actor = (await current_actor(session, actor) if owner is None
             else await owner_target_actor(session, owner, actor.id))
    policy = await effective_policy(session, actor)
    now = await _clock(session)
    row = await _record(session, USAGE, actor.id)
    if row is None:
        used, total = 0, 0
    else:
        if row.payload.get("schema") != 1 or row.payload.get("organization_id") != actor.organization_id:
            _deny("USAGE_AUTHORITY_CHANGED", 503)
        for key in ("day_messages", "total_messages"):
            if type(row.payload.get(key)) is not int or row.payload[key] < 0:
                _deny("USAGE_COUNTER_INVALID", 503)
        try:
            day = date.fromisoformat(row.payload["day"])
        except (KeyError, ValueError, TypeError):
            _deny("USAGE_PERIOD_INVALID", 503)
        if day > now.date():
            _deny("USAGE_PERIOD_IN_FUTURE", 503)
        used = row.payload["day_messages"] if day == now.date() else 0
        total = row.payload["total_messages"]
    return {**policy, "usage": {"day": now.date().isoformat(), "day_messages": used,
                                "total_message_credits": total}}


async def project_capacity(session: AsyncSession, actor: UserRecord, owner_id: str,
                           *, administrator: UserRecord | None = None) -> None:
    if administrator is not None:
        from app.core.auth import require_super_owner
        await require_super_owner(await current_actor(session, administrator, permission=None))
    # Organization serialization protects the existing billing count+insert,
    # including simultaneous creations for different users of the same tenant.
    await _global_guard(session)
    org = await session.scalar(select(Organization).where(Organization.id == actor.organization_id)
                               .with_for_update().execution_options(populate_existing=True))
    if org is None or org.status not in ACTIVE_ORGANIZATION_STATUSES:
        _deny("ORGANIZATION_UNAVAILABLE", 403)
    actor = await current_actor(session, actor, permission=None if administrator is not None else "projects:write")
    if not (await effective_policy(session, actor))["values"]["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)
    owner = await auth_service.get_user_by_id(session, owner_id)
    if owner.organization_id != actor.organization_id:
        _deny("PROJECT_OWNER_SCOPE_INVALID", 403)
    policy = (await effective_policy(session, owner))["values"]
    if not policy["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)
    count = int(await session.scalar(select(func.count(Project.id)).where(
        Project.organization_id == owner.organization_id, Project.owner_id == owner.id,
        Project.status != "deleted")) or 0)
    if count >= policy["max_projects"]:
        _deny("USER_PROJECT_LIMIT")
    if owner.organization_plan.strip().lower() == "free" or owner.role.strip().lower() == "free user":
        from app.services.free_tier import assert_free_project_creation_allowed
        await assert_free_project_creation_allowed(session, owner)


async def owner_project_capacity(session: AsyncSession, owner: UserRecord, target_id: str) -> None:
    # Administrative creation/restoration is not a silent quota exception.
    # The Super Owner can deliberately change the user's policy beforehand.
    target = await owner_target_actor(session, owner, target_id)
    await project_capacity(session, target, target.id, administrator=owner)


def thread_domain(user_id: str) -> str:
    return THREAD_PREFIX + _entity_id(user_id)


def _thread_payload(row: OwnerControlRecord, actor: UserRecord) -> dict[str, Any]:
    value = row.payload
    if value.get("schema") != 1 or value.get("organization_id") != actor.organization_id or value.get("user_id") != actor.id:
        _deny("CONVERSATION_SCOPE_INVALID", 404)
    if type(value.get("messages")) is not int or value["messages"] < 0 or row.status not in {"open", "paused", "closed"}:
        _deny("CONVERSATION_STATE_INVALID", 503)
    return value


def thread_snapshot(row: OwnerControlRecord, actor: UserRecord, policy: dict[str, Any], now: datetime) -> dict[str, Any]:
    value = _thread_payload(row, actor)
    deadline = _utc(row.created_at) + timedelta(seconds=policy["conversation_seconds"])
    return {"id": row.resource_id, "project_id": value["project_id"], "user_id": actor.id,
            "title": value["title"], "status": row.status, "effective_status": "expired" if now >= deadline else row.status,
            "messages_used": value["messages"], "messages_allowed": policy["messages_per_conversation"],
            "opened_at": _utc(row.created_at).isoformat(), "expires_at": deadline.isoformat(),
            "seconds_remaining": max(0, int((deadline-now).total_seconds())), "version": row.version,
            "last_job_id": value.get("last_job_id"), "priority": policy["priority"]}


async def get_thread(session: AsyncSession, actor: UserRecord, conversation_id: str,
                     *, lock: bool = False) -> OwnerControlRecord:
    row = await _record(session, thread_domain(actor.id), _uuid(conversation_id), lock=lock)
    if row is None:
        _deny("CONVERSATION_NOT_FOUND", 404)
    _thread_payload(row, actor)
    return row


async def list_threads(session: AsyncSession, actor: UserRecord, project_id: str | None = None) -> list[dict[str, Any]]:
    actor = await current_actor(session, actor)
    policy = (await effective_policy(session, actor))["values"]
    if not policy["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)
    query = select(OwnerControlRecord).where(OwnerControlRecord.domain == thread_domain(actor.id))
    if project_id is not None:
        query = query.where(OwnerControlRecord.payload["project_id"].as_string() == _entity_id(project_id))
    rows = list((await session.scalars(query.order_by(OwnerControlRecord.created_at.desc()).limit(1000))).all())
    now = await _clock(session)
    return [thread_snapshot(row, actor, policy, now) for row in rows]


async def create_thread(session: AsyncSession, actor: UserRecord, *, project_id: str,
                        title: str, request_id: str) -> dict[str, Any]:
    actor, policy, now = await admission(session, actor)
    if not 1 <= len(title.strip()) <= 240 or not 8 <= len(request_id) <= 128:
        _deny("INVALID_CONVERSATION_INPUT", 422)
    project = await session.scalar(select(Project).where(Project.id == _entity_id(project_id),
        Project.organization_id == actor.organization_id, Project.status.notin_({"deleted", "cancelled", "archived"})))
    if project is None:
        _deny("PROJECT_NOT_FOUND", 404)
    # An idempotent request is bound to user+request and identical project/title.
    try:
        user_namespace = UUID(actor.id)
    except ValueError:
        user_namespace = uuid5(NAMESPACE_URL, "aionex:governed-user:" + _entity_id(actor.id))
    cid = str(uuid5(user_namespace, "project-conversation:" + request_id))
    prior = await _record(session, thread_domain(actor.id), cid)
    if prior is not None:
        value = _thread_payload(prior, actor)
        if value["project_id"] != project.id or value["title"] != title.strip():
            _deny("IDEMPOTENCY_CONTENT_CONFLICT", 409)
        return thread_snapshot(prior, actor, policy, now)
    predicate = and_(OwnerControlRecord.domain == thread_domain(actor.id),
                     OwnerControlRecord.status.in_({"open", "paused"}),
                     OwnerControlRecord.created_at > now-timedelta(seconds=policy["conversation_seconds"]))
    count = int(await session.scalar(select(func.count(OwnerControlRecord.id)).where(predicate)) or 0)
    per_project = int(await session.scalar(select(func.count(OwnerControlRecord.id)).where(
        predicate, OwnerControlRecord.payload["project_id"].as_string() == project.id)) or 0)
    if count >= policy["max_open_conversations"]:
        _deny("USER_CONVERSATION_LIMIT")
    if per_project >= policy["max_open_conversations_per_project"]:
        _deny("PROJECT_CONVERSATION_LIMIT")
    row = OwnerControlRecord(id=str(uuid4()), domain=thread_domain(actor.id), resource_id=cid,
        status="open", enabled=True, created_at=now, updated_at=now, version=1,
        payload={"schema": 1, "organization_id": actor.organization_id, "user_id": actor.id,
                 "project_id": project.id, "title": title.strip(), "messages": 0, "last_job_id": None})
    session.add(row)
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id,
        action="conversation.created", resource_type="project_conversation", resource_id=cid,
        details={"project_id": project.id, "policy_priority": policy["priority"]}))
    await session.flush()
    return thread_snapshot(row, actor, policy, now)


async def change_thread(session: AsyncSession, actor: UserRecord, conversation_id: str,
                        *, action: str, owner: UserRecord | None = None, note: str = "") -> dict[str, Any]:
    if owner is not None:
        from app.core.auth import require_super_owner
        owner = await require_super_owner(await current_actor(session, owner, permission=None))
    elif action != "close":
        _deny("OWNER_ACTION_REQUIRED", 403)
    await _global_guard(session, exclusive=owner is not None)
    actor = (await owner_target_actor(session, owner, actor.id, lock=True)
             if owner is not None and action != "resume"
             else await current_actor(session, actor, lock=True))
    row = await get_thread(session, actor, conversation_id, lock=True)
    if action not in {"pause", "resume", "close"}:
        _deny("INVALID_CONVERSATION_ACTION", 422)
    policy = (await effective_policy(session, actor))["values"]
    now = await _clock(session)
    if action == "resume" and (not policy["enabled"] or now >= _utc(row.created_at)+timedelta(seconds=policy["conversation_seconds"])):
        _deny("CONVERSATION_DURATION_EXCEEDED", 409)
    if action == "resume":
        # Closing a conversation releases a slot, so restoring it must reacquire
        # that slot under the same user lock used by creation. Never reset age
        # or usage, and apply the current Owner cap even after it is reduced.
        predicate = and_(OwnerControlRecord.domain == thread_domain(actor.id),
                         OwnerControlRecord.id != row.id,
                         OwnerControlRecord.status.in_({"open", "paused"}),
                         OwnerControlRecord.created_at > now-timedelta(seconds=policy["conversation_seconds"]))
        count = int(await session.scalar(select(func.count(OwnerControlRecord.id)).where(predicate)) or 0)
        per_project = int(await session.scalar(select(func.count(OwnerControlRecord.id)).where(
            predicate, OwnerControlRecord.payload["project_id"].as_string() == row.payload["project_id"])) or 0)
        if count >= policy["max_open_conversations"]:
            _deny("USER_CONVERSATION_LIMIT")
        if per_project >= policy["max_open_conversations_per_project"]:
            _deny("PROJECT_CONVERSATION_LIMIT")
    row.status = {"pause": "paused", "resume": "open", "close": "closed"}[action]
    row.enabled = row.status == "open"
    row.version += 1
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=(owner or actor).id,
        action="owner.conversation."+action if owner else "conversation.closed",
        resource_type="project_conversation", resource_id=row.resource_id,
        details={"note": note[:500], "counter_reset": False, "opened_at_reset": False}))
    await session.flush()
    return thread_snapshot(row, actor, policy, now)


async def messages(session: AsyncSession, actor: UserRecord, conversation_id: str) -> dict[str, Any]:
    actor = await current_actor(session, actor)
    policy = (await effective_policy(session, actor))["values"]
    if not policy["enabled"]:
        _deny("OWNER_ACCESS_SUSPENDED", 403)
    row = await get_thread(session, actor, conversation_id)
    rows = list((await session.scalars(select(Job).where(Job.organization_id == actor.organization_id,
        Job.type == JOB_TYPE, Job.payload["conversation_id"].as_string() == row.resource_id,
        Job.payload["requested_by_id"].as_string() == actor.id)
        .order_by(Job.created_at.desc(), Job.id.desc()).limit(200))).all())
    items = [{"id": job.id, "ordinal": job.payload["ordinal"], "user_message": job.payload["user_message"],
              "assistant_message": str((job.result or {}).get("text", "")) if job.status == "completed" else None,
              "status": job.status, "error": job.error, "created_at": _utc(job.created_at).isoformat(),
              "completed_at": _utc(job.finished_at).isoformat() if job.finished_at else None} for job in reversed(rows)]
    return {"conversation": thread_snapshot(row, actor, policy, await _clock(session)), "messages": items,
            "history_limit": 200}


async def conversation_agent(session: AsyncSession, actor: UserRecord, agent_id: str,
                             policy: dict[str, Any]) -> tuple[AIAgent, AIProvider]:
    selected = agent_id or policy["default_agent_id"]
    if not selected:
        _deny("CONVERSATION_ASSISTANT_NOT_CONFIGURED", 409)
    agent = await session.get(AIAgent, _entity_id(selected))
    provider = await session.get(AIProvider, agent.provider_id) if agent else None
    if (agent is None or provider is None or provider.organization_id != agent.organization_id
        or (agent.organization_id != actor.organization_id and agent.id != policy["default_agent_id"])):
        _deny("CONVERSATION_ASSISTANT_NOT_FOUND", 404)
    return agent, provider


async def send_message(session: AsyncSession, actor: UserRecord, conversation_id: str,
                       *, message: str, request_id: str, agent_id: str,
                       confirm_external_processing: bool) -> dict[str, Any]:
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
        _deny("INVALID_REQUEST_IDENTITY", 422)
    actor, policy, now = await admission(session, actor)
    row = await get_thread(session, actor, conversation_id, lock=True)
    value = _thread_payload(row, actor)
    project = await session.scalar(select(Project).where(
        Project.id == value["project_id"], Project.organization_id == actor.organization_id,
        Project.status.notin_({"deleted", "cancelled", "archived"})).with_for_update(read=True))
    if project is None:
        _deny("PROJECT_NOT_FOUND", 404)
    if row.status != "open":
        _deny("CONVERSATION_NOT_OPEN", 409)
    if now >= _utc(row.created_at)+timedelta(seconds=policy["conversation_seconds"]):
        _deny("CONVERSATION_DURATION_EXCEEDED", 409)
    clean = message.strip()
    if not clean or len(clean) > policy["max_message_characters"]:
        _deny("MESSAGE_LENGTH_LIMIT", 422)
    from app.services import ai_runtime_service as ai
    agent, provider = await conversation_agent(session, actor, agent_id, policy)
    if agent.status in {"paused", "disabled"} or not ai.provider_enabled(provider) or not ai.provider_configured(provider):
        _deny("CONVERSATION_PROVIDER_UNAVAILABLE", 409)
    if provider.type in {"aws_bedrock", "azure_openai"} or provider.type in ai.DEDICATED_3D_PROVIDER_TYPES:
        _deny("CONVERSATION_PROVIDER_NOT_SUPPORTED", 422)
    free = actor.role.strip().lower() == "free user" or actor.organization_plan.strip().lower() == "free"
    if provider.type != "ollama" and (free or not confirm_external_processing):
        _deny("EXTERNAL_PROCESSING_NOT_AUTHORIZED", 403 if free else 422)
    from app.core.owner_policy import require_owner_service_allowed
    await require_owner_service_allowed(session, provider.type)
    job_id = str(uuid5(UUID(row.resource_id), "user-turn:"+request_id))
    digest = hashlib.sha256((agent.id+"\0"+clean).encode()).hexdigest()
    prior = await session.get(Job, job_id)
    if prior is not None:
        if prior.type != JOB_TYPE or prior.organization_id != actor.organization_id or prior.payload.get("requested_by_id") != actor.id or prior.payload.get("request_digest") != digest:
            _deny("IDEMPOTENCY_CONTENT_CONFLICT", 409)
        return {"job_id": prior.id, "conversation_id": row.resource_id,
                "status": prior.status, "duplicate": True, "charged_again": False}
    previous_id = value.get("last_job_id")
    if previous_id:
        previous = await session.get(Job, previous_id)
        if previous is None or previous.type != JOB_TYPE or previous.status not in TERMINAL:
            _deny("CONVERSATION_TURN_PENDING", 409)
        if previous.status == "needs_review":
            _deny("CONVERSATION_PROVIDER_RECONCILIATION_REQUIRED", 409)
    if value["messages"] >= policy["messages_per_conversation"]:
        _deny("CONVERSATION_MESSAGE_LIMIT")
    await consume_turn(session, actor, policy, now)
    if free:
        from app.services.free_tier import consume_assistant_response, consume_user_message
        await consume_user_message(session, actor, characters=len(clean))
        await consume_assistant_response(session, actor)
    payload = dict(value)
    payload["messages"] += 1
    payload["last_job_id"] = job_id
    row.payload = payload
    row.version += 1
    job = Job(id=job_id, organization_id=actor.organization_id, agent_id=agent.id,
        type=JOB_TYPE, status="queued", created_at=now, updated_at=now,
        payload={"schema": 1, "conversation_id": row.resource_id, "project_id": payload["project_id"],
                 "requested_by_id": actor.id, "auth_version": actor.auth_version,
                 "user_message": clean, "ordinal": payload["messages"], "request_digest": digest,
                 "priority": policy["priority"], "external_processing_confirmed": confirm_external_processing,
                 "accepted_provider_id": provider.id, "accepted_provider_type": provider.type,
                 "accepted_agent_model": agent.model,
                 "accepted_policy_versions": (await effective_policy(session, actor))["versions"]}, result={})
    session.add(job)
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id,
        action="conversation.turn_accepted", resource_type="conversation_job", resource_id=job_id,
        details={"conversation_id": row.resource_id, "ordinal": payload["messages"],
                 "message_credits_reserved": 1, "provider_io_started": False}))
    await session.flush()
    return {"job_id": job_id, "conversation_id": row.resource_id, "status": "queued",
            "duplicate": False, "charged_again": False}


async def available_agents(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    actor = await current_actor(session, actor)
    await require_stream_allowed(session, actor)
    policy = (await effective_policy(session, actor))["values"]
    from app.services.ai_runtime_service import DEDICATED_3D_PROVIDER_TYPES, provider_configured, provider_enabled
    rows = (await session.execute(select(AIAgent, AIProvider).join(AIProvider, AIAgent.provider_id == AIProvider.id)
        .where(or_(AIAgent.organization_id == actor.organization_id,
                   AIAgent.id == policy["default_agent_id"]),
               AIProvider.organization_id == AIAgent.organization_id,
               AIAgent.status.notin_({"paused", "disabled"})).order_by(AIAgent.name).limit(100))).all()
    free = actor.role.strip().lower() == "free user" or actor.organization_plan.strip().lower() == "free"
    return [{"id": a.id, "name": a.name, "provider": p.type, "model": a.model,
             "external_processing": p.type != "ollama", "platform_shared": a.organization_id != actor.organization_id} for a, p in rows
            if p.type not in {"aws_bedrock", "azure_openai", *DEDICATED_3D_PROVIDER_TYPES}
            and provider_configured(p) and provider_enabled(p) and (not free or p.type == "ollama")]


async def owner_directory(session: AsyncSession, owner: UserRecord) -> dict[str, Any]:
    """Bounded directory metadata, never provider credentials or user messages."""
    from app.core.auth import require_super_owner
    from app.services.ai_runtime_service import provider_configured, provider_enabled, DEDICATED_3D_PROVIDER_TYPES
    owner = await require_super_owner(await current_actor(session, owner, permission=None))
    users = (await session.execute(select(User, Organization.plan)
        .join(Organization, User.organization_id == Organization.id)
        .where(User.deleted_at.is_(None)).order_by(User.name, User.id).limit(500))).all()
    assistants = (await session.execute(select(AIAgent, AIProvider)
        .join(AIProvider, AIAgent.provider_id == AIProvider.id)
        .where(AIAgent.organization_id == owner.organization_id,
               AIProvider.organization_id == owner.organization_id)
        .order_by(AIAgent.name, AIAgent.id).limit(100))).all()
    return {
        "users": [{"id": user.id, "name": user.name, "email": user.email,
                   "plan": plan, "status": user.status} for user, plan in users],
        "assistants": [{"id": agent.id, "name": agent.name, "model": agent.model,
                        "provider": provider.type,
                        "configured": provider_configured(provider) and provider_enabled(provider)
                            and agent.status not in {"paused", "disabled"}}
                       for agent, provider in assistants
                       if provider.type not in {"aws_bedrock", "azure_openai", *DEDICATED_3D_PROVIDER_TYPES}],
        "directory_limits": {"users": 500, "assistants": 100},
    }


async def owner_conversations(session: AsyncSession, owner: UserRecord, *, user_id: str | None = None) -> list[dict[str, Any]]:
    from app.core.auth import require_super_owner
    owner = await require_super_owner(await current_actor(session, owner, permission=None))
    statement = select(OwnerControlRecord).where(OwnerControlRecord.domain.like(THREAD_PREFIX+"%"))
    if user_id is not None:
        statement = statement.where(OwnerControlRecord.domain == thread_domain(user_id))
    rows = list((await session.scalars(statement.order_by(OwnerControlRecord.created_at.desc()).limit(500))).all())
    return [{"id": row.resource_id, "user_id": row.payload.get("user_id"),
             "organization_id": row.payload.get("organization_id"), "project_id": row.payload.get("project_id"),
             "title": row.payload.get("title"), "status": row.status,
             "messages_used": row.payload.get("messages"), "opened_at": _utc(row.created_at).isoformat(),
             "version": row.version, "last_job_id": row.payload.get("last_job_id")} for row in rows]


async def reset_policy(session: AsyncSession, owner: UserRecord, *, scope: str,
                       identifier: str, expected_version: int) -> dict[str, Any]:
    from app.core.auth import require_super_owner
    fresh = await current_actor(session, owner, permission=None)
    if fresh.auth_version != owner.auth_version:
        _deny("OWNER_AUTHORITY_CHANGED", 403)
    await require_super_owner(fresh)
    await _global_guard(session, exclusive=True)
    key = scope_key(scope, identifier)
    row = await _record(session, POLICY, key, lock=True)
    if row is None or row.version != expected_version:
        _deny("POLICY_VERSION_CONFLICT", 409)
    row.payload = {"schema": 1, "values": dict(DEFAULTS) if key == GLOBAL else {}}
    row.enabled, row.status = True, "active"
    row.version += 1
    session.add(AuditEvent(organization_id=owner.organization_id, user_id=owner.id,
        action="owner.conversation_governance.policy_reset", resource_type="governance_policy",
        resource_id=key, details={"version": row.version, "usage_reset": False}))
    await session.flush()
    return {"scope": scope, "identifier": identifier, "version": row.version,
            "values": dict(row.payload["values"])}


async def charge_project_request(session: AsyncSession, actor: UserRecord, *,
                                 characters: int, permission: str = "projects:write") -> dict[str, Any]:
    """Share daily/credit authority across chat, project objectives and agent jobs.

    Per-conversation duration/message counts apply only to an explicit durable
    conversation. This reservation shares the caller's commit or rollback.
    """
    actor, policy, now = await admission(session, actor, permission=permission)
    if characters < 1 or characters > policy["max_message_characters"]:
        _deny("MESSAGE_LENGTH_LIMIT", 422)
    await consume_turn(session, actor, policy, now)
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id,
        action="governance.project_message_reserved", resource_type="user_message_credit",
        resource_id=actor.id, details={"units": 1, "unit_is_currency": False,
                                      "permission": permission, "priority": policy["priority"]}))
    return policy
