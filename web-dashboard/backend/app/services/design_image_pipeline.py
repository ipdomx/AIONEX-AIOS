"""Phase 36E fail-closed routed image pipeline planning.

This service is the durable entry boundary between runtime-proven image routing,
provider execution and local Sharp derivatives. Creation is deliberately no-spend:
the provider execution remains ``planned`` until the existing explicit arm call.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Iterable

from aios.design_factory import (
    IMAGE_PROVIDER_CAPABILITIES,
    DesignFactoryError,
    DesignRequest,
    ProviderRouteDecision,
    ProviderRuntimeEvidence,
    RasterExportSpec,
    compile_provider_prompt,
    responsive_raster_exports,
    route_live_provider,
)
from app.db.models import MediaAssetNode
from app.services.design_image_runtime import (
    DesignImageExecutionSpec,
    create_design_image_execution,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


class DesignImagePipelineError(RuntimeError):
    """A routed image pipeline cannot be created without weakening a safety boundary."""


@dataclass(frozen=True, slots=True)
class RoutedDesignImagePipeline:
    graph_id: str
    execution_id: str
    provider_source_node_id: str
    primary_derivative_node_id: str
    derivative_node_ids: tuple[str, ...]
    route: ProviderRouteDecision
    exports: tuple[RasterExportSpec, ...]
    fingerprint: str


def _capability(provider: str, model: str):
    for item in IMAGE_PROVIDER_CAPABILITIES:
        if item.provider == provider and item.model == model:
            return item
    raise DesignImagePipelineError("live route capability disappeared from the governed matrix")


def _fingerprint(
    *,
    request: DesignRequest,
    route: ProviderRouteDecision,
    exports: tuple[RasterExportSpec, ...],
    caller_key: str,
    reference_node_ids: tuple[str, ...],
    mask_node_id: str | None,
) -> str:
    payload = {
        "request": asdict(request),
        "route": {
            "provider": route.provider,
            "model": route.model,
            "operation": route.operation,
            "provider_output_format": route.provider_output_format,
            "target_preset_id": route.target_preset_id,
            "requires_resampling": route.requires_resampling,
        },
        "exports": [asdict(item) for item in exports],
        "caller_key": caller_key,
        "reference_node_ids": list(reference_node_ids),
        "mask_node_id": mask_node_id,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def _load_reusable_input(
    session: AsyncSession,
    *,
    organization_id: str,
    node_id: str,
) -> MediaAssetNode:
    row = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == node_id,
            MediaAssetNode.organization_id == organization_id,
        )
    )
    if (
        row is None
        or row.status != "completed"
        or not row.storage_key
        or not row.checksum
        or not row.media_type
        or row.media_type not in _CONTENT_TYPES.values()
    ):
        raise DesignImagePipelineError("design image reference input is unavailable")
    return row


async def create_routed_design_image_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    request: DesignRequest,
    runtime_evidence: Iterable[ProviderRuntimeEvidence],
    provider_output_format: str,
    idempotency_key: str,
    derivative_preset_ids: Iterable[str] = (),
    reference_node_ids: Iterable[str] = (),
    mask_node_id: str | None = None,
    estimated_cost_usd: float = 0.0,
) -> RoutedDesignImagePipeline:
    """Create a routed provider-source + Sharp-derivative DAG without arming spend."""
    caller_key = idempotency_key.strip()
    if not 8 <= len(caller_key) <= 160:
        raise DesignImagePipelineError("design image pipeline idempotency key is invalid")
    reference_ids = tuple(str(item).strip() for item in reference_node_ids if str(item).strip())
    if len(reference_ids) != len(set(reference_ids)) or len(reference_ids) > 14:
        raise DesignImagePipelineError("design image reference set is invalid")
    if request.reference_count != len(reference_ids):
        raise DesignImagePipelineError("design image request/reference count does not match")
    if mask_node_id and mask_node_id in reference_ids:
        raise DesignImagePipelineError("design image mask cannot alias a reference input")
    if request.operation == "generate" and (reference_ids or mask_node_id):
        raise DesignImagePipelineError("generate pipeline cannot carry edit inputs")
    if request.operation != "generate" and not reference_ids:
        raise DesignImagePipelineError("non-generate pipeline requires a governed reference input")
    if request.operation == "inpaint" and not mask_node_id:
        raise DesignImagePipelineError("inpaint pipeline requires a governed mask input")
    if request.operation != "inpaint" and mask_node_id:
        raise DesignImagePipelineError("mask input is only accepted for inpaint")

    try:
        route = route_live_provider(
            request,
            output_format=provider_output_format,
            evidence=runtime_evidence,
        )
        exports = responsive_raster_exports(
            request,
            derivative_preset_ids=derivative_preset_ids,
        )
    except DesignFactoryError as exc:
        raise DesignImagePipelineError(str(exc)) from exc
    if not exports:
        raise DesignImagePipelineError("design image pipeline has no governed derivatives")

    capability = _capability(route.provider, route.model)
    compiled = compile_provider_prompt(request, capability)
    fingerprint = _fingerprint(
        request=request,
        route=route,
        exports=exports,
        caller_key=caller_key,
        reference_node_ids=reference_ids,
        mask_node_id=mask_node_id,
    )

    nodes: list[MediaNodeSpec] = []
    edges: list[MediaEdgeSpec] = []
    reusable: dict[str, MediaAssetNode] = {}
    for index, node_id in enumerate(reference_ids):
        old = await _load_reusable_input(
            session,
            organization_id=scope.organization_id,
            node_id=node_id,
        )
        key = f"reference-{index:02d}"
        nodes.append(MediaNodeSpec(key=key, node_type="image", media_type=old.media_type))
        reusable[key] = old
        edges.append(MediaEdgeSpec(key, "provider-source", ordinal=index))
    if mask_node_id:
        mask = await _load_reusable_input(
            session,
            organization_id=scope.organization_id,
            node_id=mask_node_id,
        )
        nodes.append(MediaNodeSpec(key="mask", node_type="mask", media_type=mask.media_type))
        reusable["mask"] = mask
        edges.append(MediaEdgeSpec("mask", "provider-source", ordinal=len(reference_ids)))

    source_media_type = _CONTENT_TYPES[route.provider_output_format]
    nodes.append(
        MediaNodeSpec(
            key="provider-source",
            node_type="provider-image",
            media_type=source_media_type,
            parameters={
                "executor": "design-image-provider",
                "provider_operation": request.operation,
                "output_format": route.provider_output_format,
            },
            provenance=(
                {
                    "type": "phase36e-live-route",
                    "provider": route.provider,
                    "model": route.model,
                    "operation": route.operation,
                    "output_format": route.provider_output_format,
                    "evidence_state": route.evidence_state,
                },
            ),
        )
    )

    derivative_keys: list[str] = []
    for index, export in enumerate(exports):
        key = f"derivative-{index:02d}-{export.preset_id}-{export.output_format}"
        derivative_keys.append(key)
        nodes.append(
            MediaNodeSpec(
                key=key,
                node_type="image-derivative",
                media_type=_CONTENT_TYPES[export.output_format],
                parameters={
                    "operation": "design-image-derivative",
                    "engine": "sharp",
                    "output_profile": f"design-{export.preset_id}-{export.output_format}",
                    "preset_id": export.preset_id,
                    "width": export.width,
                    "height": export.height,
                    "output_format": export.output_format,
                    "fit": export.fit,
                    "position": export.position,
                    "hardware_adapter": "software",
                },
                provenance=(
                    {
                        "type": "phase36e-responsive-export",
                        "preset_id": export.preset_id,
                        "output_format": export.output_format,
                    },
                ),
            )
        )
        edges.append(MediaEdgeSpec("provider-source", key, ordinal=index))

    graph = await create_media_graph(
        session,
        scope=scope,
        spec=MediaGraphSpec(
            title=request.title,
            asset_kind="image",
            nodes=tuple(nodes),
            edges=tuple(edges),
            output_profile="image-png-lossless",
            rights_metadata={"phase36e_governed": True},
            provenance=(
                {
                    "type": "phase36e-design-image-pipeline",
                    "fingerprint": fingerprint,
                },
            ),
        ),
        idempotency_key=f"p36e-graph-{fingerprint}",
        reuse_nodes=reusable,
    )

    rows = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(MediaAssetNode.graph_id == graph.id)
                .order_by(MediaAssetNode.logical_key)
            )
        ).all()
    )
    by_key = {row.logical_key: row for row in rows}
    source = by_key.get("provider-source")
    derivatives = [by_key.get(key) for key in derivative_keys]
    if source is None or any(row is None for row in derivatives):
        raise DesignImagePipelineError("design image pipeline graph materialization is incomplete")
    derivative_rows = [row for row in derivatives if row is not None]
    primary = derivative_rows[0]
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "design_image_pipeline": {
            "fingerprint": fingerprint,
            "provider_source_node_id": source.id,
            "primary_derivative_node_id": primary.id,
            "derivative_node_ids": [row.id for row in derivative_rows],
            "route": {
                "provider": route.provider,
                "model": route.model,
                "operation": route.operation,
                "provider_output_format": route.provider_output_format,
                "target_preset_id": route.target_preset_id,
                "requires_resampling": route.requires_resampling,
                "evidence_state": route.evidence_state,
            },
        },
    }

    request_options = dict(compiled.settings)
    request_options["output_format"] = route.provider_output_format
    execution = await create_design_image_execution(
        session,
        spec=DesignImageExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            graph_id=graph.id,
            target_node_id=source.id,
            provider=route.provider,
            model=route.model,
            operation=request.operation,
            prompt=compiled.prompt,
            idempotency_key=f"p36e-exec-{fingerprint}",
            request_options=request_options,
            output_format=route.provider_output_format,
            estimated_cost_usd=estimated_cost_usd,
        ),
    )
    await session.flush()
    return RoutedDesignImagePipeline(
        graph_id=graph.id,
        execution_id=execution.id,
        provider_source_node_id=source.id,
        primary_derivative_node_id=primary.id,
        derivative_node_ids=tuple(row.id for row in derivative_rows),
        route=route,
        exports=exports,
        fingerprint=fingerprint,
    )
