from __future__ import annotations

from pathlib import Path

import pytest

from app.db.base import Base
from app.db import models as _models  # noqa: F401
from app.services.media_orchestrator import (
    FFMPEG_TARGET_VERSION,
    OUTPUT_PROFILES,
    MediaEdgeSpec,
    MediaGraphError,
    MediaGraphSpec,
    MediaNodeSpec,
    output_profile,
)
from app.services.media_storage import LocalMediaObjectStore, MediaStorageError


def _video_graph() -> MediaGraphSpec:
    nodes = (
        MediaNodeSpec("scene-a", "scene", media_type="video/mp4", scene_metadata={"index": 1}),
        MediaNodeSpec("scene-b", "scene", media_type="video/mp4", scene_metadata={"index": 2}),
        MediaNodeSpec("music", "audio", media_type="audio/wav"),
        MediaNodeSpec("assembly", "assembly", media_type="video/mp4"),
        MediaNodeSpec("final", "output", media_type="video/mp4"),
    )
    edges = (
        MediaEdgeSpec("scene-a", "assembly", ordinal=0),
        MediaEdgeSpec("scene-b", "assembly", ordinal=1),
        MediaEdgeSpec("music", "assembly", dependency_type="audio", ordinal=2),
        MediaEdgeSpec("assembly", "final", dependency_type="render"),
    )
    return MediaGraphSpec(
        title="Phase 36D real media graph",
        asset_kind="video",
        nodes=nodes,
        edges=edges,
        output_profile="video-mp4-h264",
        rights_metadata={"status": "owner-supplied"},
        provenance=({"source": "phase36d-test", "type": "synthetic"},),
    )


def test_media_graph_is_deterministic_acyclic_and_partial_revision_is_bounded() -> None:
    graph = _video_graph()
    assert graph.topological_order[-1] == "final"
    assert len(graph.checksum) == 64
    assert graph.checksum == _video_graph().checksum
    assert graph.affected_nodes(["scene-a"]) == ("scene-a", "assembly", "final")
    assert "scene-b" not in graph.affected_nodes(["scene-a"])
    assert "music" not in graph.affected_nodes(["scene-a"])


def test_media_graph_rejects_cycle_and_unknown_profile() -> None:
    nodes = (MediaNodeSpec("a", "scene"), MediaNodeSpec("b", "assembly"))
    with pytest.raises(MediaGraphError, match="acyclic"):
        MediaGraphSpec(
            title="cycle",
            asset_kind="video",
            nodes=nodes,
            edges=(MediaEdgeSpec("a", "b"), MediaEdgeSpec("b", "a")),
            output_profile="video-mp4-h264",
        )
    with pytest.raises(MediaGraphError, match="profile"):
        MediaGraphSpec(
            title="bad profile",
            asset_kind="video",
            nodes=nodes,
            edges=(MediaEdgeSpec("a", "b"),),
            output_profile="missing",
        )


def test_output_profile_registry_targets_ffmpeg_9_and_real_formats() -> None:
    assert FFMPEG_TARGET_VERSION == "9.0"
    assert {"video-mp4-h264", "video-webm-av1", "audio-wav-pcm", "image-png-lossless"} <= set(OUTPUT_PROFILES)
    assert output_profile("video-mp4-h264").media_type == "video/mp4"
    assert output_profile("video-webm-av1").video_codec == "libsvtav1"


def test_phase36d_schema_contract_is_durable_and_tenant_scoped() -> None:
    graphs = Base.metadata.tables["media_asset_graphs"]
    nodes = Base.metadata.tables["media_asset_nodes"]
    edges = Base.metadata.tables["media_asset_edges"]
    steps = Base.metadata.tables["media_render_steps"]
    assert {"organization_id", "project_id", "idempotency_key", "graph_checksum", "rights_metadata", "provenance"} <= set(graphs.c.keys())
    assert {"graph_id", "organization_id", "logical_key", "revision", "checksum", "scene_metadata", "timeline_metadata", "provenance"} <= set(nodes.c.keys())
    assert {"graph_id", "parent_node_id", "child_node_id", "dependency_type", "ordinal"} <= set(edges.c.keys())
    assert {"graph_id", "target_node_id", "operation", "engine_version", "hardware_adapter", "input_checksums", "output_checksum", "idempotency_key"} <= set(steps.c.keys())


def test_local_media_storage_is_private_atomic_and_path_safe(tmp_path: Path, monkeypatch) -> None:
    from app.services import media_storage

    monkeypatch.setattr(media_storage.settings, "MEDIA_MAX_OBJECT_BYTES", 1024 * 1024)
    store = LocalMediaObjectStore(tmp_path / "media")
    body = b"real-media-bytes"
    stored = store.put_bytes("org/project/scene-01.bin", body, "application/octet-stream")
    assert stored.backend == "local"
    assert stored.size_bytes == len(body)
    assert len(stored.sha256) == 64
    assert store.get_bytes(stored.key, max_bytes=1024) == body
    with pytest.raises(MediaStorageError, match="invalid|escapes"):
        store.put_bytes("../escape.bin", b"x", "application/octet-stream")
    store.delete(stored.key)
    with pytest.raises(MediaStorageError, match="unavailable"):
        store.get_bytes(stored.key, max_bytes=1024)
