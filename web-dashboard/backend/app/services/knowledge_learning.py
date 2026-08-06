"""Verified scoped knowledge, memory, provenance, and learning for Phase 29F."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    KnowledgeItem,
    KnowledgeProvenance,
    LearningEvent,
    Lesson,
    Project,
    ScopedMemory,
    User,
    WorkforceAssignment,
    WorkforceMember,
    Workspace,
    uuid_str,
)

SCOPE_TYPES = frozenset({"organization", "workspace", "project", "user", "worker"})
OUTCOMES = frozenset({"success", "failure", "partial", "unknown"})


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def item_snapshot(item: KnowledgeItem, provenance: Sequence[KnowledgeProvenance] = ()) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "workspace_id": item.workspace_id,
        "project_id": item.project_id,
        "worker_id": item.worker_id,
        "created_by_id": item.created_by_id,
        "verified_by_id": item.verified_by_id,
        "supersedes_id": item.supersedes_id,
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "namespace": item.namespace,
        "subject": item.subject,
        "content": item.content,
        "content_text": item.content_text,
        "confidence": item.confidence,
        "status": item.status,
        "checksum": item.checksum,
        "tags": item.tags,
        "version": item.version,
        "verified_at": iso(item.verified_at),
        "archived_at": iso(item.archived_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "provenance": [provenance_snapshot(value) for value in provenance],
    }


def provenance_snapshot(item: KnowledgeProvenance) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "source_type": item.source_type,
        "author": item.author,
        "uri": item.uri,
        "checksum": item.checksum,
        "source_quality": item.source_quality,
        "direct_evidence": item.direct_evidence,
        "collected_at": iso(item.collected_at),
    }


def memory_snapshot(item: ScopedMemory) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "created_by_id": item.created_by_id,
        "source_item_id": item.source_item_id,
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "key": item.key,
        "value": item.value,
        "summary": item.summary,
        "confidence": item.confidence,
        "status": item.status,
        "version": item.version,
        "expires_at": iso(item.expires_at),
        "revoked_at": iso(item.revoked_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def learning_snapshot(item: LearningEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "project_id": item.project_id,
        "worker_id": item.worker_id,
        "assignment_id": item.assignment_id,
        "created_by_id": item.created_by_id,
        "verified_by_id": item.verified_by_id,
        "action": item.action,
        "context_fingerprint": item.context_fingerprint,
        "outcome": item.outcome,
        "evidence": item.evidence,
        "strategy": item.strategy,
        "error_fingerprint": item.error_fingerprint,
        "lesson": item.lesson,
        "status": item.status,
        "verified_at": iso(item.verified_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def lesson_snapshot(item: Lesson) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "project_id": item.project_id,
        "worker_id": item.worker_id,
        "source_event_id": item.source_event_id,
        "promoted_by_id": item.promoted_by_id,
        "title": item.title,
        "lesson": item.lesson,
        "confidence": item.confidence,
        "status": item.status,
        "tags": item.tags,
        "version": item.version,
        "promoted_at": iso(item.promoted_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


async def validate_scope(
    session: AsyncSession,
    actor: UserRecord,
    *,
    scope_type: str,
    scope_id: str | None,
) -> tuple[str, str, str | None, str | None, str | None]:
    normalized = scope_type.strip().lower()
    if normalized not in SCOPE_TYPES:
        raise ValueError("Unsupported knowledge scope")
    if normalized == "organization":
        if scope_id and scope_id != actor.organization_id:
            raise PermissionError("Organization scope violation")
        return normalized, actor.organization_id, None, None, None
    identifier = (scope_id or "").strip()
    if not identifier:
        raise ValueError("A scope id is required")
    if normalized == "workspace":
        item = await session.scalar(
            select(Workspace).where(
                Workspace.id == identifier,
                Workspace.organization_id == actor.organization_id,
                Workspace.status != "deleted",
            )
        )
        if item is None:
            raise LookupError("Knowledge workspace not found")
        return normalized, identifier, item.id, None, None
    if normalized == "project":
        item = await session.scalar(
            select(Project).where(
                Project.id == identifier,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if item is None:
            raise LookupError("Knowledge project not found")
        return normalized, identifier, item.workspace_id, item.id, None
    if normalized == "user":
        item = await session.scalar(
            select(User).where(
                User.id == identifier,
                User.organization_id == actor.organization_id,
                User.deleted_at.is_(None),
            )
        )
        if item is None:
            raise LookupError("Knowledge user not found")
        if item.id != actor.id and "*" not in actor.permissions and "knowledge:manage" not in actor.permissions:
            raise PermissionError("User-scoped knowledge is private")
        return normalized, identifier, None, None, None
    worker = await session.scalar(
        select(WorkforceMember).where(
            WorkforceMember.id == identifier,
            WorkforceMember.organization_id == actor.organization_id,
            WorkforceMember.status != "retired",
        )
    )
    if worker is None:
        raise LookupError("Knowledge workforce member not found")
    return normalized, identifier, None, None, worker.id


async def ingest_item(
    session: AsyncSession,
    actor: UserRecord,
    *,
    scope_type: str,
    scope_id: str | None,
    namespace: str,
    subject: str,
    content: dict[str, Any],
    content_text: str,
    confidence: float,
    tags: Sequence[str] = (),
    provenance: Sequence[dict[str, Any]] = (),
    supersedes_id: str | None = None,
) -> KnowledgeItem:
    if confidence < 0 or confidence > 1:
        raise ValueError("Knowledge confidence must be between 0 and 1")
    normalized_scope, normalized_scope_id, workspace_id, project_id, worker_id = await validate_scope(
        session, actor, scope_type=scope_type, scope_id=scope_id
    )
    normalized_subject = subject.strip()
    normalized_text = content_text.strip()
    if len(normalized_subject) < 2 or not normalized_text:
        raise ValueError("Knowledge subject and content are required")
    digest = sha256(
        canonical_json(
            {
                "scope_type": normalized_scope,
                "scope_id": normalized_scope_id,
                "namespace": namespace.strip().lower(),
                "subject": normalized_subject,
                "content": content,
                "content_text": normalized_text,
            }
        )
    )
    existing = await session.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.organization_id == actor.organization_id,
            KnowledgeItem.checksum == digest,
        )
    )
    if existing is not None:
        return existing
    if supersedes_id:
        superseded = await session.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.id == supersedes_id,
                KnowledgeItem.organization_id == actor.organization_id,
            )
        )
        if superseded is None:
            raise LookupError("Superseded knowledge item not found")
    item = KnowledgeItem(
        id=uuid_str(),
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        worker_id=worker_id,
        created_by_id=actor.id,
        supersedes_id=supersedes_id,
        scope_type=normalized_scope,
        scope_id=normalized_scope_id,
        namespace=namespace.strip().lower() or "default",
        subject=normalized_subject,
        content=content,
        content_text=normalized_text,
        confidence=confidence,
        status="draft",
        checksum=digest,
        tags=sorted({value.strip().lower() for value in tags if value.strip()}),
        version=1,
    )
    session.add(item)
    await session.flush()
    for raw in provenance:
        source = str(raw.get("source") or "").strip()
        if not source:
            raise ValueError("Every provenance record requires a source")
        quality = float(raw.get("source_quality", 0.5))
        if quality < 0 or quality > 1:
            raise ValueError("Provenance source quality must be between 0 and 1")
        session.add(
            KnowledgeProvenance(
                id=uuid_str(),
                knowledge_item_id=item.id,
                source=source,
                source_type=str(raw.get("source_type") or "internal").strip().lower(),
                author=(str(raw.get("author") or "").strip() or None),
                uri=(str(raw.get("uri") or "").strip() or None),
                checksum=(str(raw.get("checksum") or "").strip() or None),
                source_quality=quality,
                direct_evidence=bool(raw.get("direct_evidence", True)),
                collected_at=now(),
            )
        )
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="knowledge.item.ingested",
            resource_type="knowledge_item",
            resource_id=item.id,
            details={
                "scope_type": item.scope_type,
                "scope_id": item.scope_id,
                "checksum": item.checksum,
                "provenance_count": len(provenance),
            },
        )
    )
    return item


async def verify_item(
    session: AsyncSession,
    actor: UserRecord,
    item: KnowledgeItem,
    *,
    accepted: bool,
    confidence: float | None = None,
    note: str = "",
) -> KnowledgeItem:
    if item.status == "archived":
        raise ValueError("Archived knowledge cannot be verified")
    if confidence is not None:
        if confidence < 0 or confidence > 1:
            raise ValueError("Knowledge confidence must be between 0 and 1")
        item.confidence = confidence
    item.status = "verified" if accepted else "rejected"
    item.verified_by_id = actor.id
    item.verified_at = now()
    item.version += 1
    if accepted and item.supersedes_id:
        superseded = await session.get(KnowledgeItem, item.supersedes_id)
        if superseded is not None and superseded.organization_id == item.organization_id:
            superseded.status = "superseded"
            superseded.version += 1
    session.add(
        AuditEvent(
            organization_id=item.organization_id,
            user_id=actor.id,
            action="knowledge.item.verified" if accepted else "knowledge.item.rejected",
            resource_type="knowledge_item",
            resource_id=item.id,
            details={"confidence": item.confidence, "note": note.strip() or None},
        )
    )
    return item


async def archive_item(
    session: AsyncSession, actor: UserRecord, item: KnowledgeItem
) -> KnowledgeItem:
    if item.status == "archived":
        return item
    item.status = "archived"
    item.archived_at = now()
    item.version += 1
    session.add(
        AuditEvent(
            organization_id=item.organization_id,
            user_id=actor.id,
            action="knowledge.item.archived",
            resource_type="knowledge_item",
            resource_id=item.id,
            details={"version": item.version},
        )
    )
    return item


async def item_with_provenance(
    session: AsyncSession, item: KnowledgeItem
) -> dict[str, Any]:
    provenance = list(
        (
            await session.scalars(
                select(KnowledgeProvenance)
                .where(KnowledgeProvenance.knowledge_item_id == item.id)
                .order_by(KnowledgeProvenance.collected_at)
            )
        ).all()
    )
    return item_snapshot(item, provenance)


async def upsert_memory(
    session: AsyncSession,
    actor: UserRecord,
    *,
    scope_type: str,
    scope_id: str | None,
    key: str,
    value: dict[str, Any],
    summary: str | None,
    confidence: float,
    source_item_id: str | None = None,
    expires_at: datetime | None = None,
) -> ScopedMemory:
    if confidence < 0 or confidence > 1:
        raise ValueError("Memory confidence must be between 0 and 1")
    normalized_scope, normalized_scope_id, _, _, _ = await validate_scope(
        session, actor, scope_type=scope_type, scope_id=scope_id
    )
    normalized_key = key.strip().lower()
    if not normalized_key or len(normalized_key) > 200:
        raise ValueError("Memory key is invalid")
    if source_item_id:
        source = await session.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.id == source_item_id,
                KnowledgeItem.organization_id == actor.organization_id,
                KnowledgeItem.status == "verified",
            )
        )
        if source is None:
            raise LookupError("Verified memory source was not found")
    item = await session.scalar(
        select(ScopedMemory)
        .where(
            ScopedMemory.organization_id == actor.organization_id,
            ScopedMemory.scope_type == normalized_scope,
            ScopedMemory.scope_id == normalized_scope_id,
            ScopedMemory.key == normalized_key,
        )
        .with_for_update()
    )
    if item is None:
        item = ScopedMemory(
            id=uuid_str(),
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            scope_type=normalized_scope,
            scope_id=normalized_scope_id,
            key=normalized_key,
            version=1,
        )
        session.add(item)
    else:
        item.version += 1
    item.source_item_id = source_item_id
    item.value = value
    item.summary = (summary or "").strip() or None
    item.confidence = confidence
    item.status = "active"
    item.expires_at = expires_at
    item.revoked_at = None
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="memory.upserted",
            resource_type="scoped_memory",
            resource_id=item.id,
            details={"scope_type": normalized_scope, "scope_id": normalized_scope_id, "key": normalized_key, "version": item.version},
        )
    )
    await session.flush()
    return item


async def revoke_memory(
    session: AsyncSession,
    actor: UserRecord,
    item: ScopedMemory,
    *,
    reason: str,
) -> ScopedMemory:
    item.status = "revoked"
    item.revoked_at = now()
    item.version += 1
    session.add(
        AuditEvent(
            organization_id=item.organization_id,
            user_id=actor.id,
            action="memory.revoked",
            resource_type="scoped_memory",
            resource_id=item.id,
            details={"reason": reason.strip() or None, "version": item.version},
        )
    )
    return item


async def create_learning_event(
    session: AsyncSession,
    actor: UserRecord,
    *,
    action: str,
    context: dict[str, Any],
    outcome: str,
    evidence: Sequence[str],
    strategy: str | None = None,
    project_id: str | None = None,
    worker_id: str | None = None,
    assignment_id: str | None = None,
    error: str | None = None,
    lesson: str | None = None,
) -> LearningEvent:
    if outcome not in OUTCOMES:
        raise ValueError("Unsupported learning outcome")
    if project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if project is None:
            raise LookupError("Learning project not found")
    if worker_id:
        worker = await session.scalar(
            select(WorkforceMember).where(
                WorkforceMember.id == worker_id,
                WorkforceMember.organization_id == actor.organization_id,
            )
        )
        if worker is None:
            raise LookupError("Learning workforce member not found")
    if assignment_id:
        assignment = await session.scalar(
            select(WorkforceAssignment).where(
                WorkforceAssignment.id == assignment_id,
                WorkforceAssignment.organization_id == actor.organization_id,
            )
        )
        if assignment is None:
            raise LookupError("Learning assignment not found")
    context_fingerprint = sha256(canonical_json(context))
    error_fingerprint = sha256(error.strip()) if error and error.strip() else None
    item = LearningEvent(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=project_id,
        worker_id=worker_id,
        assignment_id=assignment_id,
        created_by_id=actor.id,
        action=action.strip(),
        context_fingerprint=context_fingerprint,
        outcome=outcome,
        evidence=list(dict.fromkeys(value.strip() for value in evidence if value.strip())),
        strategy=(strategy or "").strip() or None,
        error_fingerprint=error_fingerprint,
        lesson=(lesson or "").strip() or None,
        status="recorded",
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="learning.event.recorded",
            resource_type="learning_event",
            resource_id=item.id,
            details={"outcome": outcome, "context_fingerprint": context_fingerprint, "evidence_count": len(item.evidence)},
        )
    )
    await session.flush()
    return item


async def verify_learning_event(
    session: AsyncSession,
    actor: UserRecord,
    item: LearningEvent,
    *,
    accepted: bool,
    note: str = "",
) -> LearningEvent:
    if item.status in {"verified", "rejected"}:
        if (item.status == "verified") == accepted:
            return item
        raise ValueError("Learning event already has a terminal decision")
    item.status = "verified" if accepted else "rejected"
    item.verified_by_id = actor.id
    item.verified_at = now()
    session.add(
        AuditEvent(
            organization_id=item.organization_id,
            user_id=actor.id,
            action="learning.event.verified" if accepted else "learning.event.rejected",
            resource_type="learning_event",
            resource_id=item.id,
            details={"note": note.strip() or None},
        )
    )
    return item


async def promote_lesson(
    session: AsyncSession,
    actor: UserRecord,
    event: LearningEvent,
    *,
    title: str,
    lesson: str | None,
    confidence: float,
    tags: Sequence[str] = (),
) -> Lesson:
    if event.status != "verified":
        raise ValueError("Only verified learning can be promoted")
    if confidence < 0 or confidence > 1:
        raise ValueError("Lesson confidence must be between 0 and 1")
    existing = await session.scalar(
        select(Lesson).where(
            Lesson.organization_id == actor.organization_id,
            Lesson.source_event_id == event.id,
            Lesson.status != "retired",
        )
    )
    if existing is not None:
        return existing
    body = (lesson or event.lesson or "").strip()
    if not body:
        raise ValueError("Promoted lesson content is required")
    item = Lesson(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=event.project_id,
        worker_id=event.worker_id,
        source_event_id=event.id,
        promoted_by_id=actor.id,
        title=title.strip(),
        lesson=body,
        confidence=confidence,
        status="verified",
        tags=sorted({value.strip().lower() for value in tags if value.strip()}),
        version=1,
        promoted_at=now(),
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="lesson.promoted",
            resource_type="lesson",
            resource_id=item.id,
            details={"source_event_id": event.id, "confidence": confidence},
        )
    )
    await session.flush()
    return item


async def search_knowledge(
    session: AsyncSession,
    actor: UserRecord,
    *,
    query: str,
    scope_type: str | None = None,
    scope_id: str | None = None,
    verified_only: bool = True,
    limit: int = 100,
) -> dict[str, list[dict[str, Any]]]:
    normalized = query.strip()
    item_statement = select(KnowledgeItem).where(
        KnowledgeItem.organization_id == actor.organization_id,
        KnowledgeItem.status == "verified" if verified_only else KnowledgeItem.status != "archived",
        or_(
            KnowledgeItem.subject.ilike(f"%{normalized}%"),
            KnowledgeItem.content_text.ilike(f"%{normalized}%"),
            KnowledgeItem.namespace.ilike(f"%{normalized}%"),
        ),
    )
    memory_statement = select(ScopedMemory).where(
        ScopedMemory.organization_id == actor.organization_id,
        ScopedMemory.status == "active",
        or_(
            ScopedMemory.key.ilike(f"%{normalized}%"),
            ScopedMemory.summary.ilike(f"%{normalized}%"),
        ),
    )
    lesson_statement = select(Lesson).where(
        Lesson.organization_id == actor.organization_id,
        Lesson.status == "verified",
        or_(Lesson.title.ilike(f"%{normalized}%"), Lesson.lesson.ilike(f"%{normalized}%")),
    )
    if scope_type:
        validated_type, validated_id, _, _, _ = await validate_scope(
            session, actor, scope_type=scope_type, scope_id=scope_id
        )
        item_statement = item_statement.where(
            KnowledgeItem.scope_type == validated_type,
            KnowledgeItem.scope_id == validated_id,
        )
        memory_statement = memory_statement.where(
            ScopedMemory.scope_type == validated_type,
            ScopedMemory.scope_id == validated_id,
        )
    items = list((await session.scalars(item_statement.order_by(KnowledgeItem.updated_at.desc()).limit(limit))).all())
    memories = list((await session.scalars(memory_statement.order_by(ScopedMemory.updated_at.desc()).limit(limit))).all())
    lessons = list((await session.scalars(lesson_statement.order_by(Lesson.updated_at.desc()).limit(limit))).all())
    return {
        "knowledge": [item_snapshot(item) for item in items],
        "memories": [memory_snapshot(item) for item in memories],
        "lessons": [lesson_snapshot(item) for item in lessons],
    }
