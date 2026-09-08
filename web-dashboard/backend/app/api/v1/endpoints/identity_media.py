"""User-facing governed identity-media launch surface."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.phase36_identity_media import IdentityMediaPolicyError, IdentityMediaRequest
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import get_db
from app.db.models import AuditEvent, IdentityMediaExecution, Project
from app.services import identity_media_access
from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    model_for_operation,
)
from app.services.identity_media_runtime import (
    IdentityMediaExecutionError,
    arm_execution,
    create_execution,
    public_execution,
)
from app.services.media_storage import MediaStorageError, media_object_store

router = APIRouter(prefix="/studio/identity-media", tags=["Studio Identity Media"])

_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_AUDIO_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"})
_VIDEO_TYPES = frozenset({"video/mp4"})
_MAX_IMAGE = 12 * 1024 * 1024
_MAX_AUDIO = 20 * 1024 * 1024
_MAX_VIDEO = 100 * 1024 * 1024
_RIGHTS_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "text/plain"})
_MAX_RIGHTS = 5 * 1024 * 1024
_RUNTIME_MODELS = {
    "voice_clone": "minimax/voice-cloning",
    "face_reenactment": "prunaai/p-video-avatar",
    "talking_head": "prunaai/p-video-avatar",
    "avatar_generation": "prunaai/p-video-avatar",
    "lip_sync": "sync/lipsync-2",
}


def _safe_filename(value: str | None, fallback: str) -> str:
    name = Path(str(value or "").strip()).name
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {".", "-", "_"})
    return (safe[:120] or fallback)


def _valid_envelope(kind: str, body: bytes) -> bool:
    if kind == "image":
        return (
            body.startswith(b"\x89PNG\r\n\x1a\n")
            or body.startswith(b"\xff\xd8\xff")
            or (len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP")
        )
    if kind == "audio":
        return (
            body.startswith(b"RIFF") and len(body) >= 12 and body[8:12] == b"WAVE"
        ) or body.startswith(b"ID3") or (
            len(body) > 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0
        ) or (len(body) >= 12 and body[4:8] == b"ftyp")
    if kind == "video":
        return len(body) >= 12 and body[4:8] == b"ftyp"
    return False


async def _read_upload(upload: UploadFile, *, kind: str) -> tuple[bytes, str, str]:
    content_type = str(upload.content_type or "").split(";", 1)[0].strip().lower()
    allowed = _IMAGE_TYPES if kind == "image" else _AUDIO_TYPES if kind == "audio" else _VIDEO_TYPES
    maximum = _MAX_IMAGE if kind == "image" else _MAX_AUDIO if kind == "audio" else _MAX_VIDEO
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported {kind} content type")
    body = await upload.read(maximum + 1)
    if not body or len(body) > maximum or not _valid_envelope(kind, body):
        raise HTTPException(status_code=422, detail=f"Invalid or oversized {kind} input")
    return body, content_type, _safe_filename(upload.filename, f"source-{kind}")


async def _read_rights_evidence(upload: UploadFile) -> tuple[bytes, str, str]:
    content_type = str(upload.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _RIGHTS_TYPES:
        raise HTTPException(status_code=415, detail="Rights evidence must be PDF, PNG, JPEG, or text")
    body = await upload.read(_MAX_RIGHTS + 1)
    if not body or len(body) > _MAX_RIGHTS:
        raise HTTPException(status_code=422, detail="Rights evidence is empty or exceeds 5 MB")
    if content_type == "application/pdf" and not body.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Rights evidence PDF envelope is invalid")
    if content_type == "image/png" and not body.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="Rights evidence PNG envelope is invalid")
    if content_type == "image/jpeg" and not body.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=422, detail="Rights evidence JPEG envelope is invalid")
    return body, content_type, _safe_filename(upload.filename, "rights-evidence")


async def _project_scope(session: AsyncSession, actor: UserRecord, project_id: str | None) -> str | None:
    value = str(project_id or "").strip() or None
    if value is None:
        return None
    exists = await session.scalar(
        select(Project.id).where(
            Project.id == value,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Project not found")
    return value


@router.get("/capabilities")
async def capabilities(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    snapshot = await identity_media_access.user_access_snapshot(session, actor)
    configured = bool(str(settings.REPLICATE_API_TOKEN or "").strip())
    live = bool(settings.IDENTITY_MEDIA_LIVE_ENABLED and configured)
    for item in snapshot["operations"]:
        item["runtime_ready"] = bool(item["runtime_ready"] and live)
        item["fictional_inspired_direct"] = bool(item["fictional_inspired_direct"] and live)
        item["model"] = _RUNTIME_MODELS.get(item["operation"])
    snapshot.update(
        {
            "provider": "replicate" if configured else None,
            "worker_live": bool(settings.IDENTITY_MEDIA_LIVE_ENABLED),
            "provider_configured": configured,
            "licensed_public_figure_runtime_ready": False,
            "free_provider_route_ready": False,
            "paid_provider_route_ready": live,
            "raw_credentials_returned": False,
        }
    )
    return snapshot


@router.get("/access-requests")
async def my_access_requests(
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"requests": await identity_media_access.list_user_requests(session, actor)}


@router.post("/access-requests", status_code=201)
async def request_access(
    operation: Annotated[str, Form()],
    identity_basis: Annotated[str, Form()],
    subject_reference: Annotated[str, Form(min_length=1, max_length=200)],
    reason: Annotated[str, Form(max_length=1000)] = "",
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await identity_media_access.submit_access_request(
            session,
            actor,
            operation=operation,
            identity_basis=identity_basis,
            subject_reference=subject_reference,
            reason=reason,
        )
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/executions", status_code=202)
async def create_identity_execution(
    operation: Annotated[str, Form()],
    identity_basis: Annotated[str, Form()],
    subject_reference: Annotated[str, Form(min_length=1, max_length=200)],
    idempotency_key: Annotated[str, Form(min_length=8, max_length=160)],
    synthetic_media_disclosure_accepted: Annotated[bool, Form()],
    approved_max_cost_usd: Annotated[float, Form(gt=0, le=25.0)],
    script: Annotated[str, Form(max_length=10000)] = "",
    estimated_duration_seconds: Annotated[float, Form(ge=1, le=60)] = 10.0,
    project_id: Annotated[str | None, Form(max_length=36)] = None,
    rights_evidence_sha256: Annotated[str | None, Form(max_length=64)] = None,
    rights_attestation_accepted: Annotated[bool, Form()] = False,
    license_reference: Annotated[str | None, Form(max_length=500)] = None,
    named_real_person_reference: Annotated[str | None, Form(max_length=200)] = None,
    commercial_use_requested: Annotated[bool, Form()] = False,
    commercial_use_authorized: Annotated[bool, Form()] = False,
    claims_real_identity: Annotated[bool, Form()] = False,
    source_image: UploadFile | None = File(default=None),
    source_audio: UploadFile | None = File(default=None),
    source_video: UploadFile | None = File(default=None),
    rights_evidence_file: UploadFile | None = File(default=None),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not settings.IDENTITY_MEDIA_LIVE_ENABLED:
        raise HTTPException(status_code=503, detail="Identity Media runtime is not live")
    if not str(settings.REPLICATE_API_TOKEN or "").strip():
        raise HTTPException(status_code=503, detail="Identity Media provider is not configured")
    if operation not in _RUNTIME_MODELS:
        raise HTTPException(status_code=503, detail="This Identity Media operation is visible but runtime acceptance is pending")
    if identity_basis == "licensed_public_figure":
        raise HTTPException(
            status_code=503,
            detail="Licensed public-figure execution is pending a licensed-catalog runtime; Owner approval alone is not a likeness license",
        )
    access = await identity_media_access.effective_access(
        session,
        actor,
        operation=operation,
        identity_basis=identity_basis,
        subject_reference=subject_reference,
    )
    if not access.allowed:
        status_code = 403 if access.owner_approval_required else 503
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": "IDENTITY_MEDIA_OWNER_APPROVAL_REQUIRED" if access.owner_approval_required else "IDENTITY_MEDIA_RUNTIME_PENDING",
                "reason": access.reason,
                "operation": operation,
                "owner_approval_required": access.owner_approval_required,
            },
        )
    effective_rights_sha = str(rights_evidence_sha256 or "").strip().lower() or None
    rights_body: bytes | None = None
    rights_content_type: str | None = None
    rights_filename: str | None = None
    rights_evidence_source = "provided-sha256" if effective_rights_sha else None
    if identity_basis == "self" and effective_rights_sha is None:
        if not rights_attestation_accepted:
            raise HTTPException(
                status_code=422,
                detail="Self identity use requires the rights/self-identity attestation",
            )
        attestation = (
            "AIONEX.IDENTITY_MEDIA.SELF_RIGHTS.v1\n"
            f"user={actor.id}\noperation={operation}\nsubject={subject_reference.strip()}\n"
            f"commercial_requested={bool(commercial_use_requested)}\n"
            f"commercial_authorized={bool(commercial_use_authorized)}"
        )
        effective_rights_sha = sha256(attestation.encode("utf-8")).hexdigest()
        rights_evidence_source = "durable-self-attestation-v1"
    elif identity_basis == "consented_person" and effective_rights_sha is None:
        if rights_evidence_file is None:
            raise HTTPException(
                status_code=422,
                detail="Consented-person identity use requires a consent/rights evidence file",
            )
        rights_body, rights_content_type, rights_filename = await _read_rights_evidence(rights_evidence_file)
        effective_rights_sha = sha256(rights_body).hexdigest()
        rights_evidence_source = "uploaded-private-evidence"

    try:
        decision = IdentityMediaRequest(
            operation=operation,  # type: ignore[arg-type]
            identity_basis=identity_basis,  # type: ignore[arg-type]
            provider_access="paid",
            subject_reference=subject_reference,
            synthetic_media_disclosure_accepted=synthetic_media_disclosure_accepted,
            rights_evidence_sha256=effective_rights_sha,
            license_reference=license_reference,
            commercial_use_requested=commercial_use_requested,
            commercial_use_authorized=commercial_use_authorized,
            claims_real_identity=claims_real_identity,
            named_real_person_reference=named_real_person_reference,
        ).validate()
    except IdentityMediaPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    required = {
        "voice_clone": (False, True, False),
        "face_reenactment": (True, False, False),
        "talking_head": (True, False, False),
        "avatar_generation": (True, False, False),
        "lip_sync": (False, True, True),
    }[operation]
    if required[0] and source_image is None:
        raise HTTPException(status_code=422, detail="Source image is required")
    if required[1] and source_audio is None:
        raise HTTPException(status_code=422, detail="Source audio is required")
    if required[2] and source_video is None:
        raise HTTPException(status_code=422, detail="Source video is required")
    if operation == "voice_clone" and not script.strip():
        raise HTTPException(status_code=422, detail="A script is required for cloned speech output")
    if operation in {"face_reenactment", "talking_head", "avatar_generation"} and source_audio is None and not script.strip():
        raise HTTPException(status_code=422, detail="A script or source audio is required for avatar speech")

    scoped_project = await _project_scope(session, actor, project_id)
    store = media_object_store()
    stored_keys: dict[str, str] = {}
    checksums: dict[str, str] = {}
    content_types: dict[str, str] = {}
    filenames: dict[str, str] = {}
    try:
        for name, upload, kind in (
            ("image", source_image, "image"),
            ("audio", source_audio, "audio"),
            ("video", source_video, "video"),
        ):
            if upload is None:
                continue
            body, content_type, filename = await _read_upload(upload, kind=kind)
            digest = sha256(body).hexdigest()
            suffix = Path(filename).suffix.lower()[:10]
            key = f"identity-media/{actor.organization_id}/inputs/{idempotency_key}/{name}-{digest[:16]}{suffix}"
            stored = await __import__("asyncio").to_thread(
                store.put_bytes,
                key,
                body,
                content_type,
                metadata={"kind": name, "sha256": digest},
            )
            stored_keys[name] = stored.key
            checksums[name] = stored.sha256
            content_types[name] = content_type
            filenames[name] = filename

        if rights_body is not None and rights_content_type and rights_filename and effective_rights_sha:
            suffix = Path(rights_filename).suffix.lower()[:10]
            rights_key = (
                f"identity-media/{actor.organization_id}/rights/{idempotency_key}/"
                f"evidence-{effective_rights_sha[:16]}{suffix}"
            )
            stored = await __import__("asyncio").to_thread(
                store.put_bytes,
                rights_key,
                rights_body,
                rights_content_type,
                metadata={"kind": "rights-evidence", "sha256": effective_rights_sha},
            )
            stored_keys["rights_evidence"] = stored.key
            checksums["rights_evidence"] = stored.sha256
            content_types["rights_evidence"] = rights_content_type
            filenames["rights_evidence"] = rights_filename

        session.add(
            AuditEvent(
                organization_id=actor.organization_id,
                user_id=actor.id,
                action="identity_media.rights_attested",
                resource_type="identity_media_rights",
                resource_id=idempotency_key,
                details={
                    "operation": operation,
                    "identity_basis": identity_basis,
                    "subject_reference": subject_reference.strip(),
                    "rights_evidence_sha256": effective_rights_sha,
                    "rights_evidence_source": rights_evidence_source,
                    "owner_approval_present": bool(access.allowed and access.owner_approval_required),
                    "commercial_use_requested": bool(commercial_use_requested),
                    "commercial_use_authorized": bool(commercial_use_authorized),
                },
            )
        )

        row = await create_execution(
            session,
            organization_id=actor.organization_id,
            requested_by_id=actor.id,
            project_id=scoped_project,
            idempotency_key=idempotency_key,
            decision=decision,
            input_storage_keys=stored_keys,
            input_checksums=checksums,
            request_payload={
                "script": script.strip(),
                "estimated_duration_seconds": estimated_duration_seconds,
                "input_content_types": content_types,
                "input_filenames": filenames,
                "video_prompt": "Natural talking portrait motion, preserve the supplied identity and scene.",
                "rights_gate": "owner-approval-plus-subject-rights" if identity_basis != "fictional_inspired" else "fictional-direct",
                "rights_evidence_source": rights_evidence_source,
            },
            model=model_for_operation(operation),
            approved_max_cost_usd=approved_max_cost_usd,
        )
        await arm_execution(session, organization_id=actor.organization_id, execution_id=row.id)
        await session.commit()
        return public_execution(row)
    except (IdentityMediaExecutionError, IdentityMediaProviderFailure, MediaStorageError) as exc:
        await session.rollback()
        for key in stored_keys.values():
            await __import__("asyncio").to_thread(store.delete, key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        for key in stored_keys.values():
            await __import__("asyncio").to_thread(store.delete, key)
        raise


@router.get("/executions")
async def list_executions(
    limit: int = Query(default=50, ge=1, le=200),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(
                select(IdentityMediaExecution)
                .where(
                    IdentityMediaExecution.organization_id == actor.organization_id,
                    IdentityMediaExecution.requested_by_id == actor.id,
                )
                .order_by(IdentityMediaExecution.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return {"executions": [public_execution(row) for row in rows]}


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await session.scalar(
        select(IdentityMediaExecution).where(
            IdentityMediaExecution.id == execution_id,
            IdentityMediaExecution.organization_id == actor.organization_id,
            IdentityMediaExecution.requested_by_id == actor.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Identity Media execution not found")
    return public_execution(row)


@router.get("/executions/{execution_id}/download")
async def download_execution(
    execution_id: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = await session.scalar(
        select(IdentityMediaExecution).where(
            IdentityMediaExecution.id == execution_id,
            IdentityMediaExecution.organization_id == actor.organization_id,
            IdentityMediaExecution.requested_by_id == actor.id,
        )
    )
    if row is None or row.status != "completed" or not row.output_storage_key:
        raise HTTPException(status_code=404, detail="Identity Media output is not ready")
    store = media_object_store()
    media_type = str(row.output_media_type or "application/octet-stream")
    suffix = ".mp3" if media_type == "audio/mpeg" else ".wav" if "wav" in media_type else ".mp4"
    filename = f"aionex-{row.operation}-{row.id}{suffix}"
    signed = store.presigned_get(
        row.output_storage_key,
        filename=filename,
        content_type=media_type,
        expires_seconds=300,
        inline=False,
    )
    if signed:
        return RedirectResponse(signed, status_code=307)
    try:
        body = await __import__("asyncio").to_thread(
            store.get_bytes,
            row.output_storage_key,
            max_bytes=int(settings.IDENTITY_MEDIA_MAX_PROVIDER_BYTES),
        )
    except MediaStorageError as exc:
        raise HTTPException(status_code=404, detail="Identity Media output is unavailable") from exc
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
