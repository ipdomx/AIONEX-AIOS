"""Verified, tenant-scoped knowledge, memory, and learning endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import KnowledgeItem, LearningEvent, Lesson, ScopedMemory
from app.services import adaptive_intelligence, knowledge_learning

router = APIRouter()


class ProvenanceCreate(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    source_type: str = Field(default="internal", min_length=1, max_length=80)
    author: str | None = Field(default=None, max_length=200)
    uri: str | None = Field(default=None, max_length=4000)
    checksum: str | None = Field(default=None, max_length=64)
    source_quality: float = Field(default=0.5, ge=0, le=1)
    direct_evidence: bool = True


class KnowledgeCreate(BaseModel):
    scope_type: Literal["organization", "workspace", "project", "user", "worker"]
    scope_id: str | None = None
    namespace: str = Field(default="default", min_length=1, max_length=120)
    subject: str = Field(min_length=2, max_length=300)
    content: dict[str, Any] = Field(default_factory=dict)
    content_text: str = Field(min_length=1, max_length=200000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=200)
    provenance: list[ProvenanceCreate] = Field(default_factory=list, max_length=100)
    supersedes_id: str | None = None


class KnowledgeDecision(BaseModel):
    accepted: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str = Field(default="", max_length=5000)


class MemoryUpsert(BaseModel):
    scope_type: Literal["organization", "workspace", "project", "user", "worker"]
    scope_id: str | None = None
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = Field(default=None, max_length=20000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source_item_id: str | None = None
    expires_at: datetime | None = None


class MemoryRevoke(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class LearningCreate(BaseModel):
    action: str = Field(min_length=2, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal["success", "failure", "partial", "unknown"]
    evidence: list[str] = Field(default_factory=list, max_length=200)
    strategy: str | None = Field(default=None, max_length=200)
    project_id: str | None = None
    worker_id: str | None = None
    assignment_id: str | None = None
    error: str | None = Field(default=None, max_length=20000)
    lesson: str | None = Field(default=None, max_length=20000)


class LearningDecision(BaseModel):
    accepted: bool
    note: str = Field(default="", max_length=5000)


class LessonPromote(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    lesson: str | None = Field(default=None, max_length=50000)
    confidence: float = Field(default=0.7, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=200)


async def _item(
    session: AsyncSession,
    actor: UserRecord,
    item_id: str,
    *,
    for_update: bool = False,
) -> KnowledgeItem:
    statement = select(KnowledgeItem).where(
        KnowledgeItem.id == item_id,
        KnowledgeItem.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    if (
        item.scope_type == "user"
        and item.scope_id != actor.id
        and "*" not in actor.permissions
        and "knowledge:manage" not in actor.permissions
    ):
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return item


async def _memory(
    session: AsyncSession,
    actor: UserRecord,
    memory_id: str,
    *,
    for_update: bool = False,
) -> ScopedMemory:
    statement = select(ScopedMemory).where(
        ScopedMemory.id == memory_id,
        ScopedMemory.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Scoped memory not found")
    if (
        item.scope_type == "user"
        and item.scope_id != actor.id
        and "*" not in actor.permissions
        and "knowledge:manage" not in actor.permissions
    ):
        raise HTTPException(status_code=404, detail="Scoped memory not found")
    return item


async def _learning_event(
    session: AsyncSession,
    actor: UserRecord,
    event_id: str,
    *,
    for_update: bool = False,
) -> LearningEvent:
    statement = select(LearningEvent).where(
        LearningEvent.id == event_id,
        LearningEvent.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Learning event not found")
    return item


@router.get("/items")
async def list_items(
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    namespace: str | None = Query(default=None, max_length=120),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    search: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(KnowledgeItem).where(
        KnowledgeItem.organization_id == actor.organization_id,
        KnowledgeItem.status != "archived",
    )
    if scope_type:
        try:
            normalized_type, normalized_id, _, _, _ = (
                await knowledge_learning.validate_scope(
                    session,
                    actor,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        statement = statement.where(
            KnowledgeItem.scope_type == normalized_type,
            KnowledgeItem.scope_id == normalized_id,
        )
    else:
        statement = statement.where(
            (KnowledgeItem.scope_type != "user")
            | (KnowledgeItem.scope_id == actor.id)
        )
    if namespace:
        statement = statement.where(KnowledgeItem.namespace == namespace.strip().lower())
    if status_filter:
        statement = statement.where(KnowledgeItem.status == status_filter)
    if search:
        normalized = search.strip()
        statement = statement.where(
            KnowledgeItem.subject.ilike(f"%{normalized}%")
            | KnowledgeItem.content_text.ilike(f"%{normalized}%")
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(KnowledgeItem.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return [knowledge_learning.item_snapshot(item) for item in rows]


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(
    data: KnowledgeCreate,
    actor: UserRecord = Depends(require_permissions("knowledge:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await knowledge_learning.ingest_item(
            session,
            actor,
            scope_type=data.scope_type,
            scope_id=data.scope_id,
            namespace=data.namespace,
            subject=data.subject,
            content=data.content,
            content_text=data.content_text,
            confidence=data.confidence,
            tags=data.tags,
            provenance=[value.model_dump(mode="json") for value in data.provenance],
            supersedes_id=data.supersedes_id,
        )
        await adaptive_intelligence.record_experience(
            session,
            actor,
            source="user",
            action="knowledge.item.submitted",
            context={
                "knowledge_item_id": item.id,
                "scope_type": item.scope_type,
                "scope_id": item.scope_id,
                "namespace": item.namespace,
                "subject": item.subject,
                "candidate_confidence": item.confidence,
            },
            outcome="success",
            evidence=[f"knowledge-checksum:{item.checksum}"],
            lesson=f"Candidate knowledge submitted: {item.subject}"[:4000],
            project_id=item.project_id,
        )
        await session.commit()
        await session.refresh(item)
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await knowledge_learning.item_with_provenance(session, item)


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_learning.item_with_provenance(
        session, await _item(session, actor, item_id)
    )


@router.post("/items/{item_id}/verify")
async def verify_item(
    item_id: str,
    data: KnowledgeDecision,
    actor: UserRecord = Depends(require_permissions("knowledge:verify")),
    session: AsyncSession = Depends(get_db),
):
    item = await _item(session, actor, item_id, for_update=True)
    try:
        await knowledge_learning.verify_item(
            session,
            actor,
            item,
            accepted=data.accepted,
            confidence=data.confidence,
            note=data.note,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await knowledge_learning.item_with_provenance(session, item)


@router.post("/items/{item_id}/archive")
async def archive_item(
    item_id: str,
    actor: UserRecord = Depends(require_permissions("knowledge:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await _item(session, actor, item_id, for_update=True)
    await knowledge_learning.archive_item(session, actor, item)
    await session.commit()
    return knowledge_learning.item_snapshot(item)


@router.get("/memories")
async def list_memories(
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    status_filter: str = Query(default="active", alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(ScopedMemory).where(
        ScopedMemory.organization_id == actor.organization_id,
        ScopedMemory.status == status_filter,
    )
    if scope_type:
        try:
            normalized_type, normalized_id, _, _, _ = (
                await knowledge_learning.validate_scope(
                    session,
                    actor,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        statement = statement.where(
            ScopedMemory.scope_type == normalized_type,
            ScopedMemory.scope_id == normalized_id,
        )
    else:
        statement = statement.where(
            (ScopedMemory.scope_type != "user")
            | (ScopedMemory.scope_id == actor.id)
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(ScopedMemory.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return [knowledge_learning.memory_snapshot(item) for item in rows]


@router.put("/memories")
async def upsert_memory(
    data: MemoryUpsert,
    actor: UserRecord = Depends(require_permissions("knowledge:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await knowledge_learning.upsert_memory(
            session,
            actor,
            scope_type=data.scope_type,
            scope_id=data.scope_id,
            key=data.key,
            value=data.value,
            summary=data.summary,
            confidence=data.confidence,
            source_item_id=data.source_item_id,
            expires_at=data.expires_at,
        )
        await session.commit()
        await session.refresh(item)
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return knowledge_learning.memory_snapshot(item)


@router.post("/memories/{memory_id}/revoke")
async def revoke_memory(
    memory_id: str,
    data: MemoryRevoke,
    actor: UserRecord = Depends(require_permissions("knowledge:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await _memory(session, actor, memory_id, for_update=True)
    await knowledge_learning.revoke_memory(
        session,
        actor,
        item,
        reason=data.reason,
    )
    await session.commit()
    return knowledge_learning.memory_snapshot(item)


@router.get("/learning-events")
async def list_learning_events(
    project_id: str | None = None,
    worker_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    outcome: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(LearningEvent).where(
        LearningEvent.organization_id == actor.organization_id
    )
    if project_id:
        statement = statement.where(LearningEvent.project_id == project_id)
    if worker_id:
        statement = statement.where(LearningEvent.worker_id == worker_id)
    if status_filter:
        statement = statement.where(LearningEvent.status == status_filter)
    if outcome:
        statement = statement.where(LearningEvent.outcome == outcome)
    rows = list(
        (
            await session.scalars(
                statement.order_by(LearningEvent.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [knowledge_learning.learning_snapshot(item) for item in rows]


@router.post("/learning-events", status_code=status.HTTP_201_CREATED)
async def create_learning_event(
    data: LearningCreate,
    actor: UserRecord = Depends(require_permissions("knowledge:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await knowledge_learning.create_learning_event(
            session,
            actor,
            action=data.action,
            context=data.context,
            outcome=data.outcome,
            evidence=data.evidence,
            strategy=data.strategy,
            project_id=data.project_id,
            worker_id=data.worker_id,
            assignment_id=data.assignment_id,
            error=data.error,
            lesson=data.lesson,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return knowledge_learning.learning_snapshot(item)


@router.post("/learning-events/{event_id}/verify")
async def verify_learning_event(
    event_id: str,
    data: LearningDecision,
    actor: UserRecord = Depends(require_permissions("knowledge:verify")),
    session: AsyncSession = Depends(get_db),
):
    item = await _learning_event(session, actor, event_id, for_update=True)
    try:
        await knowledge_learning.verify_learning_event(
            session,
            actor,
            item,
            accepted=data.accepted,
            note=data.note,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return knowledge_learning.learning_snapshot(item)


@router.post("/learning-events/{event_id}/promote", status_code=status.HTTP_201_CREATED)
async def promote_lesson(
    event_id: str,
    data: LessonPromote,
    actor: UserRecord = Depends(require_permissions("knowledge:verify")),
    session: AsyncSession = Depends(get_db),
):
    event = await _learning_event(session, actor, event_id)
    try:
        item = await knowledge_learning.promote_lesson(
            session,
            actor,
            event,
            title=data.title,
            lesson=data.lesson,
            confidence=data.confidence,
            tags=data.tags,
        )
        await session.commit()
        await session.refresh(item)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return knowledge_learning.lesson_snapshot(item)


@router.get("/lessons")
async def list_lessons(
    project_id: str | None = None,
    worker_id: str | None = None,
    status_filter: str = Query(default="verified", alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(Lesson).where(
        Lesson.organization_id == actor.organization_id,
        Lesson.status == status_filter,
    )
    if project_id:
        statement = statement.where(Lesson.project_id == project_id)
    if worker_id:
        statement = statement.where(Lesson.worker_id == worker_id)
    rows = list(
        (
            await session.scalars(
                statement.order_by(Lesson.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return [knowledge_learning.lesson_snapshot(item) for item in rows]


@router.get("/search")
async def search_knowledge(
    query: str = Query(min_length=1, max_length=300),
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    verified_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    actor: UserRecord = Depends(require_permissions("knowledge:read")),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await knowledge_learning.search_knowledge(
            session,
            actor,
            query=query,
            scope_type=scope_type,
            scope_id=scope_id,
            verified_only=verified_only,
            limit=limit,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
