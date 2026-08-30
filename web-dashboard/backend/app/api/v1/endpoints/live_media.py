"""Governed user-facing activation surface for Phase 36 live media runtimes.

This module deliberately reuses the durable Phase 36 execution authorities.  It
never performs provider generation in the request process, never returns provider
credentials or raw Open Song endpoint identifiers, and requires an explicit user
cost/rights approval before an execution can become claimable.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.audio_factory import AudioRequest, AudioSegment, build_audio_plan
from aios.design_factory import DesignRequest, ProviderRuntimeEvidence
from aios.music_factory import MusicRequest, MusicRightsEvidence, build_music_plan
from aios.open_song_factory import (
    OpenSongRequest,
    OpenSongRightsEvidence,
    OpenSongRuntimeBinding,
    build_open_song_plan,
)
from aios.stable_audio_factory import (
    StableAudioRequest,
    StableAudioRightsEvidence,
    build_stable_audio_plan,
)
from aios.video_factory import VideoRequest, VideoRuntimeEvidence

from app.core.auth import UserRecord
from app.core.config import settings
from app.core.owner_policy import require_owner_service_allowed
from app.db.base import get_db
from app.db.models import (
    AIProvider,
    AuditEvent,
    AudioDubbingExecution,
    AudioMusicExecution,
    AudioSongExecution,
    AudioSpeechExecution,
    AudioTranscriptExecution,
    DesignImageExecution,
    VideoExecution,
    MediaAssetNode,
    Project,
    Workspace,
    uuid_str,
)
from app.services.ai_runtime_service import (
    ensure_environment_providers,
    provider_enabled,
)
from app.services.audio_dubbing_pipeline import (
    create_audio_dubbing_pipeline,
    load_private_transcript_document,
)
from app.services.audio_dubbing_runtime import (
    arm_audio_dubbing_execution,
    audio_dubbing_execution_snapshot,
)
from app.services.audio_music_pipeline import create_lyria_music_pipeline
from app.services.audio_music_runtime import (
    arm_audio_music_execution,
    audio_music_execution_snapshot,
)
from app.services.audio_open_song_pipeline import create_open_song_pipeline
from app.services.audio_song_runtime import audio_song_execution_snapshot
from app.services.audio_speech_pipeline import create_stock_speech_pipeline
from app.services.audio_speech_runtime import (
    arm_audio_speech_execution,
    audio_speech_execution_snapshot,
)
from app.services.audio_stable_music_pipeline import create_stable_audio_music_pipeline
from app.services.audio_transcript_pipeline import create_audio_transcript_pipeline
from app.services.audio_transcript_runtime import (
    arm_audio_transcript_execution,
    audio_transcript_execution_snapshot,
)
from app.services.design_image_pipeline import create_routed_design_image_pipeline
from app.services.design_image_runtime import arm_design_image_execution
from app.services.free_tier import require_non_free_user
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import media_object_store
from app.services.provider_model_evidence import probe_provider_model_inventory
from app.services.video_pipeline import create_routed_video_pipeline
from app.services.video_project_runtime import arm_video_project, video_project_snapshot

router = APIRouter()

_REPO_ROOT = Path(os.environ.get("AIOS_REPO_ROOT", "/workspace"))
_OPEN_SONG_EVIDENCE_ROOT = _REPO_ROOT / ".deployment-backups/phase36g-open-song-main-components-live/20260827T165247Z"
_OPEN_SONG_BINDING = _OPEN_SONG_EVIDENCE_ROOT / "runpod-private-binding-acceptance.json"
_OPEN_SONG_ACCEPTANCE = _OPEN_SONG_EVIDENCE_ROOT / "real-open-song-acceptance-v8.json"
_OPEN_SONG_SECONDARY_EVIDENCE_ROOT = Path(
    os.environ.get(
        "AUDIO_SONG_SECONDARY_EVIDENCE_ROOT",
        str(_REPO_ROOT / ".deployment-backups/phase36g-open-song-secondary-live/current"),
    )
)
_OPEN_SONG_SECONDARY_BINDING = _OPEN_SONG_SECONDARY_EVIDENCE_ROOT / "runpod-private-binding-acceptance.json"
_OPEN_SONG_SECONDARY_ACCEPTANCE = _OPEN_SONG_SECONDARY_EVIDENCE_ROOT / "real-open-song-acceptance.json"
_OPEN_SONG_ACTIVE_STATUSES = ("planned", "queued", "running", "rendering")
_RECEIPTS = {
    "image": "docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md",
    "video": "docs/phase-36/receipts/36F-2026-08-19-video-factory.md",
    "audio": "docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md",
    "music": "docs/phase-36/receipts/36G-2026-08-26-funded-music-provider-activation.md",
    "stable_music": "docs/phase-36/receipts/36G-2026-08-26-funded-music-provider-activation.md",
}
_SHA = frozenset("0123456789abcdef")


def _sha256_file(relative: str) -> str:
    path = (_REPO_ROOT / relative).resolve()
    root = _REPO_ROOT.resolve()
    if root not in path.parents or not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=503, detail="Runtime acceptance evidence is unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_ok(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in _SHA for ch in text):
        raise HTTPException(status_code=503, detail="Runtime acceptance evidence is invalid")
    return text


def _load_json_evidence(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Runtime acceptance evidence is unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="Runtime acceptance evidence is invalid")
    return data


async def _scope(
    session: AsyncSession,
    actor: UserRecord,
    *,
    project_id: str | None,
    workspace_id: str | None,
) -> MediaGraphScope:
    project = None
    if project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        workspace_id = project.workspace_id
    if workspace_id:
        workspace = await session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == actor.organization_id,
                Workspace.status == "active",
            )
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return MediaGraphScope(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        workspace_id=workspace_id,
        project_id=project_id,
    )


async def _provider_inventory(
    session: AsyncSession,
    actor: UserRecord,
    provider_type: str,
) -> tuple[AIProvider, tuple[str, ...], str]:
    await require_owner_service_allowed(session, provider_type)
    await ensure_environment_providers(session, actor.organization_id)
    rows = list(
        (
            await session.scalars(
                select(AIProvider)
                .where(
                    AIProvider.organization_id == actor.organization_id,
                    AIProvider.type == provider_type,
                )
                .order_by(AIProvider.id)
            )
        ).all()
    )
    enabled = [row for row in rows if provider_enabled(row)]
    if len(enabled) != 1:
        raise HTTPException(status_code=503, detail=f"{provider_type} provider authority is unavailable")
    try:
        evidence = await probe_provider_model_inventory(enabled[0])
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{provider_type} live model inventory is unavailable") from exc
    return enabled[0], evidence.model_ids, evidence.evidence_ref


def _evidence_digest(evidence_ref: str) -> str:
    return hashlib.sha256(evidence_ref.encode("utf-8")).hexdigest()


async def _audit(session: AsyncSession, actor: UserRecord, action: str, resource_type: str, resource_id: str, details: dict[str, Any]) -> None:
    session.add(
        AuditEvent(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={**details, "credential_returned": False},
        )
    )


class LiveScope(BaseModel):
    project_id: str | None = None
    workspace_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)


class ImageLiveRequest(LiveScope):
    title: str = Field(min_length=2, max_length=160)
    brief: str = Field(min_length=8, max_length=6000)
    use_case: Literal["logo", "brand-system", "poster", "advertisement", "product-mockup", "infographic", "diagram", "experimental-graphic", "social-post"] = "social-post"
    preset_id: str = "social-square"
    operation: Literal["generate", "edit", "variation", "inpaint"] = "generate"
    style: str = Field(default="modern", min_length=2, max_length=120)
    language: str = Field(default="en-US", min_length=2, max_length=35)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    reference_node_ids: list[str] = Field(default_factory=list, max_length=14)
    mask_node_id: str | None = None
    approved_max_cost_usd: float = Field(gt=0, le=1.0)


class VideoLiveRequest(LiveScope):
    title: str = Field(min_length=2, max_length=160)
    brief: str = Field(min_length=8, max_length=6000)
    operation: Literal["text-to-video", "image-to-video", "logo-to-video", "reference-to-video", "remix"] = "text-to-video"
    use_case: Literal["advertisement", "explainer", "product", "social", "cinematic", "logo-animation"] = "advertisement"
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    resolution: Literal["720p"] = "720p"
    language: str = Field(default="en-US", min_length=2, max_length=35)
    style: str = Field(default="cinematic", min_length=2, max_length=120)
    reference_node_id: str | None = None
    approved_max_total_cost_usd: float = Field(gt=0, le=50.0)


class SpeechLiveRequest(LiveScope):
    title: str = Field(min_length=2, max_length=160)
    text: str = Field(min_length=1, max_length=4096)
    language: str = Field(default="en-US", min_length=2, max_length=35)
    voice: Literal["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"] = "marin"
    instructions: str = Field(default="", max_length=4096)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    approved_max_cost_usd: float = Field(default=0.05, gt=0, le=0.05)


class TranscriptLiveRequest(LiveScope):
    source_node_id: str
    language: str = Field(default="en", min_length=2, max_length=32)
    operation: Literal["transcribe", "diarize"] = "transcribe"
    source_duration_ms: int = Field(gt=0, le=600_000)
    source_sample_rate_hz: int = Field(ge=8_000, le=192_000)
    source_channels: int = Field(ge=1, le=2)
    approved_max_cost_usd: float = Field(gt=0, le=1.0)


class DubbingLiveRequest(LiveScope):
    source_transcript_node_id: str
    target_language: str = Field(min_length=2, max_length=32)
    voice_bindings: dict[str, str] = Field(min_length=1, max_length=32)
    output_profile_id: str = "wav-pcm-48k-stereo"
    max_translation_cost_usd: float = Field(gt=0, le=2.0)
    per_segment_speech_cap_usd: float = Field(gt=0, le=0.10)
    approved_max_total_cost_usd: float = Field(gt=0, le=5.0)


class MusicLiveRequest(LiveScope):
    title: str = Field(min_length=2, max_length=160)
    prompt: str = Field(min_length=8, max_length=3000)
    language: str = Field(default="en", min_length=2, max_length=32)
    provider: Literal["replicate", "stability"] = "replicate"
    tier: Literal["draft", "final"] = "draft"
    instrumental_only: bool = True
    lyrics: str = Field(default="", max_length=6000)
    rights_basis: Literal["instrumental", "original-user-owned", "licensed", "public-domain"] = "instrumental"
    rights_evidence_sha256: str | None = None
    commercial_use_authorized: bool
    provider_terms_accepted: bool
    ai_generated_disclosure_accepted: bool
    final_generation_approved: bool = False
    final_approval_evidence_sha256: str | None = None
    prior_draft_checksum: str | None = None
    approved_max_cost_usd: float = Field(gt=0, le=0.20)


class SongLiveRequest(LiveScope):
    title: str = Field(min_length=3, max_length=160)
    concept: str = Field(min_length=20, max_length=1000)
    lyrics: str = Field(min_length=40, max_length=8000)
    language: str = Field(default="en", min_length=2, max_length=32)
    duration_seconds: int = Field(ge=30, le=180)
    bpm: int = Field(ge=40, le=240)
    musical_key: str = Field(min_length=1, max_length=16)
    rights_basis: Literal["original", "licensed", "public-domain"]
    rights_evidence_sha256: str | None = None
    commercial_use_authorized: bool
    provider_terms_accepted: bool
    ai_generated_disclosure_accepted: bool
    approved_max_cost_usd: float = Field(gt=0, le=0.20)
    monthly_user_cap_usd: float = Field(gt=0, le=5.0)


@router.get("/jobs")
async def list_live_media_jobs(
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    organization_id = actor.organization_id
    rows: list[dict[str, Any]] = []

    async def recent(model, *, kind: str, limit: int = 25):
        return list(
            (
                await session.scalars(
                    select(model)
                    .where(model.organization_id == organization_id)
                    .order_by(model.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    for row in await recent(DesignImageExecution, kind="image"):
        rows.append({
            "kind": "image", "id": row.id, "graph_id": row.graph_id,
            "status": row.status, "provider": row.provider, "model": row.model,
            "attempts": row.attempts, "max_attempts": row.max_attempts,
            "actual_cost_usd": row.actual_cost_usd, "created_at": row.created_at.isoformat(),
            "error_code": row.error_code,
        })
    for row in await recent(VideoExecution, kind="video"):
        rows.append({
            "kind": "video", "id": row.id, "graph_id": row.graph_id, "scene_key": row.scene_key,
            "status": row.status, "provider": row.provider, "model": row.model,
            "attempts": row.attempts, "max_attempts": row.max_attempts,
            "actual_cost_usd": row.actual_cost_usd, "created_at": row.created_at.isoformat(),
            "error_code": row.error_code,
        })
    for model, kind in (
        (AudioSpeechExecution, "speech"),
        (AudioTranscriptExecution, "transcript"),
        (AudioDubbingExecution, "dubbing"),
        (AudioMusicExecution, "music"),
        (AudioSongExecution, "song"),
    ):
        for row in await recent(model, kind=kind):
            rows.append({
                "kind": kind, "id": row.id,
                "graph_id": getattr(row, "graph_id", None) or getattr(row, "final_graph_id", None),
                "status": row.status, "provider": getattr(row, "provider", None),
                "model": getattr(row, "model", None),
                "attempts": int(getattr(row, "attempts", 0) or 0),
                "max_attempts": int(getattr(row, "max_attempts", 1) or 1),
                "actual_cost_usd": getattr(row, "actual_cost_usd", None)
                    if hasattr(row, "actual_cost_usd")
                    else getattr(row, "actual_total_cost_usd", None),
                "created_at": row.created_at.isoformat(),
                "error_code": getattr(row, "error_code", None),
            })

    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return {"jobs": rows[:100], "credential_returned": False, "raw_provider_job_id_returned": False}


@router.get("/capabilities")
async def live_media_capabilities(
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    models: dict[str, bool] = {}
    for provider_type, wanted in (
        ("openai", ("gpt-image-2", "sora-2", "gpt-4o-mini-tts-2025-12-15", "gpt-4o-mini-transcribe-2025-12-15", "gpt-4o-transcribe-diarize", "gpt-5.6-luna")),
    ):
        try:
            _, inventory, _ = await _provider_inventory(session, actor, provider_type)
            models.update({name: name in inventory for name in wanted})
        except HTTPException:
            models.update({name: False for name in wanted})
    return {
        "schema": "36.live-media-capabilities.v1",
        "image": {"ready": bool(models.get("gpt-image-2")), "worker_live": settings.DESIGN_IMAGE_LIVE_ENABLED},
        "video": {"ready": bool(models.get("sora-2")), "worker_live": settings.VIDEO_EXECUTION_LIVE_ENABLED},
        "speech": {"ready": bool(models.get("gpt-4o-mini-tts-2025-12-15")), "worker_live": settings.AUDIO_SPEECH_LIVE_ENABLED},
        "transcript": {"ready": bool(models.get("gpt-4o-mini-transcribe-2025-12-15") and models.get("gpt-4o-transcribe-diarize")), "worker_live": settings.AUDIO_TRANSCRIPT_LIVE_ENABLED},
        "dubbing": {"ready": bool(models.get("gpt-5.6-luna") and models.get("gpt-4o-mini-tts-2025-12-15")), "worker_live": settings.AUDIO_DUBBING_LIVE_ENABLED},
        "music": {"ready": True, "worker_live": settings.AUDIO_MUSIC_LIVE_ENABLED, "requires_provider_preflight": True},
        "open_song": {"ready": _OPEN_SONG_BINDING.is_file() and _OPEN_SONG_ACCEPTANCE.is_file(), "worker_live": settings.AUDIO_SONG_LIVE_ENABLED, "secondary_account_used": False},
        "credentials_returned": False,
    }


@router.post("/image", status_code=202)
async def create_live_image(
    data: ImageLiveRequest,
    actor: UserRecord = Depends(require_non_free_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, inventory, evidence_ref = await _provider_inventory(session, actor, "openai")
    if "gpt-image-2" not in inventory:
        raise HTTPException(status_code=503, detail="GPT Image 2 is unavailable in the current provider inventory")
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    request = DesignRequest(
        title=data.title,
        brief=data.brief,
        use_case=data.use_case,
        preset_id=data.preset_id,
        operation=data.operation,
        style=data.style,
        language=data.language,
        reference_count=len(data.reference_node_ids),
    )
    runtime = ProviderRuntimeEvidence(
        provider="openai",
        model="gpt-image-2",
        state="ready",
        proven_operations=frozenset({"generate", "edit", "variation", "inpaint"}),
        verified_output_formats=frozenset({"png", "jpeg", "webp"}),
        reason=f"current-model-inventory:{_evidence_digest(evidence_ref)[:16]}+phase36e-acceptance:{_sha256_file(_RECEIPTS['image'])[:16]}",
    )
    try:
        pipeline = await create_routed_design_image_pipeline(
            session,
            scope=scope,
            request=request,
            runtime_evidence=(runtime,),
            provider_output_format=data.output_format,
            idempotency_key=data.idempotency_key,
            reference_node_ids=tuple(data.reference_node_ids),
            mask_node_id=data.mask_node_id,
            estimated_cost_usd=data.approved_max_cost_usd,
        )
        row = await session.get(DesignImageExecution, pipeline.execution_id)
        if row is None:
            raise RuntimeError("image execution disappeared")
        row.max_attempts = 1
        row.request_options = {**(row.request_options or {}), "approved_max_cost_usd": data.approved_max_cost_usd, "approval_mode": "explicit-user-cap"}
        await arm_design_image_execution(session, execution_id=row.id, organization_id=actor.organization_id)
        await _audit(session, actor, "studio.live_media.image.armed", "design_image_execution", row.id, {"graph_id": pipeline.graph_id, "provider": row.provider, "model": row.model, "approved_max_cost_usd": data.approved_max_cost_usd})
        await session.commit()
        return {"kind": "image", "execution_id": row.id, "graph_id": pipeline.graph_id, "status": row.status, "provider": row.provider, "model": row.model, "approved_max_cost_usd": data.approved_max_cost_usd, "automatic_retry": False}
    except HTTPException:
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/image/{execution_id}")
async def get_live_image(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await session.scalar(select(DesignImageExecution).where(DesignImageExecution.id == execution_id, DesignImageExecution.organization_id == actor.organization_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Image execution not found")
    return {"kind": "image", "execution_id": row.id, "graph_id": row.graph_id, "status": row.status, "provider": row.provider, "model": row.model, "attempts": row.attempts, "max_attempts": row.max_attempts, "estimated_cost_usd": row.estimated_cost_usd, "actual_cost_usd": row.actual_cost_usd, "cost_basis": row.cost_basis, "error_code": row.error_code}


@router.post("/video", status_code=202)
async def create_live_video(data: VideoLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    _, inventory, evidence_ref = await _provider_inventory(session, actor, "openai")
    if "sora-2" not in inventory:
        raise HTTPException(status_code=503, detail="Sora 2 is unavailable in the current provider inventory")
    reference_count = 0 if data.operation == "text-to-video" else 1
    if reference_count and not data.reference_node_id:
        raise HTTPException(status_code=422, detail="This video operation requires one governed reference node")
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    request = VideoRequest(title=data.title, brief=data.brief, operation=data.operation, use_case=data.use_case, aspect_ratio=data.aspect_ratio, resolution=data.resolution, language=data.language, style=data.style, reference_count=reference_count)
    runtime = VideoRuntimeEvidence(provider="openai", model="sora-2", state="ready", proven_operations=frozenset({"text-to-video", "image-to-video", "logo-to-video", "reference-to-video", "remix"}), reason=f"current-model-inventory:{_evidence_digest(evidence_ref)[:16]}+phase36f-acceptance:{_sha256_file(_RECEIPTS['video'])[:16]}")
    try:
        pipeline = await create_routed_video_pipeline(session, scope=scope, request=request, runtime_evidence=(runtime,), idempotency_key=data.idempotency_key, reference_node_id=data.reference_node_id)
        armed = await arm_video_project(session, organization_id=actor.organization_id, graph_id=pipeline.graph_id, max_total_cost_usd=data.approved_max_total_cost_usd)
        await _audit(session, actor, "studio.live_media.video.armed", "media_asset_graph", pipeline.graph_id, {"provider": pipeline.provider, "model": pipeline.model, "projected_cost_usd": armed.projected_cost_usd, "approved_max_total_cost_usd": data.approved_max_total_cost_usd})
        await session.commit()
        return {"kind": "video", "graph_id": pipeline.graph_id, "status": "rendering", "provider": pipeline.provider, "model": pipeline.model, "execution_ids": list(pipeline.execution_ids), "projected_cost_usd": armed.projected_cost_usd, "approved_max_total_cost_usd": data.approved_max_total_cost_usd, "automatic_retry": False}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/video/{graph_id}")
async def get_live_video(graph_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        snapshot = await video_project_snapshot(session, organization_id=actor.organization_id, graph_id=graph_id)
        return {"kind": "video", **asdict(snapshot)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/speech", status_code=202)
async def create_live_speech(data: SpeechLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    _, inventory, evidence_ref = await _provider_inventory(session, actor, "openai")
    model = "gpt-4o-mini-tts-2025-12-15"
    if model not in inventory:
        raise HTTPException(status_code=503, detail="Pinned stock speech model is unavailable")
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    request = AudioRequest(title=data.title, brief=data.text, operation="speech", language=data.language, script=data.text, speaker_count=1, voice_mode="stock", source_count=0, segments=(AudioSegment(segment_id="speech-1", role="narration", text=data.text, language=data.language),))
    try:
        plan = build_audio_plan(request)
        pipeline = await create_stock_speech_pipeline(
            session,
            scope=scope,
            plan=plan,
            provider="openai",
            model=model,
            voice=data.voice,
            instructions=data.instructions,
            speed=data.speed,
            max_duration_seconds=min(300.0, max(20.0, len(data.text) / 12.0)),
            estimated_cost_usd=data.approved_max_cost_usd,
            max_cost_usd=data.approved_max_cost_usd,
            idempotency_key=data.idempotency_key,
            max_attempts=1,
        )
        row = await arm_audio_speech_execution(session, execution_id=pipeline.speech_execution_id, organization_id=actor.organization_id, approved_max_cost_usd=data.approved_max_cost_usd)
        await _audit(session, actor, "studio.live_media.speech.armed", "audio_speech_execution", row.id, {"provider": row.provider, "model": row.model, "approved_max_cost_usd": data.approved_max_cost_usd})
        await session.commit()
        return {"kind": "speech", **(await audio_speech_execution_snapshot(session, organization_id=actor.organization_id, execution_id=row.id))}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/transcript", status_code=202)
async def create_live_transcript(data: TranscriptLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    _, inventory, _ = await _provider_inventory(session, actor, "openai")
    model = "gpt-4o-mini-transcribe-2025-12-15" if data.operation == "transcribe" else "gpt-4o-transcribe-diarize"
    if model not in inventory:
        raise HTTPException(status_code=503, detail="Pinned transcript model is unavailable")
    node = await session.scalar(select(MediaAssetNode).where(MediaAssetNode.id == data.source_node_id, MediaAssetNode.organization_id == actor.organization_id))
    if node is None or node.status != "completed" or not node.storage_key or not node.checksum or not node.size_bytes or node.media_type not in {"audio/wav", "audio/x-wav"}:
        raise HTTPException(status_code=409, detail="Governed WAV source node is unavailable")
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    try:
        pipeline = await create_audio_transcript_pipeline(session, scope=scope, source_node_id=node.id, language=data.language, operation=data.operation, idempotency_key=data.idempotency_key, max_cost_usd=data.approved_max_cost_usd, source_duration_ms=data.source_duration_ms, source_sample_rate_hz=data.source_sample_rate_hz, source_channels=data.source_channels)
        row = await arm_audio_transcript_execution(session, execution_id=pipeline.execution_id, organization_id=actor.organization_id, approved_max_cost_usd=data.approved_max_cost_usd)
        await _audit(session, actor, "studio.live_media.transcript.armed", "audio_transcript_execution", row.id, {"model": row.model, "operation": data.operation, "approved_max_cost_usd": data.approved_max_cost_usd})
        await session.commit()
        return {"kind": "transcript", **(await audio_transcript_execution_snapshot(session, organization_id=actor.organization_id, execution_id=row.id))}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/dubbing", status_code=202)
async def create_live_dubbing(data: DubbingLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    _, inventory, evidence_ref = await _provider_inventory(session, actor, "openai")
    if not {"gpt-5.6-luna", "gpt-4o-mini-tts-2025-12-15"}.issubset(set(inventory)):
        raise HTTPException(status_code=503, detail="Pinned dubbing models are unavailable")
    source = await session.scalar(select(MediaAssetNode).where(MediaAssetNode.id == data.source_transcript_node_id, MediaAssetNode.organization_id == actor.organization_id))
    if source is None or not source.storage_key or not source.checksum or not source.size_bytes:
        raise HTTPException(status_code=409, detail="Governed transcript source is unavailable")
    try:
        document = load_private_transcript_document(store=media_object_store(), storage_key=str(source.storage_key), object_checksum=str(source.checksum), object_size_bytes=int(source.size_bytes))
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Private transcript document could not be verified") from exc
    proof = _evidence_digest(evidence_ref)
    bindings = {speaker: {"voice": voice, "runtime_evidence_sha256": proof} for speaker, voice in data.voice_bindings.items()}
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    try:
        pipeline = await create_audio_dubbing_pipeline(session, scope=scope, source_transcript_node_id=source.id, document=document, target_language=data.target_language, voice_bindings=bindings, output_profile_id=data.output_profile_id, idempotency_key=data.idempotency_key, max_translation_cost_usd=data.max_translation_cost_usd, per_segment_speech_cap_usd=data.per_segment_speech_cap_usd, max_total_cost_usd=data.approved_max_total_cost_usd)
        row = await arm_audio_dubbing_execution(session, execution_id=pipeline.execution_id, organization_id=actor.organization_id, approved_max_total_cost_usd=data.approved_max_total_cost_usd)
        await _audit(session, actor, "studio.live_media.dubbing.armed", "audio_dubbing_execution", row.id, {"target_language": data.target_language, "approved_max_total_cost_usd": data.approved_max_total_cost_usd, "voice_mode": "stock"})
        await session.commit()
        return {"kind": "dubbing", **(await audio_dubbing_execution_snapshot(session, organization_id=actor.organization_id, execution_id=row.id))}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _replicate_preflight() -> str:
    credential = str(settings.REPLICATE_API_TOKEN or "").strip()
    if not credential:
        raise HTTPException(status_code=503, detail="Replicate is not configured")
    headers = {"Authorization": f"Bearer {credential}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            account = await client.get("https://api.replicate.com/v1/account", headers=headers)
            model = await client.get("https://api.replicate.com/v1/models/google/lyria-3", headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail="Replicate preflight failed") from exc
    if account.status_code != 200 or model.status_code != 200:
        raise HTTPException(status_code=503, detail="Replicate account/model preflight failed")
    return hashlib.sha256(f"replicate:{account.status_code}:{model.status_code}".encode()).hexdigest()


async def _stability_preflight() -> str:
    credential = str(settings.STABILITY_API_KEY or "").strip()
    if not credential:
        raise HTTPException(status_code=503, detail="Stability is not configured")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.get("https://api.stability.ai/v1/user/balance", headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"})
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail="Stability balance preflight failed") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Stability balance preflight failed")
    try:
        raw_credits = (response.json() or {}).get("credits")
        credits = float(raw_credits) if raw_credits is not None else 0.0
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail="Stability balance evidence is invalid")
    if credits <= 0:
        raise HTTPException(status_code=402, detail="Stability account has no available credits")
    return hashlib.sha256(f"stability-balance-positive:{round(credits,6)}".encode()).hexdigest()


@router.post("/music", status_code=202)
async def create_live_music(data: MusicLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    try:
        if data.provider == "replicate":
            provider_proof = await _replicate_preflight()
            music_rights = MusicRightsEvidence(basis=data.rights_basis, evidence_sha256=data.rights_evidence_sha256, commercial_use_authorized=data.commercial_use_authorized, user_accepts_provider_terms=data.provider_terms_accepted, synthid_disclosure_required=True)
            music_request = MusicRequest(title=data.title, prompt=data.prompt, language=data.language, rights=music_rights, tier=data.tier, instrumental_only=data.instrumental_only, lyrics=data.lyrics, final_generation_approved=data.final_generation_approved, final_approval_evidence_sha256=data.final_approval_evidence_sha256, prior_draft_checksum=data.prior_draft_checksum)
            music_plan = build_music_plan(music_request)
            music_pipeline = await create_lyria_music_pipeline(session, scope=scope, plan=music_plan, idempotency_key=data.idempotency_key, runtime_evidence_sha256=provider_proof, pricing_evidence_sha256=_sha256_file(_RECEIPTS["music"]))
            fixed_cost_usd = music_pipeline.fixed_cost_usd
            execution_id = music_pipeline.music_execution_id
        else:
            if data.tier != "draft" or not data.instrumental_only or data.lyrics.strip():
                raise HTTPException(status_code=422, detail="Stable Audio launch route is instrumental draft only")
            provider_proof = await _stability_preflight()
            stable_rights = StableAudioRightsEvidence(commercial_use_authorized=data.commercial_use_authorized, user_accepts_provider_terms=data.provider_terms_accepted, ai_generated_disclosure_required=data.ai_generated_disclosure_accepted)
            stable_plan = build_stable_audio_plan(StableAudioRequest(title=data.title, prompt=data.prompt, language=data.language, rights=stable_rights))
            stable_pipeline = await create_stable_audio_music_pipeline(session, scope=scope, plan=stable_plan, idempotency_key=data.idempotency_key, runtime_evidence_sha256=provider_proof, pricing_evidence_sha256=_sha256_file(_RECEIPTS["stable_music"]))
            fixed_cost_usd = stable_pipeline.fixed_cost_usd
            execution_id = stable_pipeline.music_execution_id
        if abs(float(fixed_cost_usd) - float(data.approved_max_cost_usd)) > 1e-9:
            raise HTTPException(status_code=409, detail="Approved music cost must exactly match the fixed provider price")
        row = await arm_audio_music_execution(session, execution_id=execution_id, organization_id=actor.organization_id, approved_max_cost_usd=data.approved_max_cost_usd)
        await _audit(session, actor, "studio.live_media.music.armed", "audio_music_execution", row.id, {"provider": row.provider, "model": row.model, "tier": row.tier, "approved_max_cost_usd": data.approved_max_cost_usd})
        await session.commit()
        return {"kind": "music", **(await audio_music_execution_snapshot(session, organization_id=actor.organization_id, execution_id=row.id))}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _open_song_binding_from_evidence(
    binding_path: Path,
    acceptance_path: Path,
) -> tuple[OpenSongRuntimeBinding, dict[str, str]]:
    binding = _load_json_evidence(binding_path)
    accepted = _load_json_evidence(acceptance_path)
    endpoint = str(binding.get("endpoint_id") or "").strip()
    digest = str(binding.get("image_digest") or "").strip().lower()
    repository = str(binding.get("image_repository") or "").strip().lower()
    if not endpoint or not digest.startswith("sha256:") or not repository:
        raise HTTPException(status_code=503, detail="Open Song runtime binding is incomplete")
    runtime = OpenSongRuntimeBinding(
        route_id="runpod-flex-a40",
        endpoint_id_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
        container_image_repository=repository,
        container_image_index_digest=digest,
        container_image_digest=digest,
        image_sbom_sha256=_hash_ok(binding.get("image_sbom_sha256")),
        handler_source_sha256=_hash_ok(binding.get("handler_source_sha256")),
    )
    if accepted.get("status") != "pass" or int((accepted.get("provider") or {}).get("attempts") or 0) != 1:
        raise HTTPException(status_code=503, detail="Open Song retained live acceptance is not valid")
    return runtime, {
        "runtime": _hash_ok(accepted.get("runtime_evidence_sha256")),
        "pricing": _hash_ok(accepted.get("pricing_evidence_sha256")),
        "license": _hash_ok(accepted.get("license_evidence_sha256")),
    }


def _open_song_binding_and_evidence() -> tuple[OpenSongRuntimeBinding, dict[str, str]]:
    return _open_song_binding_from_evidence(_OPEN_SONG_BINDING, _OPEN_SONG_ACCEPTANCE)


def _secondary_open_song_binding_and_evidence() -> tuple[OpenSongRuntimeBinding, dict[str, str]] | None:
    binding_exists = _OPEN_SONG_SECONDARY_BINDING.is_file()
    acceptance_exists = _OPEN_SONG_SECONDARY_ACCEPTANCE.is_file()
    if not binding_exists and not acceptance_exists:
        return None
    if binding_exists != acceptance_exists:
        raise HTTPException(status_code=503, detail="Secondary Open Song runtime evidence is incomplete")
    return _open_song_binding_from_evidence(
        _OPEN_SONG_SECONDARY_BINDING,
        _OPEN_SONG_SECONDARY_ACCEPTANCE,
    )


async def _select_open_song_binding_and_evidence(
    session: AsyncSession,
    *,
    routing_key: str,
) -> tuple[OpenSongRuntimeBinding, dict[str, str]]:
    candidates = [_open_song_binding_and_evidence()]
    secondary = _secondary_open_song_binding_and_evidence()
    if secondary is not None:
        if secondary[0].endpoint_id_sha256 == candidates[0][0].endpoint_id_sha256:
            raise HTTPException(status_code=503, detail="Open Song account pool contains a duplicate endpoint")
        candidates.append(secondary)
    if len(candidates) == 1:
        return candidates[0]

    endpoint_hashes = [item[0].endpoint_id_sha256 for item in candidates]
    counts = {endpoint_hash: 0 for endpoint_hash in endpoint_hashes}
    rows = (
        await session.execute(
            select(
                AudioSongExecution.endpoint_id_sha256,
                func.count(AudioSongExecution.id),
            )
            .where(
                AudioSongExecution.endpoint_id_sha256.in_(endpoint_hashes),
                AudioSongExecution.status.in_(_OPEN_SONG_ACTIVE_STATUSES),
            )
            .group_by(AudioSongExecution.endpoint_id_sha256)
        )
    ).all()
    for endpoint_hash, active_count in rows:
        if endpoint_hash in counts:
            counts[endpoint_hash] = int(active_count or 0)

    def rank(item: tuple[OpenSongRuntimeBinding, dict[str, str]]) -> tuple[int, str]:
        endpoint_hash = item[0].endpoint_id_sha256
        tie_break = hashlib.sha256(f"{routing_key}:{endpoint_hash}".encode()).hexdigest()
        return counts[endpoint_hash], tie_break

    return min(candidates, key=rank)


@router.post("/song", status_code=202)
async def create_live_song(data: SongLiveRequest, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if not (data.commercial_use_authorized and data.provider_terms_accepted and data.ai_generated_disclosure_accepted):
        raise HTTPException(status_code=422, detail="Commercial use, provider terms, and AI disclosure acceptance are required")
    binding, evidence = await _select_open_song_binding_and_evidence(
        session, routing_key=data.idempotency_key
    )
    scope = await _scope(session, actor, project_id=data.project_id, workspace_id=data.workspace_id)
    rights = OpenSongRightsEvidence(basis=data.rights_basis, commercial_use_authorized=True, provider_terms_accepted=True, ai_generated_disclosure_accepted=True, evidence_sha256=data.rights_evidence_sha256)
    try:
        plan = build_open_song_plan(OpenSongRequest(title=data.title, concept=data.concept, lyrics=data.lyrics, language=data.language, duration_seconds=data.duration_seconds, bpm=data.bpm, musical_key=data.musical_key, rights=rights))
        if abs(float(plan.route.max_cost_usd) - float(data.approved_max_cost_usd)) > 1e-9:
            raise HTTPException(status_code=409, detail="Approved Open Song cost must exactly match the governed route cap")
        pipeline = await create_open_song_pipeline(session, scope=scope, plan=plan, idempotency_key=data.idempotency_key, runtime_evidence_sha256=evidence["runtime"], pricing_evidence_sha256=evidence["pricing"], license_evidence_sha256=evidence["license"], runtime_binding=binding)
        row = await session.get(AudioSongExecution, pipeline.execution_id)
        if row is None:
            raise RuntimeError("Open Song execution disappeared")
        row.provider_metadata = {**(row.provider_metadata or {}), "user_cost_approved": True, "approved_max_cost_usd": data.approved_max_cost_usd, "monthly_user_cap_usd": data.monthly_user_cap_usd, "balance_check_delegated_to_secret_worker": True}
        await _audit(session, actor, "studio.live_media.song.approved", "audio_song_execution", row.id, {"provider": "runpod", "route_id": row.route_id, "approved_max_cost_usd": data.approved_max_cost_usd, "monthly_user_cap_usd": data.monthly_user_cap_usd, "endpoint_id_returned": False})
        await session.commit()
        snapshot = await audio_song_execution_snapshot(session, organization_id=actor.organization_id, execution_id=row.id)
        return {"kind": "open_song", **snapshot, "arming_state": "awaiting-secret-worker-balance-check", "endpoint_id_returned": False, "automatic_retry": False}
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/music/{execution_id}")
async def get_live_music(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"kind": "music", **(await audio_music_execution_snapshot(session, organization_id=actor.organization_id, execution_id=execution_id))}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/song/{execution_id}")
async def get_live_song(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"kind": "open_song", **(await audio_song_execution_snapshot(session, organization_id=actor.organization_id, execution_id=execution_id)), "endpoint_id_returned": False}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/speech/{execution_id}")
async def get_live_speech(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"kind": "speech", **(await audio_speech_execution_snapshot(session, organization_id=actor.organization_id, execution_id=execution_id))}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/transcript/{execution_id}")
async def get_live_transcript(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"kind": "transcript", **(await audio_transcript_execution_snapshot(session, organization_id=actor.organization_id, execution_id=execution_id))}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dubbing/{execution_id}")
async def get_live_dubbing(execution_id: str, actor: UserRecord = Depends(require_non_free_user), session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return {"kind": "dubbing", **(await audio_dubbing_execution_snapshot(session, organization_id=actor.organization_id, execution_id=execution_id))}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
