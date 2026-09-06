"""Phase 36G Stage 8 disabled-by-default durable open-song worker."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import wave
from uuid import uuid4

import pytest
from aios.open_song_factory import (
    ACE_STEP_LANGUAGE_MODEL_REVISION,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_SOURCE_COMMIT,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_SOURCE_COMMIT,
    OpenSongRequest,
    OpenSongRightsEvidence,
    OpenSongRuntimeBinding,
    build_open_song_plan,
)
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import AudioSongExecution, MediaAssetNode, Organization, User
from app.services.audio_open_song_pipeline import create_open_song_pipeline
from app.services.audio_song_providers import (
    AudioSongProviderFailure,
    ProviderAudioArtifact,
    ProviderDownloadedArtifact,
    ProviderOpenSongJob,
    ProviderOpenSongResult,
)
from app.services.audio_song_runtime import arm_audio_song_execution
from app.services.audio_song_worker import (
    AudioSongWorker,
    AudioSongWorkerError,
    OpenSongWorkerSecrets,
    _read_secret_file,
)
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import LocalMediaObjectStore

RUNTIME_EVIDENCE = "a" * 64
PRICING_EVIDENCE = "b" * 64
LICENSE_EVIDENCE = "c" * 64
BALANCE_EVIDENCE = "d" * 64
RIGHTS_EVIDENCE = "e" * 64
RUNTIME_IMAGE_REPOSITORY = "ghcr.io/aionex/open-song-handler"
RUNTIME_IMAGE_INDEX_DIGEST = "sha256:" + "7" * 64
RUNTIME_IMAGE_DIGEST = "sha256:" + "8" * 64
RUNTIME_IMAGE_SBOM = "9" * 64
RUNTIME_HANDLER_SOURCE = "0" * 64
ARTIFACT_HOST = "assets.example.test"


class Scope:
    def __init__(self, organization_id: str, user_id: str) -> None:
        self.organization_id = organization_id
        self.user_id = user_id


class FakeAdapter:
    def __init__(
        self,
        *,
        submit_job: ProviderOpenSongJob | None = None,
        retrieve_job: ProviderOpenSongJob | None = None,
        submit_failure: AudioSongProviderFailure | None = None,
        download_failure: AudioSongProviderFailure | None = None,
        bodies: dict[str, bytes] | None = None,
    ) -> None:
        self.submit_job = submit_job
        self.retrieve_job = retrieve_job
        self.submit_failure = submit_failure
        self.download_failure = download_failure
        self.bodies = bodies or {}
        self.submit_calls = 0
        self.retrieve_calls = 0
        self.download_calls = 0

    async def submit(self, request, *, credential: str, endpoint_id: str):
        del request, credential, endpoint_id
        self.submit_calls += 1
        if self.submit_failure is not None:
            raise self.submit_failure
        assert self.submit_job is not None
        return self.submit_job

    async def retrieve(self, job_id: str, *, credential: str, endpoint_id: str):
        del job_id, credential, endpoint_id
        self.retrieve_calls += 1
        assert self.retrieve_job is not None
        return self.retrieve_job

    async def download(self, artifact: ProviderAudioArtifact):
        self.download_calls += 1
        if self.download_failure is not None:
            raise self.download_failure
        body = self.bodies[artifact.url]
        return ProviderDownloadedArtifact(
            body=body,
            media_type="audio/wav",
            sha256=hashlib.sha256(body).hexdigest(),
        )


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        organization = Organization(
            id=f"p36g-song-worker-org-{suffix}",
            name=f"P36G Song Worker {tag}",
            slug=f"p36g-song-worker-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(organization)
        await session.flush()
        user = User(
            id=f"p36g-song-worker-user-{suffix}",
            organization_id=organization.id,
            role_id=None,
            email=f"{tag}-{suffix}@phase36g-song-worker.example.invalid",
            name="Phase36G Song Worker User",
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


def secrets() -> OpenSongWorkerSecrets:
    return OpenSongWorkerSecrets(
        api_key="runpod-stage8-worker-test-key",
        endpoint_id="stage8-worker-endpoint",
        artifact_hosts=frozenset({ARTIFACT_HOST}),
        runtime_image_repository=RUNTIME_IMAGE_REPOSITORY,
        runtime_image_index_digest=RUNTIME_IMAGE_INDEX_DIGEST,
        runtime_image_digest=RUNTIME_IMAGE_DIGEST,
        image_sbom_sha256=RUNTIME_IMAGE_SBOM,
        handler_source_sha256=RUNTIME_HANDLER_SOURCE,
    )


def runtime_binding() -> OpenSongRuntimeBinding:
    config = secrets()
    return OpenSongRuntimeBinding(
        route_id="runpod-flex-a40",
        endpoint_id_sha256=config.endpoint_id_sha256,
        container_image_repository=config.runtime_image_repository,
        container_image_index_digest=config.runtime_image_index_digest,
        container_image_digest=config.runtime_image_digest,
        image_sbom_sha256=config.image_sbom_sha256,
        handler_source_sha256=config.handler_source_sha256,
    )


def song_plan():
    return build_open_song_plan(
        OpenSongRequest(
            title="Governed worker open song",
            concept=(
                "Original cinematic electronic pop with a warm synthetic vocal, "
                "strong chorus, and clean resolved ending."
            ),
            lyrics=(
                "[Verse]\nA new horizon rises from the night.\n"
                "[Chorus]\nWe build the future in the morning light."
            ),
            language="en",
            duration_seconds=30,
            bpm=104,
            musical_key="Am",
            time_signature=4,
            seed=36_008,
            rights=OpenSongRightsEvidence(
                basis="original",
                commercial_use_authorized=True,
                provider_terms_accepted=True,
                ai_generated_disclosure_accepted=True,
                evidence_sha256=RIGHTS_EVIDENCE,
            ),
        )
    )


async def persist_armed(scope: Scope, key: str):
    async with SessionLocal() as session:
        result = await create_open_song_pipeline(
            session,
            scope=MediaGraphScope(scope.organization_id, scope.user_id),
            plan=song_plan(),
            idempotency_key=key,
            runtime_evidence_sha256=RUNTIME_EVIDENCE,
            pricing_evidence_sha256=PRICING_EVIDENCE,
            license_evidence_sha256=LICENSE_EVIDENCE,
            runtime_binding=runtime_binding(),
        )
        await arm_audio_song_execution(
            session,
            execution_id=result.execution_id,
            organization_id=scope.organization_id,
            approved_max_cost_usd=0.20,
            monthly_user_cap_usd=0.40,
            provider_balance_usd=1.0,
            balance_evidence_sha256=BALANCE_EVIDENCE,
        )
        await session.commit()
        return result


def wav_bytes(*, duration_seconds: float = 1.0) -> bytes:
    output = io.BytesIO()
    frame_count = int(48_000 * duration_seconds)
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(b"\x00\x00\x00\x00" * frame_count)
    return output.getvalue()


def artifact(name: str, body: bytes) -> ProviderAudioArtifact:
    return ProviderAudioArtifact(
        url=f"https://{ARTIFACT_HOST}/{name}.wav",
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        media_type="audio/wav",
        duration_seconds=1.0,
        sample_rate_hz=48_000,
        channels=2,
    )


def completed_job(body: bytes) -> tuple[ProviderOpenSongJob, dict[str, bytes]]:
    full = artifact("song", body)
    stems = {
        stem: artifact(f"stem-{stem}", body)
        for stem in ("vocals", "drums", "bass", "other")
    }
    result = ProviderOpenSongResult(
        schema="aionex.open-song-provider-result.v1",
        source_commit=ACE_STEP_SOURCE_COMMIT,
        model_revision=ACE_STEP_MODEL_REVISION,
        language_model_revision=ACE_STEP_LANGUAGE_MODEL_REVISION,
        container_image_digest=RUNTIME_IMAGE_DIGEST,
        separation_source_commit=DEMUCS_SOURCE_COMMIT,
        separation_checkpoint_sha256=DEMUCS_CHECKPOINT_SHA256,
        full_song=full,
        stems=stems,
    )
    bodies = {full.url: body, **{item.url: body for item in stems.values()}}
    return (
        ProviderOpenSongJob(
            job_id="stage8-worker-completed-job",
            state="COMPLETED",
            execution_time_ms=1_500,
            result=result,
            metadata={"status": "COMPLETED", "executiontime": 1_500},
        ),
        bodies,
    )


def worker(
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    live_enabled: bool = True,
    poll_seconds: int = 60,
) -> AudioSongWorker:
    return AudioSongWorker(
        adapter=adapter,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        secrets=secrets(),
        live_enabled=live_enabled,
        worker_id="stage8-audio-song-worker",
        poll_seconds=poll_seconds,
        lease_seconds=60,
        max_polls=10,
        health_path=tmp_path / "health.json",
    )


@pytest.mark.asyncio
async def test_worker_is_hard_disabled_without_loading_provider(tmp_path: Path) -> None:
    instance = AudioSongWorker(
        adapter=None,
        store=LocalMediaObjectStore(tmp_path / "objects"),
        secrets=None,
        live_enabled=False,
        health_path=tmp_path / "health.json",
    )
    assert await instance.run_once() is False
    payload = (tmp_path / "health.json").read_text(encoding="utf-8")
    assert '"status": "disabled"' in payload
    assert '"secret_returned": false' in payload


def test_health_file_never_persists_runtime_binding_values(tmp_path: Path) -> None:
    configured = secrets()
    instance = AudioSongWorker(
        adapter=FakeAdapter(),  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        secrets=configured,
        live_enabled=False,
        health_path=tmp_path / "health.json",
    )
    instance.write_health("disabled")
    raw = (tmp_path / "health.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["runtime_binding_loaded"] is True
    assert payload["runtime_binding_returned"] is False
    assert "runtime_binding" not in payload
    for private_value in (
        configured.api_key,
        configured.endpoint_id,
        configured.endpoint_id_sha256,
        configured.runtime_image_repository,
        configured.runtime_image_index_digest,
        configured.runtime_image_digest,
        configured.image_sbom_sha256,
        configured.handler_source_sha256,
    ):
        assert private_value not in raw


@pytest.mark.asyncio
async def test_submit_once_persists_job_and_defers_poll(tmp_path: Path) -> None:
    scope = await seed_scope("pending")
    try:
        result = await persist_armed(
            scope, f"open-song-worker-pending-{scope.organization_id}"
        )
        adapter = FakeAdapter(
            submit_job=ProviderOpenSongJob(
                job_id="stage8-worker-pending-job",
                state="IN_QUEUE",
                execution_time_ms=None,
                result=None,
                metadata={"status": "IN_QUEUE", "delaytime": 2},
            )
        )
        instance = worker(tmp_path, adapter)
        assert await instance.run_once() is True
        assert adapter.submit_calls == 1 and adapter.retrieve_calls == 0
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "queued"
            assert row.provider_state == "submitted"
            assert row.provider_job_id == "stage8-worker-pending-job"
            assert row.attempts == 1 and row.polls == 1
            assert row.available_at is not None
        assert await instance.run_once() is False
        assert adapter.submit_calls == 1
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_ambiguous_submit_stops_without_resubmit(tmp_path: Path) -> None:
    scope = await seed_scope("ambiguous")
    try:
        result = await persist_armed(
            scope, f"open-song-worker-ambiguous-{scope.organization_id}"
        )
        adapter = FakeAdapter(
            submit_failure=AudioSongProviderFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            )
        )
        instance = worker(tmp_path, adapter)
        assert await instance.run_once() is True
        assert adapter.submit_calls == 1
        assert await instance.run_once() is False
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "needs_review"
            assert row.provider_state == "ambiguous"
            assert row.provider_job_id is None
            assert row.attempts == 1
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_completed_job_stores_song_and_four_stems_atomically(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("completed")
    try:
        result = await persist_armed(
            scope, f"open-song-worker-completed-{scope.organization_id}"
        )
        body = wav_bytes()
        job, bodies = completed_job(body)
        adapter = FakeAdapter(submit_job=job, bodies=bodies)
        instance = worker(tmp_path, adapter)
        assert await instance.run_once() is True
        assert adapter.submit_calls == 1
        assert adapter.download_calls == 5
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "rendering"
            assert row.provider_state == "completed"
            assert row.stem_count == 4
            assert row.actual_billed_seconds == 2.0
            assert row.actual_cost_usd == 0.00068
            nodes = {
                item.logical_key: item
                for item in (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == result.graph_id
                        )
                    )
                ).all()
            }
            assert nodes["song"].status == "completed"
            for stem in ("vocals", "drums", "bass", "other"):
                assert nodes[f"stem-{stem}"].status == "completed"
            assert nodes["mix"].status == "planned"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_download_failure_after_durable_job_defers_same_job_not_resubmit(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("download-retry")
    try:
        result = await persist_armed(
            scope, f"open-song-worker-download-{scope.organization_id}"
        )
        body = wav_bytes()
        job, bodies = completed_job(body)
        adapter = FakeAdapter(
            submit_job=job,
            bodies=bodies,
            download_failure=AudioSongProviderFailure(
                "provider_artifact_transport",
                retryable=True,
                ambiguous_submission=False,
            ),
        )
        instance = worker(tmp_path, adapter)
        assert await instance.run_once() is True
        assert adapter.submit_calls == 1
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "queued"
            assert row.provider_state == "submitted"
            assert row.provider_job_id == job.job_id
            assert row.attempts == 1 and row.polls == 1
            assert row.available_at is not None
        assert await instance.run_once() is False
        assert adapter.submit_calls == 1
    finally:
        await cleanup(scope)



def test_secret_file_is_private_bounded_and_never_returned(tmp_path: Path) -> None:
    source = tmp_path / "runpod-open-song.env"
    source.write_text(
        "\n".join(
            (
                "RUNPOD_API_KEY=runpod-stage8-secret-test-key",
                "AUDIO_SONG_RUNPOD_ENDPOINT_ID=stage8-secret-endpoint",
                f"AUDIO_SONG_ARTIFACT_HOSTS={ARTIFACT_HOST}",
                f"AUDIO_SONG_RUNTIME_IMAGE_REPOSITORY={RUNTIME_IMAGE_REPOSITORY}",
                f"AUDIO_SONG_RUNTIME_IMAGE_INDEX_DIGEST={RUNTIME_IMAGE_INDEX_DIGEST}",
                f"AUDIO_SONG_RUNTIME_IMAGE_DIGEST={RUNTIME_IMAGE_DIGEST}",
                f"AUDIO_SONG_IMAGE_SBOM_SHA256={RUNTIME_IMAGE_SBOM}",
                f"AUDIO_SONG_HANDLER_SOURCE_SHA256={RUNTIME_HANDLER_SOURCE}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    source.chmod(0o600)
    loaded = OpenSongWorkerSecrets.from_values(_read_secret_file(str(source)))
    public = loaded.public_snapshot()
    assert public["credential_returned"] is False
    assert public["endpoint_id_returned"] is False
    assert "runpod-stage8-secret-test-key" not in repr(public)
    source.chmod(0o644)
    with pytest.raises(AudioSongWorkerError, match="private"):
        _read_secret_file(str(source))


def test_production_compose_activates_primary_song_worker_and_keeps_secondary_disabled() -> None:
    candidates = [
        Path(os.environ.get("AIOS_REPO_ROOT", "")),
        Path("/workspace"),
        *Path(__file__).resolve().parents,
    ]
    root = next(
        (
            candidate
            for candidate in candidates
            if candidate
            and (
                candidate / "web-dashboard/docker-compose.production.yml"
            ).is_file()
        ),
        None,
    )
    if root is None:
        pytest.skip("repository-level Compose sources are not mounted")
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  audio-song-worker:")
        secondary_start = source.index("  audio-song-worker-secondary:", start)
        block = source[start:secondary_start]
        secondary_block = source[
            secondary_start : source.index("  video-provider-worker:", secondary_start)
        ]
        assert 'profiles: ["audio-execution"]' in block
        assert 'AUDIO_SONG_LIVE_ENABLED: "true"' in block
        assert 'AUDIO_SONG_ENTRYPOINT_SECRET_BOOTSTRAP_ONLY: "true"' in block
        assert 'MEDIA_STORAGE_TYPE: local' in block
        assert 'MEDIA_STORAGE_TYPE: inherit' not in block
        assert "app.services.audio_song_worker" in block
        assert "runpod-open-song.env:ro" in block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
        assert 'user: "1000:1000"' not in block
        assert 'cap_drop: ["ALL"]' in block
        assert 'cap_add: ["CHOWN", "FOWNER", "SETGID", "SETUID"]' in block
        assert (
            'test: ["CMD", "su-exec", "aionex", "python", "-m", '
            '"app.services.audio_song_worker", "--healthcheck"]'
            in block
        )
        assert 'DAC_OVERRIDE' not in block
        assert 'profiles: ["audio-execution-secondary"]' in secondary_block
        assert 'AUDIO_SONG_LIVE_ENABLED: "false"' in secondary_block
        assert 'AUDIO_SONG_WORKER_ID: audio-song-secondary' in secondary_block
        assert 'AUDIO_SONG_ENTRYPOINT_SECRET_BOOTSTRAP_ONLY: "true"' in secondary_block
        assert 'MEDIA_STORAGE_TYPE: local' in secondary_block
        assert 'MEDIA_STORAGE_TYPE: inherit' not in secondary_block
        assert "app.services.audio_song_worker" in secondary_block
        assert "RUNPOD_GPU_SECONDARY.env" in secondary_block
        assert "runpod-open-song-secondary.env:ro" in secondary_block
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in secondary_block
        assert 'cap_drop: ["ALL"]' in secondary_block
        assert 'cap_add: ["CHOWN", "FOWNER", "SETGID", "SETUID"]' in secondary_block
        assert 'DAC_OVERRIDE' not in secondary_block
    entrypoint = (
        root / "web-dashboard/backend/scripts/docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert 'audio_song_secret_source="${AUDIO_SONG_RUNPOD_SECRET_FILE:-}"' in entrypoint
    assert 'install -m 0400 -o aionex -g aionex' in entrypoint
    audio_start = entrypoint.index('audio_song_secret_source="${AUDIO_SONG_RUNPOD_SECRET_FILE:-}"')
    audio_end = entrypoint.index('project_reference_source=', audio_start)
    audio_block = entrypoint[audio_start:audio_end]
    assert 'install -d -m 0700 -o root -g root "$runtime_dir"' in audio_block
    assert 'chown aionex:aionex "$runtime_dir"' in audio_block
    assert 'chmod 0700 "$runtime_dir"' in audio_block
    early_drop = 'if [ "${AUDIO_SONG_ENTRYPOINT_SECRET_BOOTSTRAP_ONLY:-false}" = "true" ]; then'
    assert early_drop in audio_block
    assert entrypoint.index(early_drop, audio_start) < entrypoint.index('project_reference_source=', audio_start)
    assert 'media_storage_root="${MEDIA_STORAGE_ROOT-/var/lib/aionex/media-assets}"' in audio_block
    assert 'if [ ! -d "$media_storage_root" ] || [ -L "$media_storage_root" ]; then' in audio_block
    assert "media_storage_meta=\"$(stat -c '%a:%u:%g' \"$media_storage_root\")\"" in audio_block
    assert 'if [ "$media_storage_meta" != "700:1000:1000" ]; then' in audio_block
    assert 'chown aionex:aionex "$media_storage_root"' in audio_block
    assert 'chmod 0700 "$media_storage_root"' in audio_block
    assert 'install -d -m 0700 -o aionex -g aionex "$media_storage_root"' in audio_block
    assert 'exec su-exec aionex "$@"' in audio_block
    assert 'DAC_OVERRIDE' not in block


async def persist_user_approved_unarmed(scope: Scope, key: str):
    async with SessionLocal() as session:
        result = await create_open_song_pipeline(
            session,
            scope=MediaGraphScope(scope.organization_id, scope.user_id),
            plan=song_plan(),
            idempotency_key=key,
            runtime_evidence_sha256=RUNTIME_EVIDENCE,
            pricing_evidence_sha256=PRICING_EVIDENCE,
            license_evidence_sha256=LICENSE_EVIDENCE,
            runtime_binding=runtime_binding(),
        )
        row = await session.get(AudioSongExecution, result.execution_id)
        assert row is not None
        row.provider_metadata = {
            **(row.provider_metadata or {}),
            "user_cost_approved": True,
            "approved_max_cost_usd": 0.20,
            "monthly_user_cap_usd": 0.40,
            "balance_check_delegated_to_secret_worker": True,
        }
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_secret_worker_arms_only_after_live_balance_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await seed_scope("balance-arm")
    try:
        result = await persist_user_approved_unarmed(
            scope, f"p36g-song-worker-balance-arm-{uuid4().hex}"
        )
        instance = worker(tmp_path, FakeAdapter())

        async def current_balance():
            return 1.0, BALANCE_EVIDENCE

        monkeypatch.setattr(instance, "_provider_balance_usd", current_balance)
        assert await instance._arm_one_user_approved() is True
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 0
            assert row.provider_metadata["balance_checked_by_secret_worker"] is True
            assert row.provider_metadata["provider_balance_sufficient_at_arm"] is True
            assert row.provider_job_id is None
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_secret_worker_refuses_insufficient_balance_without_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await seed_scope("balance-low")
    try:
        result = await persist_user_approved_unarmed(
            scope, f"p36g-song-worker-balance-low-{uuid4().hex}"
        )
        adapter = FakeAdapter()
        instance = worker(tmp_path, adapter)

        async def insufficient_balance():
            return 0.01, BALANCE_EVIDENCE

        monkeypatch.setattr(instance, "_provider_balance_usd", insufficient_balance)
        assert await instance._arm_one_user_approved() is False
        assert adapter.submit_calls == 0
        async with SessionLocal() as session:
            row = await session.get(AudioSongExecution, result.execution_id)
            assert row is not None
            assert row.status == "planned"
            assert row.attempts == 0
            assert row.provider_job_id is None
            assert row.provider_metadata["last_balance_check_sufficient"] is False
    finally:
        await cleanup(scope)
