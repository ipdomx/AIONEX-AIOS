"""Phase 36G Stage 8 dedicated durable open-song authority."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_IMAGE_INDEX_DIGEST,
    ACE_STEP_IMAGE_REPOSITORY,
    ACE_STEP_LANGUAGE_MODEL,
    ACE_STEP_LANGUAGE_MODEL_REVISION,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_SOURCE_COMMIT,
    ACE_STEP_SPACE_REVISION,
    ACE_STEP_TURBO_MODEL_REVISION,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_MODEL,
    DEMUCS_SOURCE_COMMIT,
    OPEN_SONG_STEMS,
    OpenSongRequest,
    OpenSongRightsEvidence,
    OpenSongRuntimeBinding,
    build_open_song_plan,
)
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import (
    AudioSongExecution,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    User,
)
from app.services.audio_open_song_pipeline import (
    AudioOpenSongPipelineError,
    build_open_song_graph_spec,
    create_open_song_pipeline,
)
from app.services.audio_song_runtime import (
    AudioSongExecutionError,
    arm_audio_song_execution,
    audio_song_execution_snapshot,
    claim_audio_song_execution,
    complete_audio_song_provider_output,
    defer_audio_song_provider_poll,
    finalize_audio_song_execution,
    mark_audio_song_submitting,
    record_audio_song_provider_job,
    record_audio_song_provider_poll,
    recover_expired_audio_song_executions,
)
from app.services.media_graph_runtime import MediaGraphScope

RUNTIME_EVIDENCE = "a" * 64
PRICING_EVIDENCE = "b" * 64
LICENSE_EVIDENCE = "c" * 64
BALANCE_EVIDENCE = "d" * 64
RIGHTS_EVIDENCE = "e" * 64
RUNTIME_ENDPOINT_HASH = "f" * 64
RUNTIME_IMAGE_REPOSITORY = "ghcr.io/aionex/open-song-handler"
RUNTIME_IMAGE_INDEX_DIGEST = "sha256:" + "7" * 64
RUNTIME_IMAGE_DIGEST = "sha256:" + "8" * 64
RUNTIME_IMAGE_SBOM = "9" * 64
RUNTIME_HANDLER_SOURCE = "0" * 64


def runpod_binding() -> OpenSongRuntimeBinding:
    return OpenSongRuntimeBinding(
        route_id="runpod-flex-a40",
        endpoint_id_sha256=RUNTIME_ENDPOINT_HASH,
        container_image_repository=RUNTIME_IMAGE_REPOSITORY,
        container_image_index_digest=RUNTIME_IMAGE_INDEX_DIGEST,
        container_image_digest=RUNTIME_IMAGE_DIGEST,
        image_sbom_sha256=RUNTIME_IMAGE_SBOM,
        handler_source_sha256=RUNTIME_HANDLER_SOURCE,
    )


class Scope:
    def __init__(self, organization_id: str, user_id: str) -> None:
        self.organization_id = organization_id
        self.user_id = user_id


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        organization = Organization(
            id=f"p36g-song-org-{suffix}",
            name=f"P36G Song {tag}",
            slug=f"p36g-song-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(organization)
        await session.flush()
        user = User(
            id=f"p36g-song-user-{suffix}",
            organization_id=organization.id,
            role_id=None,
            email=f"{tag}-{suffix}@phase36g-song.example.invalid",
            name="Phase36G Song User",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.commit()
    return Scope(organization.id, user.id)


async def cleanup(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == scope.organization_id)
        )
        await session.commit()


def song_plan(route_id: str = "runpod-flex-a40"):
    rights = OpenSongRightsEvidence(
        basis="original",
        commercial_use_authorized=True,
        provider_terms_accepted=True,
        ai_generated_disclosure_accepted=True,
        evidence_sha256=RIGHTS_EVIDENCE,
    )
    request = OpenSongRequest(
        title="Governed source-built open song",
        concept=(
            "Original cinematic electronic pop with a warm synthetic vocal, "
            "strong chorus, and a clean ending."
        ),
        lyrics="[Verse]\nA new horizon rises.\n[Chorus]\nWe build the light together.",
        language="en",
        duration_seconds=30,
        bpm=104,
        musical_key="Am",
        time_signature=4,
        seed=36_008,
        rights=rights,
    )
    return build_open_song_plan(request, route_id=route_id)


async def persist_pipeline(scope: Scope, *, route_id: str, key: str):
    async with SessionLocal() as session:
        result = await create_open_song_pipeline(
            session,
            scope=MediaGraphScope(
                organization_id=scope.organization_id,
                created_by_id=scope.user_id,
            ),
            plan=song_plan(route_id),
            idempotency_key=key,
            runtime_evidence_sha256=RUNTIME_EVIDENCE,
            pricing_evidence_sha256=PRICING_EVIDENCE,
            license_evidence_sha256=LICENSE_EVIDENCE,
            runtime_binding=(
                runpod_binding() if route_id == "runpod-flex-a40" else None
            ),
        )
        await session.commit()
        return result


def artifact_bundle(prefix: str = "runpod") -> tuple[dict, dict[str, dict]]:
    full_song = {
        "storage_backend": "local",
        "storage_key": f"media/test/{prefix}/song.wav",
        "checksum": "1" * 64,
        "size_bytes": 384_044,
        "media_type": "audio/wav",
        "duration_seconds": 30.0,
        "sample_rate_hz": 48_000,
        "channels": 2,
    }
    stems: dict[str, dict] = {}
    for index, stem in enumerate(OPEN_SONG_STEMS, start=2):
        stems[stem] = {
            "storage_backend": "local",
            "storage_key": f"media/test/{prefix}/stem-{stem}.wav",
            "checksum": str(index) * 64,
            "size_bytes": 384_044,
            "media_type": "audio/wav",
            "duration_seconds": 30.0,
            "sample_rate_hz": 48_000,
            "channels": 2,
        }
    return full_song, stems


def provider_evidence(
    *,
    source_commit: str,
    image_digest: str | None,
    model_revision: str = ACE_STEP_MODEL_REVISION,
) -> dict:
    return {
        "schema": "aionex.open-song-provider-result.v1",
        "source_commit": source_commit,
        "model_revision": model_revision,
        "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
        "separation_source_commit": DEMUCS_SOURCE_COMMIT,
        "separation_checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
        "container_image_digest": image_digest,
        "raw_title_returned": False,
        "raw_concept_returned": False,
        "raw_lyrics_returned": False,
    }


def test_graph_spec_has_provider_bundle_then_local_ffmpeg_dag() -> None:
    spec = build_open_song_graph_spec(song_plan())
    assert set(spec.topological_order) == {
        "song",
        "stem-vocals",
        "stem-drums",
        "stem-bass",
        "stem-other",
        "mix",
        "master",
        "waveform",
        "export",
    }
    node_map = {node.key: node for node in spec.nodes}
    assert node_map["song"].parameters.get("operation") is None
    assert node_map["stem-vocals"].parameters.get("operation") is None
    assert node_map["mix"].parameters["operation"] == "audio_mix"
    assert node_map["master"].parameters["operation"] == "audio_master"
    assert node_map["waveform"].parameters["operation"] == "audio_waveform"
    assert node_map["export"].parameters["operation"] == "audio_export"
    public = repr(spec.provenance).lower()
    assert "a new horizon rises" not in public
    assert "cinematic electronic pop" not in public


@pytest.mark.asyncio
async def test_pipeline_is_dedicated_unarmed_supply_chain_bound_and_idempotent() -> None:
    scope = await seed_scope("planned")
    key = f"open-song-planned-{scope.organization_id}"
    try:
        async with SessionLocal() as session:
            first = await create_open_song_pipeline(
                session,
                scope=MediaGraphScope(scope.organization_id, scope.user_id),
                plan=song_plan(),
                idempotency_key=key,
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
                license_evidence_sha256=LICENSE_EVIDENCE,
                runtime_binding=runpod_binding(),
            )
            again = await create_open_song_pipeline(
                session,
                scope=MediaGraphScope(scope.organization_id, scope.user_id),
                plan=song_plan(),
                idempotency_key=key,
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
                license_evidence_sha256=LICENSE_EVIDENCE,
                runtime_binding=runpod_binding(),
            )
            assert again.execution_id == first.execution_id
            row = await session.get(AudioSongExecution, first.execution_id)
            assert row is not None
            assert row.status == "planned" and row.provider_state == "not_started"
            assert row.attempts == 0 and row.max_attempts == 1
            assert row.route_id == "runpod-flex-a40"
            assert row.provider == "runpod"
            assert row.model_revision == ACE_STEP_MODEL_REVISION
            assert row.language_model == ACE_STEP_LANGUAGE_MODEL
            assert row.language_model_revision == ACE_STEP_LANGUAGE_MODEL_REVISION
            assert row.source_commit == ACE_STEP_SOURCE_COMMIT
            assert row.base_container_image_repository == ACE_STEP_IMAGE_REPOSITORY
            assert row.base_container_image_index_digest == ACE_STEP_IMAGE_INDEX_DIGEST
            assert row.base_container_image_digest == ACE_STEP_IMAGE_AMD64_DIGEST
            assert row.endpoint_id_sha256 == RUNTIME_ENDPOINT_HASH
            assert row.image_sbom_sha256 == RUNTIME_IMAGE_SBOM
            assert row.handler_source_sha256 == RUNTIME_HANDLER_SOURCE
            assert row.container_image_repository == RUNTIME_IMAGE_REPOSITORY
            assert row.container_image_index_digest == RUNTIME_IMAGE_INDEX_DIGEST
            assert row.container_image_digest == RUNTIME_IMAGE_DIGEST
            assert row.separation_model == DEMUCS_MODEL
            assert row.separation_source_commit == DEMUCS_SOURCE_COMMIT
            assert row.separation_checkpoint_sha256 == DEMUCS_CHECKPOINT_SHA256
            assert row.max_cost_usd == 0.2
            assert row.actual_cost_usd is None
            public = first.public_snapshot()
            assert public["gpu_job_created"] is False
            assert public["provider_request_started"] is False
            assert public["raw_title_returned"] is False
            assert public["raw_concept_returned"] is False
            assert public["raw_lyrics_returned"] is False
            rendered = repr(public)
            assert "A new horizon rises" not in rendered
            assert "cinematic electronic pop" not in rendered.lower()

            with pytest.raises(AudioOpenSongPipelineError, match="conflicts"):
                await create_open_song_pipeline(
                    session,
                    scope=MediaGraphScope(scope.organization_id, scope.user_id),
                    plan=song_plan("ace-step-official-space-acceptance"),
                    idempotency_key=key,
                    runtime_evidence_sha256=RUNTIME_EVIDENCE,
                    pricing_evidence_sha256=PRICING_EVIDENCE,
                    license_evidence_sha256=LICENSE_EVIDENCE,
                )
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_runpod_arm_requires_exact_cap_balance_and_monthly_policy() -> None:
    scope = await seed_scope("arm")
    result = await persist_pipeline(
        scope,
        route_id="runpod-flex-a40",
        key=f"open-song-arm-{scope.organization_id}",
    )
    try:
        async with SessionLocal() as session:
            with pytest.raises(AudioSongExecutionError, match="durable cap"):
                await arm_audio_song_execution(
                    session,
                    execution_id=result.execution_id,
                    organization_id=scope.organization_id,
                    approved_max_cost_usd=0.19,
                    monthly_user_cap_usd=0.40,
                    provider_balance_usd=1.0,
                    balance_evidence_sha256=BALANCE_EVIDENCE,
                )
            with pytest.raises(AudioSongExecutionError, match="balance"):
                await arm_audio_song_execution(
                    session,
                    execution_id=result.execution_id,
                    organization_id=scope.organization_id,
                    approved_max_cost_usd=0.20,
                    monthly_user_cap_usd=0.40,
                    provider_balance_usd=0.199,
                    balance_evidence_sha256=BALANCE_EVIDENCE,
                )
            row = await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.20,
                monthly_user_cap_usd=0.40,
                provider_balance_usd=1.0,
                balance_evidence_sha256=BALANCE_EVIDENCE,
            )
            assert row.status == "queued"
            assert row.provider_state == "not_started"
            assert row.attempts == 0
            assert (row.provider_metadata or {})["monthly_user_cap_usd"] == 0.4
            assert (row.provider_metadata or {})["provider_balance_sufficient_at_arm"] is True
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_submission_bundle_completion_and_final_qa_are_durable() -> None:
    scope = await seed_scope("complete")
    result = await persist_pipeline(
        scope,
        route_id="runpod-flex-a40",
        key=f"open-song-complete-{scope.organization_id}",
    )
    try:
        async with SessionLocal() as session:
            await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.20,
                monthly_user_cap_usd=0.40,
                provider_balance_usd=1.0,
                balance_evidence_sha256=BALANCE_EVIDENCE,
            )
            claim = await claim_audio_song_execution(
                session,
                worker_id="audio-song-test-worker",
                lease_seconds=300,
            )
            assert claim is not None
            assert claim.attempts == 1
            lease_token = str(claim.lease_token)
            fencing_token = int(claim.fencing_token)
            await mark_audio_song_submitting(
                session,
                execution_id=claim.id,
                worker_id="audio-song-test-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            await record_audio_song_provider_job(
                session,
                execution_id=claim.id,
                worker_id="audio-song-test-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
                provider_job_id="runpod-stage8-job-1",
                provider_metadata={"state": "IN_QUEUE"},
            )
            await record_audio_song_provider_poll(
                session,
                execution_id=claim.id,
                worker_id="audio-song-test-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
                state="running",
                provider_metadata={"state": "IN_PROGRESS"},
            )
            full_song, stems = artifact_bundle()
            completed = await complete_audio_song_provider_output(
                session,
                execution_id=claim.id,
                worker_id="audio-song-test-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
                full_song=full_song,
                stems=stems,
                actual_billed_seconds=100.0,
                actual_cost_usd=0.034,
                provider_metadata=provider_evidence(
                    source_commit=ACE_STEP_SOURCE_COMMIT,
                    image_digest=RUNTIME_IMAGE_DIGEST,
                ),
            )
            assert completed.status == "rendering"
            assert completed.provider_state == "completed"
            assert completed.actual_cost_known is True
            assert completed.actual_cost_usd == 0.034
            assert completed.stem_count == 4
            await session.commit()

        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, result.graph_id)
            assert graph is not None and graph.status == "rendering"
            nodes = {
                node.logical_key: node
                for node in (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == result.graph_id
                        )
                    )
                ).all()
            }
            assert nodes["song"].status == "completed"
            assert nodes["song"].storage_key == "media/test/runpod/song.wav"
            for stem in OPEN_SONG_STEMS:
                assert nodes[f"stem-{stem}"].status == "completed"
                assert nodes[f"stem-{stem}"].storage_key.endswith(
                    f"stem-{stem}.wav"
                )
            assert nodes["mix"].status == "planned"
            public = await audio_song_execution_snapshot(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
            )
            assert public["cost"]["actual_cost_usd"] == 0.034
            assert public["provider_job_id_returned"] is False
            assert public["full_song"]["storage_locator_returned"] is False
            assert all(
                item["storage_locator_returned"] is False
                for item in public["stems"].values()
            )
            assert public["final_output"]["storage_locator_returned"] is False
            assert public["raw_title_returned"] is False
            assert public["raw_concept_returned"] is False
            assert public["raw_lyrics_returned"] is False
            rendered = repr(public)
            assert "runpod-stage8-job-1" not in rendered
            assert "media/test/runpod" not in rendered

            for index, logical_key in enumerate(
                ("mix", "master", "waveform", "export"), start=6
            ):
                node = nodes[logical_key]
                node.status = "completed"
                node.storage_backend = "local"
                node.storage_key = f"media/test/final/{logical_key}"
                node.checksum = str(index) * 64
                node.size_bytes = 100_000 + index
                node.source_metadata = {"duration_seconds": 30.0}
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(
                            MediaRenderStep.graph_id == result.graph_id
                        )
                    )
                ).all()
            )
            for step in steps:
                step.status = "completed"
                step.output_checksum = nodes[
                    next(
                        node.logical_key
                        for node in nodes.values()
                        if node.id == step.target_node_id
                    )
                ].checksum
                step.result_metadata = {
                    "qa": {
                        "audio_analysis": {
                            "passed": True,
                            "integrated_lufs": -14.1,
                            "true_peak_dbtp": -1.2,
                        }
                    }
                }
            graph.status = "completed"
            finalized = await finalize_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
            )
            assert finalized.status == "completed"
            assert finalized.final_output_checksum == nodes["export"].checksum
            assert finalized.final_output_duration_seconds == 30.0
            assert finalized.final_audio_qa["passed"] is True
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_expired_ambiguous_submission_never_automatically_retries() -> None:
    scope = await seed_scope("ambiguous")
    result = await persist_pipeline(
        scope,
        route_id="runpod-flex-a40",
        key=f"open-song-ambiguous-{scope.organization_id}",
    )
    now = datetime(2026, 8, 23, 16, 0, tzinfo=UTC)
    try:
        async with SessionLocal() as session:
            await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.20,
                monthly_user_cap_usd=0.40,
                provider_balance_usd=1.0,
                balance_evidence_sha256=BALANCE_EVIDENCE,
                current=now,
            )
            claim = await claim_audio_song_execution(
                session,
                worker_id="audio-song-ambiguous-worker",
                lease_seconds=60,
                current=now,
            )
            assert claim is not None
            await mark_audio_song_submitting(
                session,
                execution_id=claim.id,
                worker_id="audio-song-ambiguous-worker",
                lease_token=str(claim.lease_token),
                fencing_token=int(claim.fencing_token),
                current=now,
            )
            await session.commit()

        async with SessionLocal() as session:
            recovered = await recover_expired_audio_song_executions(
                session,
                current=now + timedelta(seconds=61),
            )
            assert recovered == {"recovered": 0, "needs_review": 1, "observed": 1}
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "needs_review"
            assert row.provider_state == "ambiguous"
            assert row.attempts == 1 and row.max_attempts == 1
            assert row.error_metadata["automatic_retry"] is False
            assert row.error_metadata["automatic_cross_provider_fallback"] is False
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_official_space_acceptance_route_is_zero_cost_and_image_free() -> None:
    scope = await seed_scope("space")
    result = await persist_pipeline(
        scope,
        route_id="ace-step-official-space-acceptance",
        key=f"open-song-space-{scope.organization_id}",
    )
    try:
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.provider == "huggingface-space"
            assert row.model == "acestep-v15-turbo"
            assert row.model_revision == ACE_STEP_TURBO_MODEL_REVISION
            assert row.source_commit == ACE_STEP_SPACE_REVISION
            assert row.base_container_image_repository is None
            assert row.base_container_image_index_digest is None
            assert row.base_container_image_digest is None
            assert row.endpoint_id_sha256 is None
            assert row.image_sbom_sha256 is None
            assert row.handler_source_sha256 is None
            assert row.container_image_repository is None
            assert row.container_image_index_digest is None
            assert row.container_image_digest is None
            assert row.max_cost_usd == 0.0
            await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.0,
                monthly_user_cap_usd=0.0,
                provider_balance_usd=None,
                balance_evidence_sha256=None,
            )
            claim = await claim_audio_song_execution(
                session,
                worker_id="audio-song-space-worker",
                lease_seconds=300,
            )
            assert claim is not None
            lease_token = str(claim.lease_token)
            fencing_token = int(claim.fencing_token)
            await mark_audio_song_submitting(
                session,
                execution_id=claim.id,
                worker_id="audio-song-space-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            await record_audio_song_provider_job(
                session,
                execution_id=claim.id,
                worker_id="audio-song-space-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
                provider_job_id="hf-space-event-1",
                provider_metadata={"queue": "zerogpu"},
            )
            full_song, stems = artifact_bundle("space")
            completed = await complete_audio_song_provider_output(
                session,
                execution_id=claim.id,
                worker_id="audio-song-space-worker",
                lease_token=lease_token,
                fencing_token=fencing_token,
                full_song=full_song,
                stems=stems,
                actual_billed_seconds=0.0,
                actual_cost_usd=0.0,
                provider_metadata=provider_evidence(
                    source_commit=ACE_STEP_SPACE_REVISION,
                    image_digest=None,
                    model_revision=ACE_STEP_TURBO_MODEL_REVISION,
                ),
            )
            assert completed.actual_cost_known is True
            assert completed.actual_cost_usd == 0.0
            assert completed.actual_billed_seconds == 0.0
            await session.commit()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_claim_can_be_scoped_to_exact_runpod_endpoint_binding() -> None:
    scope = await seed_scope("endpoint-claim")
    result = await persist_pipeline(
        scope,
        route_id="runpod-flex-a40",
        key=f"open-song-endpoint-claim-{scope.organization_id}",
    )
    try:
        async with SessionLocal() as session:
            await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.20,
                monthly_user_cap_usd=0.40,
                provider_balance_usd=1.0,
                balance_evidence_sha256=BALANCE_EVIDENCE,
            )
            wrong = await claim_audio_song_execution(
                session,
                worker_id="audio-song-secondary",
                lease_seconds=60,
                allowed_route_ids={"runpod-flex-a40"},
                endpoint_id_sha256="1" * 64,
            )
            assert wrong is None
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 0

            right = await claim_audio_song_execution(
                session,
                worker_id="audio-song-primary",
                lease_seconds=60,
                allowed_route_ids={"runpod-flex-a40"},
                endpoint_id_sha256=RUNTIME_ENDPOINT_HASH,
            )
            assert right is not None
            assert right.id == result.execution_id
            assert right.attempts == 1
            assert right.lease_owner == "audio-song-primary"
            await session.rollback()
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_durable_poll_deferral_prevents_hot_loop_and_preserves_attempt() -> None:
    scope = await seed_scope("defer")
    result = await persist_pipeline(
        scope,
        route_id="runpod-flex-a40",
        key=f"open-song-defer-{scope.organization_id}",
    )
    now = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
    try:
        async with SessionLocal() as session:
            await arm_audio_song_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.organization_id,
                approved_max_cost_usd=0.20,
                monthly_user_cap_usd=0.40,
                provider_balance_usd=1.0,
                balance_evidence_sha256=BALANCE_EVIDENCE,
                current=now,
            )
            claim = await claim_audio_song_execution(
                session,
                worker_id="audio-song-defer-worker",
                lease_seconds=60,
                allowed_route_ids={"runpod-flex-a40"},
                current=now,
            )
            assert claim is not None
            await mark_audio_song_submitting(
                session,
                execution_id=claim.id,
                worker_id="audio-song-defer-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                current=now,
            )
            await record_audio_song_provider_job(
                session,
                execution_id=claim.id,
                worker_id="audio-song-defer-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                provider_job_id="runpod-stage8-defer-job",
                provider_metadata={"status": "IN_QUEUE"},
                current=now,
            )
            deferred = await defer_audio_song_provider_poll(
                session,
                execution_id=claim.id,
                worker_id="audio-song-defer-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                delay_seconds=10,
                current=now,
            )
            assert deferred.status == "queued"
            assert deferred.provider_state == "submitted"
            assert deferred.available_at == now + timedelta(seconds=10)
            assert deferred.lease_owner is None and deferred.lease_token is None
            assert deferred.attempts == 1
            await session.commit()

        async with SessionLocal() as session:
            early = await claim_audio_song_execution(
                session,
                worker_id="audio-song-defer-worker",
                lease_seconds=60,
                allowed_route_ids={"runpod-flex-a40"},
                current=now + timedelta(seconds=9),
            )
            assert early is None
            due = await claim_audio_song_execution(
                session,
                worker_id="audio-song-defer-worker",
                lease_seconds=60,
                allowed_route_ids={"runpod-flex-a40"},
                current=now + timedelta(seconds=10),
            )
            assert due is not None
            assert due.attempts == 1
            assert due.fencing_token == 2
            assert due.provider_state == "submitted"
            await session.rollback()
    finally:
        await cleanup(scope)
