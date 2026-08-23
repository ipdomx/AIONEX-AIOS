"""Phase 36G Stage 7 durable low-cost Lyria music contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from aios.music_factory import (
    MusicRequest,
    MusicRightsEvidence,
    build_music_plan,
)
from sqlalchemy import delete, select

from app.db.base import Base, SessionLocal
from app.db.models import (
    AudioMusicExecution,
    MediaAssetGraph,
    MediaAssetNode,
    Organization,
    User,
)
from app.services.audio_music_pipeline import (
    AudioMusicPipelineError,
    build_lyria_music_graph_spec,
    create_lyria_music_pipeline,
)
from app.services.audio_music_runtime import (
    AudioMusicExecutionAuthority,
    AudioMusicExecutionError,
    AudioMusicLeaseLost,
    arm_audio_music_execution,
    audio_music_execution_snapshot,
)
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import LocalMediaObjectStore


RUNTIME_EVIDENCE = "c" * 64
PRICING_EVIDENCE = "d" * 64
APPROVAL_EVIDENCE = "e" * 64


MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15" + b"stage7-governed-music" * 256


class Scope:
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        org = Organization(
            id=f"p36g-music-org-{suffix}",
            name=f"P36G Music {tag}",
            slug=f"p36g-music-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            id=f"p36g-music-user-{suffix}",
            organization_id=org.id,
            role_id=None,
            email=f"{tag}-{suffix}@phase36g-music.example.invalid",
            name="Phase36G Music User",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.commit()
    return Scope(org.id, user.id)


async def cleanup(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == scope.org_id))
        await session.commit()


def rights() -> MusicRightsEvidence:
    return MusicRightsEvidence(
        basis="instrumental",
        evidence_sha256=None,
        commercial_use_authorized=True,
        user_accepts_provider_terms=True,
    )


def plan(*, tier: str = "draft", approved: bool = False, draft: str | None = None):
    return build_music_plan(
        MusicRequest(
            title=f"Governed {tier} music",
            prompt="Original bright instrumental electronic music with a clear intro and ending.",
            language="en",
            rights=rights(),
            tier=tier,
            final_generation_approved=approved,
            final_approval_evidence_sha256=(APPROVAL_EVIDENCE if approved else None),
            prior_draft_checksum=draft,
        )
    )


@pytest.mark.asyncio
async def test_music_pipeline_is_draft_first_unarmed_and_exact_cost_gated(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("draft")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = AudioMusicExecutionAuthority(
        store=store,
        worker_id="music-worker-a",
        lease_seconds=30,
    )
    try:
        draft_plan = plan()
        spec = build_lyria_music_graph_spec(draft_plan)
        assert spec.topological_order == (
            "music",
            "cleanup",
            "master",
            "waveform",
            "export",
        )
        assert spec.output_profile == "audio-wav-pcm"
        assert spec.rights_metadata["preview_model"] is True
        assert spec.rights_metadata["synthid_disclosure_required"] is True
        async with SessionLocal() as session:
            result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(
                    organization_id=scope.org_id,
                    created_by_id=scope.user_id,
                ),
                plan=draft_plan,
                idempotency_key=f"music-draft-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            again = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(
                    organization_id=scope.org_id,
                    created_by_id=scope.user_id,
                ),
                plan=draft_plan,
                idempotency_key=f"music-draft-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            assert again.music_execution_id == result.music_execution_id
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.status == "planned"
            assert row.provider_state == "not_started"
            assert row.tier == "draft"
            assert row.model == "lyria-3-clip-preview"
            assert row.estimated_cost_usd == 0.04
            assert row.max_cost_usd == 0.04
            assert row.attempts == 0 and row.max_attempts == 1
            assert row.preview_model is True
            assert row.synthid_disclosure_required is True
            with pytest.raises(AudioMusicExecutionError, match="approval"):
                await arm_audio_music_execution(
                    session,
                    execution_id=row.id,
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.08,
                )
            armed = await arm_audio_music_execution(
                session,
                execution_id=row.id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.04,
            )
            assert armed.status == "queued"
            public = await audio_music_execution_snapshot(
                session,
                execution_id=row.id,
                organization_id=scope.org_id,
            )
            assert public["cost_policy"]["monthly_user_cap_usd"] == 0.40
            assert public["monthly_cost_gate"]["reserved_after_usd"] == 0.04
            assert public["reuse_same_user_plan"] is True
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        assert claim.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.attempts == 1 and row.status == "running"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_pre_submit_expiry_reclaims_same_attempt_and_fences_stale_worker(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("reclaim")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = AudioMusicExecutionAuthority(
        store=store,
        worker_id="music-worker-a",
        lease_seconds=30,
    )
    worker_b = AudioMusicExecutionAuthority(
        store=store,
        worker_id="music-worker-b",
        lease_seconds=30,
    )
    try:
        async with SessionLocal() as session:
            result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=plan(),
                idempotency_key=f"music-reclaim-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            await arm_audio_music_execution(
                session,
                execution_id=result.music_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.04,
            )
            await session.commit()
        stale = await worker_a.claim()
        assert stale is not None and stale.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        current = await worker_b.claim()
        assert current is not None and current.fencing_token == 2
        with pytest.raises(AudioMusicLeaseLost):
            await worker_a.mark_submission_started(stale)
        await worker_b.mark_submission_started(current)
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.attempts == 1
            assert row.lease_owner == "music-worker-b"
            assert row.provider_state == "submitting"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_expired_submitting_music_becomes_ambiguous_without_resubmit(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("ambiguous")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = AudioMusicExecutionAuthority(
        store=store,
        worker_id="music-worker-a",
        lease_seconds=30,
    )
    try:
        async with SessionLocal() as session:
            result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=plan(),
                idempotency_key=f"music-ambiguous-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            await arm_audio_music_execution(
                session,
                execution_id=result.music_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.04,
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert await authority.reap_ambiguous_submissions() == 1
        assert await authority.claim() is None
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.status == "failed"
            assert row.provider_state == "ambiguous"
            assert row.attempts == 1
            assert row.error_code == "music_submission_ambiguous"
            assert row.lease_token is None and row.lease_owner is None
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_completed_music_is_stored_hash_only_and_opens_local_dag(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("complete")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = AudioMusicExecutionAuthority(
        store=store,
        worker_id="music-worker-a",
        lease_seconds=30,
    )
    try:
        async with SessionLocal() as session:
            result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=plan(),
                idempotency_key=f"music-complete-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            await arm_audio_music_execution(
                session,
                execution_id=result.music_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.04,
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        completed = await authority.complete_bytes(
            claim,
            body=MP3_BYTES,
            content_type="audio/mpeg",
            provider_request_id="provider-music-request-1",
            provider_response_metadata={
                "model": "lyria-3-clip-preview",
                "tier": "draft",
                "nominal_duration_seconds": 30,
                "returned_text_sha256": "c" * 64,
                "returned_text_characters": 42,
                "raw_returned_text_returned": False,
                "synthid_watermark_expected": True,
            },
            usage_metadata={
                "official_fixed_request_usd": 0.04,
                "provider_usage_reported": False,
            },
            actual_cost_usd=0.04,
            cost_basis="official_fixed_request",
        )
        assert completed["fixed_cost_usd"] == 0.04
        async with SessionLocal() as session:
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.status == "completed"
            assert row.provider_state == "completed"
            assert row.actual_cost_usd == 0.04
            assert row.output_checksum
            assert row.output_storage_key
            assert store.get_bytes(row.output_storage_key, max_bytes=10_000_000) == MP3_BYTES
            graph = await session.get(MediaAssetGraph, result.graph_id)
            assert graph is not None and graph.status == "rendering"
            music = await session.get(MediaAssetNode, result.music_node_id)
            assert music is not None and music.status == "completed"
            cleanup_node = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == result.graph_id,
                    MediaAssetNode.logical_key == "cleanup",
                )
            )
            assert cleanup_node is not None and cleanup_node.status == "planned"
            public = await audio_music_execution_snapshot(
                session,
                execution_id=row.id,
                organization_id=scope.org_id,
            )
            assert public["runtime_evidence_sha256"] == RUNTIME_EVIDENCE
            assert public["pricing_evidence_sha256"] == PRICING_EVIDENCE
            assert public["prompt_sha256"] and public["lyrics_sha256"] is None
            assert public["raw_prompt_returned"] is False
            assert public["raw_lyrics_returned"] is False
            assert public["raw_provider_text_returned"] is False
            assert public["automatic_retry"] is False
            assert public["provider_request_recorded"] is True
            rendered = repr(public)
            assert "Original bright instrumental" not in rendered
            assert "provider-music-request-1" not in rendered
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_music_idempotency_key_rejects_a_different_plan() -> None:
    scope = await seed_scope("conflict")
    try:
        async with SessionLocal() as session:
            await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=plan(),
                idempotency_key=f"music-conflict-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            final = plan(tier="final", approved=True, draft="d" * 64)
            with pytest.raises(AudioMusicPipelineError, match="conflicts"):
                await create_lyria_music_pipeline(
                    session,
                    scope=MediaGraphScope(scope.org_id, scope.user_id),
                    plan=final,
                    idempotency_key=f"music-conflict-{scope.org_id}",
                    runtime_evidence_sha256=RUNTIME_EVIDENCE,
                    pricing_evidence_sha256=PRICING_EVIDENCE,
                )
    finally:
        await cleanup(scope)



@pytest.mark.asyncio
async def test_same_user_same_plan_reuses_execution_across_idempotency_keys() -> None:
    scope = await seed_scope("reuse")
    try:
        async with SessionLocal() as session:
            music_plan = plan()
            first = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=music_plan,
                idempotency_key=f"music-reuse-a-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            second = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=music_plan,
                idempotency_key=f"music-reuse-b-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            assert second.music_execution_id == first.music_execution_id
            assert second.graph_id == first.graph_id
            rows = list(
                (
                    await session.scalars(
                        select(AudioMusicExecution).where(
                            AudioMusicExecution.organization_id == scope.org_id
                        )
                    )
                ).all()
            )
            graphs = list(
                (
                    await session.scalars(
                        select(MediaAssetGraph).where(
                            MediaAssetGraph.organization_id == scope.org_id
                        )
                    )
                ).all()
            )
            assert len(rows) == 1
            assert len(graphs) == 1
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_final_music_requires_completed_draft_from_same_user() -> None:
    scope = await seed_scope("final-draft")
    draft_output_checksum = "f" * 64
    try:
        final_plan = plan(
            tier="final",
            approved=True,
            draft=draft_output_checksum,
        )
        async with SessionLocal() as session:
            with pytest.raises(AudioMusicPipelineError, match="completed governed draft"):
                await create_lyria_music_pipeline(
                    session,
                    scope=MediaGraphScope(scope.org_id, scope.user_id),
                    plan=final_plan,
                    idempotency_key=f"music-final-no-draft-{scope.org_id}",
                    runtime_evidence_sha256=RUNTIME_EVIDENCE,
                    pricing_evidence_sha256=PRICING_EVIDENCE,
                )

            draft_result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=plan(),
                idempotency_key=f"music-final-draft-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            draft_row = await session.get(
                AudioMusicExecution, draft_result.music_execution_id
            )
            assert draft_row is not None
            draft_row.status = "completed"
            draft_row.provider_state = "completed"
            draft_row.output_checksum = draft_output_checksum
            draft_row.completed_at = datetime.now(UTC)
            await session.flush()

            result = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=final_plan,
                idempotency_key=f"music-final-with-draft-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.tier == "final"
            assert row.prior_draft_checksum == draft_output_checksum
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_music_monthly_draft_limit_blocks_request_eleven_before_claim() -> None:
    scope = await seed_scope("monthly-limit")
    try:
        async with SessionLocal() as session:
            for index in range(10):
                music_plan = build_music_plan(
                    MusicRequest(
                        title=f"Governed draft music {index}",
                        prompt=(
                            "Original bright instrumental electronic music with a clear "
                            f"intro and ending, governed variation {index}."
                        ),
                        language="en",
                        rights=rights(),
                        tier="draft",
                    )
                )
                result = await create_lyria_music_pipeline(
                    session,
                    scope=MediaGraphScope(scope.org_id, scope.user_id),
                    plan=music_plan,
                    idempotency_key=f"music-monthly-{index}-{scope.org_id}",
                    runtime_evidence_sha256=RUNTIME_EVIDENCE,
                    pricing_evidence_sha256=PRICING_EVIDENCE,
                )
                await arm_audio_music_execution(
                    session,
                    execution_id=result.music_execution_id,
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.04,
                )

            eleventh_plan = build_music_plan(
                MusicRequest(
                    title="Governed draft music eleven",
                    prompt=(
                        "Original bright instrumental electronic music with a clear "
                        "intro and ending, governed variation eleven."
                    ),
                    language="en",
                    rights=rights(),
                    tier="draft",
                )
            )
            eleventh = await create_lyria_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=eleventh_plan,
                idempotency_key=f"music-monthly-eleven-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            with pytest.raises(AudioMusicExecutionError, match="monthly draft limit"):
                await arm_audio_music_execution(
                    session,
                    execution_id=eleventh.music_execution_id,
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.04,
                )
            row = await session.get(AudioMusicExecution, eleventh.music_execution_id)
            assert row is not None
            assert row.status == "planned"
            assert row.attempts == 0
    finally:
        await cleanup(scope)

def test_audio_music_schema_has_cost_rights_fencing_and_redaction_evidence() -> None:
    columns = set(Base.metadata.tables["audio_music_executions"].c.keys())
    assert {
        "provider_state",
        "tier",
        "plan_checksum",
        "runtime_evidence_sha256",
        "pricing_evidence_sha256",
        "prompt_sha256",
        "lyrics_sha256",
        "rights_basis",
        "rights_evidence_sha256",
        "final_generation_approved",
        "final_approval_evidence_sha256",
        "prior_draft_checksum",
        "preview_model",
        "synthid_disclosure_required",
        "attempts",
        "max_attempts",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "estimated_cost_usd",
        "max_cost_usd",
        "actual_cost_usd",
        "output_storage_key",
        "output_checksum",
        "returned_text_sha256",
    } <= columns
