from __future__ import annotations

from uuid import uuid4

import pytest
from aios.stable_audio_factory import (
    StableAudioRequest,
    StableAudioRightsEvidence,
    build_stable_audio_plan,
)
from sqlalchemy import delete

from app.db.base import SessionLocal
from app.db.models import AudioMusicExecution, Organization, User
from app.services.audio_music_runtime import (
    AudioMusicExecutionError,
    arm_audio_music_execution,
    audio_music_execution_snapshot,
)
from app.services.audio_stable_music_pipeline import (
    build_stable_audio_music_graph_spec,
    create_stable_audio_music_pipeline,
)
from app.services.media_graph_runtime import MediaGraphScope

RUNTIME_EVIDENCE = "7" * 64
PRICING_EVIDENCE = "8" * 64


class Scope:
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        org = Organization(
            id=f"p36g-stable-org-{suffix}",
            name=f"P36G Stability {tag}",
            slug=f"p36g-stability-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            id=f"p36g-stable-user-{suffix}",
            organization_id=org.id,
            role_id=None,
            email=f"{tag}-{suffix}@phase36g-stability.example.invalid",
            name="Phase36G Stability User",
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


def plan(tag: str):
    return build_stable_audio_plan(
        StableAudioRequest(
            title=f"Governed Stability draft {tag}",
            prompt=(
                f"Original cinematic instrumental music {tag} with piano, strings, "
                "gentle percussion, and a clean ending."
            ),
            language="en",
            rights=StableAudioRightsEvidence(
                commercial_use_authorized=True,
                user_accepts_provider_terms=True,
            ),
        )
    )


@pytest.mark.asyncio
async def test_stable_audio_pipeline_is_unarmed_exact_cost_and_truth_bounded() -> None:
    scope = await seed_scope("single")
    try:
        stable_plan = plan("single")
        spec = build_stable_audio_music_graph_spec(stable_plan)
        assert spec.topological_order == (
            "music",
            "cleanup",
            "master",
            "waveform",
            "export",
        )
        assert spec.rights_metadata["preview_model"] is False
        assert spec.rights_metadata["synthid_disclosure_required"] is False
        assert spec.rights_metadata["ai_generated_disclosure_required"] is True
        async with SessionLocal() as session:
            result = await create_stable_audio_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=stable_plan,
                idempotency_key=f"stable-single-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            row = await session.get(AudioMusicExecution, result.music_execution_id)
            assert row is not None
            assert row.provider == "stability"
            assert row.model == "stable-audio-2.5"
            assert row.tier == "draft"
            assert row.status == "planned"
            assert row.provider_state == "not_started"
            assert row.attempts == 0 and row.max_attempts == 1
            assert row.estimated_cost_usd == 0.20
            assert row.max_cost_usd == 0.20
            assert row.preview_model is False
            assert row.synthid_disclosure_required is False
            assert row.request_options["ai_generated_disclosure_required"] is True
            with pytest.raises(AudioMusicExecutionError, match="approval"):
                await arm_audio_music_execution(
                    session,
                    execution_id=row.id,
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.19,
                )
            await arm_audio_music_execution(
                session,
                execution_id=row.id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.20,
            )
            public = await audio_music_execution_snapshot(
                session,
                execution_id=row.id,
                organization_id=scope.org_id,
            )
            assert public["monthly_cost_gate"]["reserved_after_usd"] == 0.20
            assert public["provider"] == "stability"
            assert public["model"] == "stable-audio-2.5"
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_stable_audio_same_plan_reuses_execution_across_idempotency_keys() -> None:
    scope = await seed_scope("reuse")
    try:
        stable_plan = plan("reuse")
        async with SessionLocal() as session:
            first = await create_stable_audio_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=stable_plan,
                idempotency_key=f"stable-reuse-a-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            second = await create_stable_audio_music_pipeline(
                session,
                scope=MediaGraphScope(scope.org_id, scope.user_id),
                plan=stable_plan,
                idempotency_key=f"stable-reuse-b-{scope.org_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
            )
            assert first.music_execution_id == second.music_execution_id
            assert first.graph_id == second.graph_id
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_stable_audio_third_monthly_request_is_blocked_before_claim() -> None:
    scope = await seed_scope("cap")
    try:
        async with SessionLocal() as session:
            ids: list[str] = []
            for index in range(3):
                result = await create_stable_audio_music_pipeline(
                    session,
                    scope=MediaGraphScope(scope.org_id, scope.user_id),
                    plan=plan(f"cap-{index}"),
                    idempotency_key=f"stable-cap-{index}-{scope.org_id}",
                    runtime_evidence_sha256=RUNTIME_EVIDENCE,
                    pricing_evidence_sha256=PRICING_EVIDENCE,
                )
                ids.append(result.music_execution_id)
            await arm_audio_music_execution(
                session,
                execution_id=ids[0],
                organization_id=scope.org_id,
                approved_max_cost_usd=0.20,
            )
            await arm_audio_music_execution(
                session,
                execution_id=ids[1],
                organization_id=scope.org_id,
                approved_max_cost_usd=0.20,
            )
            with pytest.raises(AudioMusicExecutionError, match="monthly cost cap"):
                await arm_audio_music_execution(
                    session,
                    execution_id=ids[2],
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.20,
                )
            third = await session.get(AudioMusicExecution, ids[2])
            assert third is not None
            assert third.status == "planned"
            assert third.attempts == 0
            await session.commit()
    finally:
        await cleanup(scope)
