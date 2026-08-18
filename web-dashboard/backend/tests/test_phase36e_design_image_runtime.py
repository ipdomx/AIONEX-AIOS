"""Phase 36E durable design-image authority without live provider calls."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from aios.design_factory import DESIGN_PRESETS, DesignPreset, DesignRequest, ProviderRuntimeEvidence
from app.db.base import SessionLocal
from app.db.models import (
    AIProvider,
    AuditEvent,
    DesignImageExecution,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    Project,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
    Workspace,
)
from app.core.config import settings
from app.services.ai_runtime_service import encrypt_provider_secret
from app.services.design_image_providers import ProviderImageResult
from app.services.design_image_derivative_worker import DesignImageDerivativeWorker
from app.services.design_image_derivatives import SharpDerivativeResult
from app.services.design_image_pipeline import create_routed_design_image_pipeline
from app.services.design_image_worker import DesignImageWorker
from app.services.design_image_runtime import (
    DesignImageExecutionAuthority,
    DesignImageExecutionError,
    DesignImageExecutionSpec,
    DesignImageLeaseLost,
    arm_design_image_execution,
    create_design_image_execution,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph, media_graph_snapshot
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.media_render_worker import MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z9ZsAAAAASUVORK5CYII="
)


class Scope:
    def __init__(self, org: Organization, user: User, workspace: Workspace, project: Project, job: StudioJob, asset: StudioAsset) -> None:
        self.org = org
        self.user = user
        self.workspace = workspace
        self.project = project
        self.job = job
        self.asset = asset


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:10]
    async with SessionLocal() as session:
        org = Organization(name=f"P36E {tag}", slug=f"p36e-{tag}-{suffix}", plan="enterprise", status="active")
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36e-{tag}-{suffix}@example.com",
            name="Phase36E Owner",
            password_hash="unused",
            status="active",
        )
        workspace = Workspace(
            organization_id=org.id,
            name="P36E Workspace",
            slug=f"p36e-ws-{suffix}",
            status="active",
        )
        session.add_all([user, workspace])
        await session.flush()
        project = Project(
            organization_id=org.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="P36E Design Project",
            slug=f"p36e-project-{suffix}",
            description="Durable provider image execution acceptance.",
            status="active",
            priority="high",
            progress=10,
        )
        session.add(project)
        await session.flush()
        job = StudioJob(
            organization_id=org.id,
            workspace_id=workspace.id,
            project_id=project.id,
            requested_by_id=user.id,
            department="image",
            output_kind="image",
            title="P36E Image",
            brief="Create a governed production-ready visual asset.",
            language="en-US",
            style="modern",
            provider_mode="provider_neutral",
            status="completed",
            progress=100,
            safety_status="passed",
            request_metadata={},
            result_metadata={},
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            organization_id=org.id,
            job_id=job.id,
            project_id=project.id,
            created_by_id=user.id,
            department="image",
            asset_type="image",
            title="P36E Image",
            filename="template.svg",
            media_type="image/svg+xml",
            storage_path="/tmp/p36e-template.svg",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={"render_status": "template"},
        )
        session.add(asset)
        await session.commit()
        return Scope(org, user, workspace, project, job, asset)


async def cleanup_scope(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == scope.org.id))
        await session.commit()


async def create_image_graph(scope: Scope, *, blocked_parent: bool = False) -> tuple[str, str]:
    nodes = []
    edges: list[MediaEdgeSpec] = []
    reuse = None
    if blocked_parent:
        nodes.append(MediaNodeSpec(key="source", node_type="image", media_type="image/png"))
        edges.append(MediaEdgeSpec("source", "final", ordinal=0))
    nodes.append(
        MediaNodeSpec(
            key="final",
            node_type="provider-image",
            media_type="image/png",
            prompt_metadata={"private": "must-not-leak"},
            parameters={"executor": "design-image-provider"},
        )
    )
    spec = MediaGraphSpec(
        title="P36E image execution",
        asset_kind="image",
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_profile="image-png-lossless",
        rights_metadata={"owner_consent": True},
        provenance=({"type": "phase36e-test"},),
    )
    async with SessionLocal() as session:
        graph = await create_media_graph(
            session,
            scope=MediaGraphScope(
                organization_id=scope.org.id,
                created_by_id=scope.user.id,
                workspace_id=scope.workspace.id,
                project_id=scope.project.id,
                studio_job_id=scope.job.id,
                studio_asset_id=scope.asset.id,
            ),
            spec=spec,
            idempotency_key=f"graph-{uuid4()}",
            reuse_nodes=reuse,
        )
        final = await session.scalar(
            select(MediaAssetNode).where(MediaAssetNode.graph_id == graph.id, MediaAssetNode.logical_key == "final")
        )
        assert final is not None
        await session.commit()
        return graph.id, final.id


async def create_execution(scope: Scope, graph_id: str, target_node_id: str, *, key: str | None = None) -> str:
    async with SessionLocal() as session:
        row = await create_design_image_execution(
            session,
            spec=DesignImageExecutionSpec(
                organization_id=scope.org.id,
                requested_by_id=scope.user.id,
                workspace_id=scope.workspace.id,
                project_id=scope.project.id,
                studio_job_id=scope.job.id,
                studio_asset_id=scope.asset.id,
                graph_id=graph_id,
                target_node_id=target_node_id,
                provider="openai",
                model="gpt-image-2",
                operation="generate",
                prompt="Create a precise blue geometric brand visual with no placeholder content.",
                idempotency_key=key or f"execution-{uuid4()}",
                request_options={"size": "1024x1024", "quality": "high"},
                output_format="png",
                estimated_cost_usd=0.02,
            ),
        )
        await session.commit()
        return row.id


@pytest.mark.asyncio
async def test_design_image_execution_is_fail_closed_until_explicitly_armed(tmp_path: Path) -> None:
    scope = await seed_scope("arm")
    try:
        graph_id, target_id = await create_image_graph(scope)
        execution_id = await create_execution(scope, graph_id, target_id, key="phase36e-arm-idempotency")
        duplicate_id = await create_execution(scope, graph_id, target_id, key="phase36e-arm-idempotency")
        assert duplicate_id == execution_id
        async with SessionLocal() as session:
            ffmpeg_steps = int(
                await session.scalar(
                    select(func.count(MediaRenderStep.id)).where(MediaRenderStep.graph_id == graph_id)
                ) or 0
            )
            assert ffmpeg_steps == 0
        authority = DesignImageExecutionAuthority(store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="worker-a")
        assert await authority.claim() is None
        async with SessionLocal() as session:
            row = await arm_design_image_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            assert row.status == "queued"
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.execution_id == execution_id and claim.fencing_token == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_parent_dependency_blocks_provider_image_claim(tmp_path: Path) -> None:
    scope = await seed_scope("dependency")
    try:
        graph_id, target_id = await create_image_graph(scope, blocked_parent=True)
        execution_id = await create_execution(scope, graph_id, target_id)
        async with SessionLocal() as session:
            await arm_design_image_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = DesignImageExecutionAuthority(store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="worker-a")
        assert await authority.claim() is None
        async with SessionLocal() as session:
            source = await session.scalar(
                select(MediaAssetNode).where(MediaAssetNode.graph_id == graph_id, MediaAssetNode.logical_key == "source")
            )
            assert source is not None
            source.status = "completed"
            source.storage_backend = "local"
            source.storage_key = "source.png"
            source.checksum = "b" * 64
            source.size_bytes = len(_PNG_1X1)
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.execution_id == execution_id
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_reclaimed_design_image_lease_rejects_stale_worker_and_materializes_studio_revision(tmp_path: Path) -> None:
    scope = await seed_scope("fencing")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = DesignImageExecutionAuthority(store=store, worker_id="worker-a", lease_seconds=30)
    worker_b = DesignImageExecutionAuthority(store=store, worker_id="worker-b", lease_seconds=30)
    try:
        graph_id, target_id = await create_image_graph(scope)
        execution_id = await create_execution(scope, graph_id, target_id)
        async with SessionLocal() as session:
            await arm_design_image_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        claim_a = await worker_a.claim()
        assert claim_a is not None and claim_a.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        claim_b = await worker_b.claim()
        assert claim_b is not None and claim_b.execution_id == execution_id and claim_b.fencing_token == 2
        with pytest.raises(DesignImageLeaseLost):
            await worker_a.renew(claim_a)
        result = await worker_b.complete_bytes(
            claim_b,
            body=_PNG_1X1,
            content_type="image/png",
            provider_request_id="provider-request-test",
            provider_response_metadata={
                "finish_reason": "success",
                "signed_url": "https://should-not-persist.example/token",
                "prompt": "must-not-persist",
            },
            usage_metadata={
                "images": 1,
                "input_tokens": 42,
                "output_tokens": 100,
                "input_tokens_details": {"text_tokens": 42, "image_tokens": 0},
                "api_token": "must-not-persist",
                "access_token": "must-not-persist",
            },
            actual_cost_usd=0.015,
        )
        assert result["status"] == "completed"
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, execution_id)
            node = await session.get(MediaAssetNode, target_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            revisions = int(
                await session.scalar(
                    select(func.count(StudioAssetRevision.id)).where(StudioAssetRevision.asset_id == scope.asset.id)
                ) or 0
            )
            audits = int(
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.resource_type == "design_image_execution",
                        AuditEvent.resource_id == execution_id,
                    )
                ) or 0
            )
            assert row is not None and row.status == "completed"
            assert node is not None and node.status == "completed" and node.media_type == "image/png"
            assert row.output_checksum == node.checksum and row.output_size_bytes == len(_PNG_1X1)
            assert "signed_url" not in row.provider_response_metadata
            assert "prompt" not in row.provider_response_metadata
            assert "api_token" not in row.usage_metadata
            assert "access_token" not in row.usage_metadata
            assert row.usage_metadata["input_tokens"] == 42
            assert row.usage_metadata["output_tokens"] == 100
            assert row.usage_metadata["input_tokens_details"] == {"text_tokens": 42, "image_tokens": 0}
            assert any(item.get("type") == "provider-image" for item in node.provenance)
            assert asset is not None and asset.current_revision == 2 and asset.media_type == "image/png"
            assert revisions == 1 and audits == 1
            snapshot_graph = await session.scalar(select(MediaAssetGraph).where(MediaAssetGraph.id == graph_id))
            assert snapshot_graph is not None and snapshot_graph.status == "completed"
            public = await media_graph_snapshot(session, snapshot_graph)
            assert "must-not-leak" not in repr(public)
            assert "compiled_prompt" not in repr(public)
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_random_bytes_cannot_be_committed_as_final_image(tmp_path: Path) -> None:
    scope = await seed_scope("invalid")
    try:
        graph_id, target_id = await create_image_graph(scope)
        execution_id = await create_execution(scope, graph_id, target_id)
        async with SessionLocal() as session:
            await arm_design_image_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = DesignImageExecutionAuthority(store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="worker-a")
        claim = await authority.claim()
        assert claim is not None
        with pytest.raises(DesignImageExecutionError):
            await authority.complete_bytes(
                claim,
                body=b"not-an-image",
                content_type="image/png",
                provider_request_id=None,
                provider_response_metadata={},
                usage_metadata={},
                actual_cost_usd=0,
            )
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, execution_id)
            node = await session.get(MediaAssetNode, target_id)
            assert row is not None and row.status == "running"
            assert node is not None and node.status == "planned" and node.storage_key is None
    finally:
        await cleanup_scope(scope)



@pytest.mark.asyncio
async def test_gemini_flash_lite_rejects_png_before_spend_and_accepts_jpeg() -> None:
    scope = await seed_scope("gemini-format")
    try:
        graph_id, target_id = await create_image_graph(scope)
        async with SessionLocal() as session:
            with pytest.raises(DesignImageExecutionError, match="output format is unsupported by provider model"):
                await create_design_image_execution(
                    session,
                    spec=DesignImageExecutionSpec(
                        organization_id=scope.org.id,
                        requested_by_id=scope.user.id,
                        workspace_id=scope.workspace.id,
                        project_id=scope.project.id,
                        studio_job_id=scope.job.id,
                        studio_asset_id=scope.asset.id,
                        graph_id=graph_id,
                        target_node_id=target_id,
                        provider="gemini",
                        model="gemini-3.1-flash-lite-image",
                        operation="generate",
                        prompt="Create a clean blue geometric brand visual.",
                        idempotency_key=f"gemini-png-{uuid4()}",
                        request_options={"aspect_ratio": "1:1", "image_size": "1K"},
                        output_format="png",
                        estimated_cost_usd=0.0,
                    ),
                )
            row = await create_design_image_execution(
                session,
                spec=DesignImageExecutionSpec(
                    organization_id=scope.org.id,
                    requested_by_id=scope.user.id,
                    workspace_id=scope.workspace.id,
                    project_id=scope.project.id,
                    studio_job_id=scope.job.id,
                    studio_asset_id=scope.asset.id,
                    graph_id=graph_id,
                    target_node_id=target_id,
                    provider="gemini",
                    model="gemini-3.1-flash-lite-image",
                    operation="generate",
                    prompt="Create a clean blue geometric brand visual.",
                    idempotency_key=f"gemini-jpeg-{uuid4()}",
                    request_options={"aspect_ratio": "1:1", "image_size": "1K"},
                    output_format="jpeg",
                    estimated_cost_usd=0.0,
                ),
            )
            assert row.status == "planned" and row.output_format == "jpeg" and row.armed_at is None
            await session.rollback()
    finally:
        await cleanup_scope(scope)

def test_design_image_schema_has_explicit_arm_fencing_cost_and_output_evidence() -> None:
    from app.db.base import Base
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["design_image_executions"].c.keys())
    assert {
        "status", "armed_at", "lease_token", "lease_owner", "lease_expires_at", "fencing_token",
        "provider", "model", "operation", "prompt_sha256", "estimated_cost_usd", "actual_cost_usd",
        "output_storage_key", "output_checksum", "usage_metadata", "provider_response_metadata", "cost_basis",
    } <= columns


@pytest.mark.asyncio
async def test_unknown_actual_cost_is_persisted_as_null_not_zero(tmp_path: Path) -> None:
    scope = await seed_scope("unknown-cost")
    try:
        graph_id, target_id = await create_image_graph(scope)
        execution_id = await create_execution(scope, graph_id, target_id)
        async with SessionLocal() as session:
            await arm_design_image_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = DesignImageExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="unknown-cost-worker"
        )
        claim = await authority.claim()
        assert claim is not None
        await authority.complete_bytes(
            claim,
            body=_PNG_1X1,
            content_type="image/png",
            provider_request_id="unknown-cost-request",
            provider_response_metadata={},
            usage_metadata={"cost_basis": "unknown"},
            actual_cost_usd=None,
            cost_basis="unknown",
        )
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, execution_id)
            assert row is not None
            assert row.actual_cost_usd is None
            assert row.cost_basis == "unknown"
    finally:
        await cleanup_scope(scope)


class _FakeLiveAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, request, *, credential: str, base_url: str):
        self.calls += 1
        assert request.provider == "openai"
        assert request.model == "gpt-image-2"
        assert request.operation == "generate"
        assert "precise blue geometric brand visual" in request.prompt
        assert credential == "fake-provider-credential"
        assert base_url == "https://api.openai.com"
        return ProviderImageResult(
            body=_PNG_1X1,
            content_type="image/png",
            request_id="fake-live-request",
            metadata={"status": "success"},
            usage={"images": 1},
            actual_cost_usd=0.001,
            cost_basis="official_provider_usage",
        )


@pytest.mark.asyncio
async def test_design_image_worker_loads_platform_provider_and_completes_durable_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await seed_scope("worker-db")
    platform_id = settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID
    created_platform = False
    store = LocalMediaObjectStore(tmp_path / "objects")
    try:
        async with SessionLocal() as session:
            platform = await session.get(Organization, platform_id)
            if platform is None:
                platform = Organization(
                    id=platform_id,
                    name="AIONEX Platform Providers",
                    slug=f"p36e-platform-{uuid4().hex[:8]}",
                    plan="enterprise",
                    status="active",
                )
                session.add(platform)
                await session.flush()
                created_platform = True
            session.add(
                AIProvider(
                    organization_id=platform_id,
                    name="OpenAI",
                    type="openai",
                    status="connected",
                    encrypted_api_key=encrypt_provider_secret("fake-provider-credential"),
                    base_url=None,
                    config={"enabled": True},
                )
            )
            await session.commit()

        graph_id, target_id = await create_image_graph(scope)
        execution_id = await create_execution(scope, graph_id, target_id)
        async with SessionLocal() as session:
            await arm_design_image_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()

        monkeypatch.setattr(settings, "DESIGN_IMAGE_LIVE_ENABLED", True)
        monkeypatch.setattr(
            settings, "DESIGN_IMAGE_WORKER_HEALTH_FILE", str(tmp_path / "worker-health.json")
        )
        adapter = _FakeLiveAdapter()
        authority = DesignImageExecutionAuthority(
            store=store, worker_id="p36e-worker-db", lease_seconds=30
        )
        worker = DesignImageWorker(
            authority=authority,
            store=store,
            adapters={"openai": adapter},
            worker_id="p36e-worker-db",
        )
        assert await worker.run_once() is True
        assert adapter.calls == 1
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, execution_id)
            node = await session.get(MediaAssetNode, target_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            assert row is not None and row.status == "completed"
            assert row.provider_request_id == "fake-live-request"
            assert row.actual_cost_usd == pytest.approx(0.001)
            assert row.cost_basis == "official_provider_usage"
            assert node is not None and node.status == "completed"
            assert asset is not None and asset.current_revision == 2
    finally:
        await cleanup_scope(scope)
        if created_platform:
            async with SessionLocal() as session:
                platform = await session.get(Organization, platform_id)
                if platform is not None:
                    await session.delete(platform)
                    await session.commit()


class _FakeSharpDerivativeRuntime:
    def preflight(self) -> dict[str, str]:
        return {"engine": "sharp", "engine_version": "0.35.3", "node_version": "24.19.0"}

    def render(self, *, source_body: bytes, source_format: str, source_checksum: str, spec):
        assert source_body == _PNG_1X1
        assert source_format == "png"
        assert source_checksum == __import__("hashlib").sha256(_PNG_1X1).hexdigest()
        assert spec.width == 1 and spec.height == 1 and spec.output_format == "png"
        checksum = __import__("hashlib").sha256(_PNG_1X1).hexdigest()
        return SharpDerivativeResult(
            body=_PNG_1X1,
            content_type="image/png",
            width=1,
            height=1,
            output_format="png",
            sha256=checksum,
            size_bytes=len(_PNG_1X1),
            input_sha256=checksum,
            command_hash=__import__("hashlib").sha256(b"phase36e-fake-sharp-command").hexdigest(),
            engine_version="0.35.3",
            metadata={
                "engine": "sharp",
                "engine_version": "0.35.3",
                "output_format": "png",
                "output_width": 1,
                "output_height": 1,
                "fit": "cover",
                "position": "centre",
            },
        )


@pytest.mark.asyncio
async def test_routed_pipeline_stays_no_spend_until_arm_and_sharp_worker_owns_only_sharp_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await seed_scope("routed-pipeline")
    store = LocalMediaObjectStore(tmp_path / "objects")
    original = DESIGN_PRESETS["social-square"]
    monkeypatch.setitem(
        DESIGN_PRESETS,
        "social-square",
        DesignPreset("social-square", 1, 1, "1:1", "social", ("png",)),
    )
    monkeypatch.setattr(settings, "DESIGN_IMAGE_DERIVATIVE_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "DESIGN_IMAGE_DERIVATIVE_WORKER_HEALTH_FILE",
        str(tmp_path / "derivative-health.json"),
    )
    try:
        request = DesignRequest(
            title="AIONEX routed visual",
            brief="Create one governed social visual for the durable Phase 36E pipeline acceptance.",
            use_case="social-post",
            preset_id="social-square",
            operation="generate",
        )
        evidence = (
            ProviderRuntimeEvidence(
                provider="openai",
                model="gpt-image-2",
                state="ready",
                proven_operations=frozenset({"generate", "edit"}),
                verified_output_formats=frozenset({"png"}),
                reason="Stage 3 bounded canary passed",
            ),
        )
        async with SessionLocal() as session:
            pipeline = await create_routed_design_image_pipeline(
                session,
                scope=MediaGraphScope(
                    organization_id=scope.org.id,
                    created_by_id=scope.user.id,
                    workspace_id=scope.workspace.id,
                    project_id=scope.project.id,
                    studio_job_id=scope.job.id,
                    studio_asset_id=scope.asset.id,
                ),
                request=request,
                runtime_evidence=evidence,
                provider_output_format="png",
                idempotency_key="phase36e-routed-pipeline-test",
                estimated_cost_usd=0.01,
            )
            row = await session.get(DesignImageExecution, pipeline.execution_id)
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(MediaRenderStep.graph_id == pipeline.graph_id)
                    )
                ).all()
            )
            assert row is not None and row.status == "planned" and row.armed_at is None
            assert pipeline.route.provider == "openai" and pipeline.route.model == "gpt-image-2"
            assert len(steps) == 1
            assert steps[0].engine == "sharp"
            assert steps[0].engine_version == "0.35.3"
            assert steps[0].operation == "design-image-derivative"
            await session.commit()

        authority = DesignImageExecutionAuthority(store=store, worker_id="route-provider", lease_seconds=30)
        assert await authority.claim() is None
        async with SessionLocal() as session:
            await arm_design_image_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        await authority.complete_bytes(
            claim,
            body=_PNG_1X1,
            content_type="image/png",
            provider_request_id="phase36e-route-provider-request",
            provider_response_metadata={"status": "success"},
            usage_metadata={"images": 1, "cost_basis": "official_provider_usage"},
            actual_cost_usd=0.001,
            cost_basis="official_provider_usage",
        )

        ffmpeg_worker = MediaRenderWorker(store=store, worker_id="ffmpeg-engine-filter-test")
        assert await ffmpeg_worker.claim() is None

        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, pipeline.graph_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            assert graph is not None and graph.status != "completed"
            assert asset is not None and asset.current_revision == 1

        derivative_worker = DesignImageDerivativeWorker(
            store=store,
            runtime=_FakeSharpDerivativeRuntime(),
            worker_id="sharp-engine-filter-test",
        )
        assert await derivative_worker.run_once() is True
        assert await derivative_worker.run_once() is False

        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, pipeline.graph_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            revision_count = int(
                await session.scalar(
                    select(func.count(StudioAssetRevision.id)).where(
                        StudioAssetRevision.asset_id == scope.asset.id
                    )
                )
                or 0
            )
            primary = await session.get(MediaAssetNode, pipeline.primary_derivative_node_id)
            assert graph is not None and graph.status == "completed"
            assert primary is not None and primary.status == "completed"
            assert primary.media_type == "image/png" and primary.checksum
            assert asset is not None and asset.current_revision == 2
            output = (asset.asset_metadata or {}).get("design_image_pipeline_output")
            assert isinstance(output, dict)
            assert output["graph_id"] == pipeline.graph_id
            assert output["route"]["provider"] == "openai"
            assert len(output["derivatives"]) == 1
            assert revision_count == 1
            public = await media_graph_snapshot(session, graph)
            assert "compiled_prompt" not in repr(public)
            assert request.brief not in repr(public)
    finally:
        DESIGN_PRESETS["social-square"] = original
        await cleanup_scope(scope)
