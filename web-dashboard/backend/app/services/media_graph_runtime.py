"""Durable Phase 36D media-graph persistence and partial-revision planning."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.db.models import (
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    uuid_str,
)
from app.services.media_orchestrator import (
    FFMPEG_TARGET_VERSION,
    MediaEdgeSpec,
    MediaGraphError,
    MediaGraphSpec,
    MediaNodeSpec,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class MediaGraphScope:
    organization_id: str
    created_by_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None


def _stable_idempotency(*parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _operation_for(node: MediaNodeSpec) -> tuple[str | None, str | None, str]:
    operation = str(node.parameters.get("operation") or "").strip().lower() or None
    profile = str(node.parameters.get("output_profile") or "").strip() or None
    hardware = str(node.parameters.get("hardware_adapter") or "software").strip().lower()
    return operation, profile, hardware


async def create_media_graph(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    spec: MediaGraphSpec,
    idempotency_key: str,
    reuse_nodes: dict[str, MediaAssetNode] | None = None,
) -> MediaAssetGraph:
    """Persist one tenant-scoped DAG and its render steps exactly once."""
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise MediaGraphError("media graph idempotency key is invalid")
    existing = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.organization_id == scope.organization_id,
            MediaAssetGraph.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    graph = MediaAssetGraph(
        id=uuid_str(),
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        studio_job_id=scope.studio_job_id,
        studio_asset_id=scope.studio_asset_id,
        created_by_id=scope.created_by_id,
        title=spec.title,
        asset_kind=spec.asset_kind,
        output_profile=spec.output_profile,
        status="planned",
        graph_version=spec.graph_version,
        idempotency_key=key,
        graph_checksum=spec.checksum,
        graph_metadata={"schema": "36D.1", "topological_order": list(spec.topological_order)},
        rights_metadata=dict(spec.rights_metadata),
        provenance=list(spec.provenance),
    )
    session.add(graph)
    await session.flush()

    reused = reuse_nodes or {}
    rows: dict[str, MediaAssetNode] = {}
    for node in spec.nodes:
        prior = reused.get(node.key)
        row = MediaAssetNode(
            id=uuid_str(),
            graph_id=graph.id,
            organization_id=scope.organization_id,
            created_by_id=scope.created_by_id,
            logical_key=node.key,
            revision=node.revision,
            node_type=node.node_type,
            media_type=node.media_type,
            status="completed" if prior is not None else "planned",
            storage_backend=prior.storage_backend if prior is not None else None,
            storage_key=prior.storage_key if prior is not None else None,
            checksum=prior.checksum if prior is not None else None,
            size_bytes=prior.size_bytes if prior is not None else None,
            idempotency_key=_stable_idempotency(graph.id, node.key, str(node.revision)),
            source_metadata={},
            prompt_metadata=dict(node.prompt_metadata),
            rights_metadata=dict(node.rights_metadata),
            provenance=[
                *list(node.provenance),
                *(
                    [
                        {
                            "type": "reused-render",
                            "source_graph_id": prior.graph_id,
                            "source_node_id": prior.id,
                            "checksum": prior.checksum,
                        }
                    ]
                    if prior is not None
                    else []
                ),
            ],
            scene_metadata=dict(node.scene_metadata),
            timeline_metadata=dict(node.timeline_metadata),
            operation_metadata=dict(node.parameters),
        )
        rows[node.key] = row
        session.add(row)
    await session.flush()

    for edge in spec.edges:
        session.add(
            MediaAssetEdge(
                id=uuid_str(),
                graph_id=graph.id,
                organization_id=scope.organization_id,
                parent_node_id=rows[edge.parent].id,
                child_node_id=rows[edge.child].id,
                dependency_type=edge.dependency_type,
                ordinal=edge.ordinal,
            )
        )

    for node in spec.nodes:
        if node.key in reused:
            continue
        operation, profile_id, hardware = _operation_for(node)
        if operation is None:
            continue
        selected_profile = profile_id or spec.output_profile
        session.add(
            MediaRenderStep(
                id=uuid_str(),
                graph_id=graph.id,
                organization_id=scope.organization_id,
                target_node_id=rows[node.key].id,
                step_key=f"{node.key}:r{node.revision}:{operation}",
                operation=operation,
                output_profile=selected_profile,
                engine="ffmpeg",
                engine_version=FFMPEG_TARGET_VERSION,
                hardware_adapter=hardware,
                status="planned",
                attempts=0,
                max_attempts=3,
                idempotency_key=_stable_idempotency(
                    spec.checksum, node.key, str(node.revision), operation, selected_profile
                ),
                input_checksums=[],
                result_metadata={},
            )
        )
    await session.flush()
    return graph


async def load_media_graph_spec(
    session: AsyncSession, graph: MediaAssetGraph
) -> tuple[MediaGraphSpec, dict[str, MediaAssetNode]]:
    node_rows = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(MediaAssetNode.graph_id == graph.id)
                .order_by(MediaAssetNode.logical_key)
            )
        ).all()
    )
    rows_by_key = {row.logical_key: row for row in node_rows}
    edge_rows = list(
        (
            await session.scalars(
                select(MediaAssetEdge)
                .where(MediaAssetEdge.graph_id == graph.id)
                .order_by(MediaAssetEdge.ordinal, MediaAssetEdge.id)
            )
        ).all()
    )
    key_by_id = {row.id: row.logical_key for row in node_rows}
    nodes = tuple(
        MediaNodeSpec(
            key=row.logical_key,
            node_type=row.node_type,
            media_type=row.media_type,
            revision=row.revision,
            parameters=dict(row.operation_metadata or {}),
            prompt_metadata=dict(row.prompt_metadata or {}),
            rights_metadata=dict(row.rights_metadata or {}),
            provenance=tuple(row.provenance or ()),
            scene_metadata=dict(row.scene_metadata or {}),
            timeline_metadata=dict(row.timeline_metadata or {}),
        )
        for row in node_rows
    )
    edges = tuple(
        MediaEdgeSpec(
            parent=key_by_id[row.parent_node_id],
            child=key_by_id[row.child_node_id],
            dependency_type=row.dependency_type,
            ordinal=row.ordinal,
        )
        for row in edge_rows
    )
    return (
        MediaGraphSpec(
            title=graph.title,
            asset_kind=graph.asset_kind,
            nodes=nodes,
            edges=edges,
            output_profile=graph.output_profile,
            graph_version=graph.graph_version,
            rights_metadata=dict(graph.rights_metadata or {}),
            provenance=tuple(graph.provenance or ()),
        ),
        rows_by_key,
    )


async def create_partial_media_revision(
    session: AsyncSession,
    *,
    graph: MediaAssetGraph,
    created_by_id: str,
    node_parameter_updates: dict[str, dict[str, Any]],
    idempotency_key: str,
) -> tuple[MediaAssetGraph, tuple[str, ...]]:
    """Create a new graph revision, reusing outputs outside the dependency impact set."""
    current, current_rows = await load_media_graph_spec(session, graph)
    changed = tuple(sorted(key.strip() for key in node_parameter_updates if key.strip()))
    if not changed:
        raise MediaGraphError("media revision requires at least one changed node")
    affected = current.affected_nodes(changed)
    affected_set = set(affected)
    new_nodes: list[MediaNodeSpec] = []
    for node in current.nodes:
        parameters = dict(node.parameters)
        if node.key in node_parameter_updates:
            parameters.update(node_parameter_updates[node.key])
        new_nodes.append(
            MediaNodeSpec(
                key=node.key,
                node_type=node.node_type,
                media_type=node.media_type,
                revision=node.revision + (1 if node.key in affected_set else 0),
                parameters=parameters,
                prompt_metadata=dict(node.prompt_metadata),
                rights_metadata=dict(node.rights_metadata),
                provenance=tuple(node.provenance),
                scene_metadata=dict(node.scene_metadata),
                timeline_metadata=dict(node.timeline_metadata),
            )
        )
    revised = MediaGraphSpec(
        title=current.title,
        asset_kind=current.asset_kind,
        nodes=tuple(new_nodes),
        edges=current.edges,
        output_profile=current.output_profile,
        graph_version=current.graph_version + 1,
        rights_metadata=dict(current.rights_metadata),
        provenance=tuple(
            [
                *current.provenance,
                {
                    "type": "graph-revision",
                    "source_graph_id": graph.id,
                    "changed_nodes": list(changed),
                },
            ]
        ),
    )
    reusable = {
        key: row
        for key, row in current_rows.items()
        if key not in affected_set
        and row.status == "completed"
        and row.storage_key
        and row.checksum
    }
    created = await create_media_graph(
        session,
        scope=MediaGraphScope(
            organization_id=graph.organization_id,
            created_by_id=created_by_id,
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            studio_job_id=graph.studio_job_id,
            studio_asset_id=graph.studio_asset_id,
        ),
        spec=revised,
        idempotency_key=idempotency_key,
        reuse_nodes=reusable,
    )
    created.graph_metadata = {
        **(created.graph_metadata or {}),
        "revision_of_graph_id": graph.id,
        "changed_nodes": list(changed),
        "affected_nodes": list(affected),
        "reused_nodes": sorted(reusable),
    }
    return created, affected


async def media_graph_snapshot(
    session: AsyncSession, graph: MediaAssetGraph
) -> dict[str, Any]:
    """Return a prompt-free, storage-path-free tenant-safe graph snapshot."""
    nodes = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(MediaAssetNode.graph_id == graph.id)
                .order_by(MediaAssetNode.logical_key, MediaAssetNode.revision)
            )
        ).all()
    )
    edges = list(
        (
            await session.scalars(
                select(MediaAssetEdge)
                .where(MediaAssetEdge.graph_id == graph.id)
                .order_by(MediaAssetEdge.ordinal, MediaAssetEdge.id)
            )
        ).all()
    )
    steps = list(
        (
            await session.scalars(
                select(MediaRenderStep)
                .where(MediaRenderStep.graph_id == graph.id)
                .order_by(MediaRenderStep.step_key)
            )
        ).all()
    )
    key_by_id = {node.id: node.logical_key for node in nodes}
    return {
        "id": graph.id,
        "organization_id": graph.organization_id,
        "workspace_id": graph.workspace_id,
        "project_id": graph.project_id,
        "studio_job_id": graph.studio_job_id,
        "studio_asset_id": graph.studio_asset_id,
        "title": graph.title,
        "asset_kind": graph.asset_kind,
        "output_profile": graph.output_profile,
        "status": graph.status,
        "graph_version": graph.graph_version,
        "graph_checksum": graph.graph_checksum,
        "rights_metadata": graph.rights_metadata,
        "provenance": graph.provenance,
        "metadata": graph.graph_metadata,
        "nodes": [
            {
                "id": node.id,
                "logical_key": node.logical_key,
                "revision": node.revision,
                "node_type": node.node_type,
                "media_type": node.media_type,
                "status": node.status,
                "storage_backend": node.storage_backend,
                "checksum": node.checksum,
                "size_bytes": node.size_bytes,
                "rights_metadata": node.rights_metadata,
                "provenance": node.provenance,
                "scene_metadata": node.scene_metadata,
                "timeline_metadata": node.timeline_metadata,
            }
            for node in nodes
        ],
        "edges": [
            {
                "parent": key_by_id.get(edge.parent_node_id),
                "child": key_by_id.get(edge.child_node_id),
                "dependency_type": edge.dependency_type,
                "ordinal": edge.ordinal,
            }
            for edge in edges
        ],
        "render_steps": [
            {
                "id": step.id,
                "step_key": step.step_key,
                "operation": step.operation,
                "output_profile": step.output_profile,
                "engine": step.engine,
                "engine_version": step.engine_version,
                "hardware_adapter": step.hardware_adapter,
                "status": step.status,
                "attempts": step.attempts,
                "max_attempts": step.max_attempts,
                "fencing_token": step.fencing_token,
                "output_checksum": step.output_checksum,
                "command_hash": step.command_hash,
                "error_code": step.error_code,
            }
            for step in steps
        ],
    }
