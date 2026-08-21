"""Phase 36D provider-neutral creative media DAG and render planning contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

MEDIA_GRAPH_SCHEMA_VERSION = "36D.1"
FFMPEG_TARGET_VERSION = "9.0"
SHARP_TARGET_VERSION = "0.35.3"


class MediaGraphError(ValueError):
    """A creative media graph is malformed or unsafe to execute."""


@dataclass(frozen=True, slots=True)
class MediaOutputProfile:
    profile_id: str
    asset_kind: str
    extension: str
    media_type: str
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    pixel_format: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    bitrate_kbps: int | None = None
    ffmpeg_args: tuple[str, ...] = ()


OUTPUT_PROFILES: dict[str, MediaOutputProfile] = {
    "image-png-lossless": MediaOutputProfile(
        profile_id="image-png-lossless",
        asset_kind="image",
        extension="png",
        media_type="image/png",
        video_codec="png",
        ffmpeg_args=("-frames:v", "1"),
    ),
    "audio-wav-pcm": MediaOutputProfile(
        profile_id="audio-wav-pcm",
        asset_kind="audio",
        extension="wav",
        media_type="audio/wav",
        container="wav",
        audio_codec="pcm_s16le",
        sample_rate_hz=48_000,
        channels=2,
    ),
    "audio-wav-pcm-mono": MediaOutputProfile(
        profile_id="audio-wav-pcm-mono",
        asset_kind="audio",
        extension="wav",
        media_type="audio/wav",
        container="wav",
        audio_codec="pcm_s16le",
        sample_rate_hz=48_000,
        channels=1,
    ),
    "audio-m4a-aac": MediaOutputProfile(
        profile_id="audio-m4a-aac",
        asset_kind="audio",
        extension="m4a",
        media_type="audio/mp4",
        container="mp4",
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=192,
        ffmpeg_args=("-movflags", "+faststart"),
    ),
    "audio-webm-opus": MediaOutputProfile(
        profile_id="audio-webm-opus",
        asset_kind="audio",
        extension="webm",
        media_type="audio/webm",
        container="webm",
        audio_codec="libopus",
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=128,
    ),
    "video-mp4-h264": MediaOutputProfile(
        profile_id="video-mp4-h264",
        asset_kind="video",
        extension="mp4",
        media_type="video/mp4",
        container="mp4",
        video_codec="libx264",
        audio_codec="aac",
        pixel_format="yuv420p",
        ffmpeg_args=("-movflags", "+faststart"),
    ),
    "video-webm-av1": MediaOutputProfile(
        profile_id="video-webm-av1",
        asset_kind="video",
        extension="webm",
        media_type="video/webm",
        container="webm",
        video_codec="libsvtav1",
        audio_codec="libopus",
        pixel_format="yuv420p",
    ),
}


@dataclass(frozen=True, slots=True)
class MediaNodeSpec:
    key: str
    node_type: str
    media_type: str | None = None
    revision: int = 1
    parameters: dict[str, Any] = field(default_factory=dict)
    prompt_metadata: dict[str, Any] = field(default_factory=dict)
    rights_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: tuple[dict[str, Any], ...] = ()
    scene_metadata: dict[str, Any] = field(default_factory=dict)
    timeline_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        key = self.key.strip()
        node_type = self.node_type.strip().lower()
        if not key or len(key) > 160:
            raise MediaGraphError("media node key is invalid")
        if not node_type or len(node_type) > 40:
            raise MediaGraphError("media node type is invalid")
        if self.revision < 1:
            raise MediaGraphError("media node revision must be positive")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "node_type", node_type)

    def canonical(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "node_type": self.node_type,
            "media_type": self.media_type,
            "revision": self.revision,
            "parameters": self.parameters,
            "prompt_metadata": self.prompt_metadata,
            "rights_metadata": self.rights_metadata,
            "provenance": list(self.provenance),
            "scene_metadata": self.scene_metadata,
            "timeline_metadata": self.timeline_metadata,
        }

    @property
    def content_fingerprint(self) -> str:
        payload = json.dumps(
            self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class MediaEdgeSpec:
    parent: str
    child: str
    dependency_type: str = "input"
    ordinal: int = 0

    def __post_init__(self) -> None:
        parent = self.parent.strip()
        child = self.child.strip()
        dependency_type = self.dependency_type.strip().lower()
        if not parent or not child or parent == child:
            raise MediaGraphError("media edge endpoints are invalid")
        if not dependency_type or len(dependency_type) > 40:
            raise MediaGraphError("media dependency type is invalid")
        if self.ordinal < 0:
            raise MediaGraphError("media dependency ordinal cannot be negative")
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "child", child)
        object.__setattr__(self, "dependency_type", dependency_type)


@dataclass(frozen=True, slots=True)
class MediaGraphSpec:
    title: str
    asset_kind: str
    nodes: tuple[MediaNodeSpec, ...]
    edges: tuple[MediaEdgeSpec, ...]
    output_profile: str
    graph_version: int = 1
    rights_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        title = self.title.strip()
        asset_kind = self.asset_kind.strip().lower()
        if not title:
            raise MediaGraphError("media graph title is required")
        if asset_kind not in {"image", "audio", "video", "animation", "3d", "mixed"}:
            raise MediaGraphError("media graph asset kind is unsupported")
        if self.graph_version < 1:
            raise MediaGraphError("media graph version must be positive")
        if self.output_profile not in OUTPUT_PROFILES:
            raise MediaGraphError("media output profile is unknown")
        if not self.nodes:
            raise MediaGraphError("media graph requires at least one node")
        keys = [node.key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise MediaGraphError("media graph node keys must be unique")
        key_set = set(keys)
        for edge in self.edges:
            if edge.parent not in key_set or edge.child not in key_set:
                raise MediaGraphError("media graph edge references an unknown node")
        _topological_order(self.nodes, self.edges)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "asset_kind", asset_kind)

    @property
    def canonical(self) -> dict[str, Any]:
        return {
            "schema": MEDIA_GRAPH_SCHEMA_VERSION,
            "title": self.title,
            "asset_kind": self.asset_kind,
            "graph_version": self.graph_version,
            "output_profile": self.output_profile,
            "rights_metadata": self.rights_metadata,
            "provenance": list(self.provenance),
            "nodes": [node.canonical() for node in sorted(self.nodes, key=lambda item: item.key)],
            "edges": [
                {
                    "parent": edge.parent,
                    "child": edge.child,
                    "dependency_type": edge.dependency_type,
                    "ordinal": edge.ordinal,
                }
                for edge in sorted(
                    self.edges,
                    key=lambda item: (item.parent, item.child, item.dependency_type, item.ordinal),
                )
            ],
        }

    @property
    def checksum(self) -> str:
        payload = json.dumps(
            self.canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def topological_order(self) -> tuple[str, ...]:
        return _topological_order(self.nodes, self.edges)

    def affected_nodes(self, changed_keys: Iterable[str]) -> tuple[str, ...]:
        changed = {item.strip() for item in changed_keys if item.strip()}
        known = {node.key for node in self.nodes}
        if not changed <= known:
            raise MediaGraphError("changed media node is not in the graph")
        children: dict[str, set[str]] = {key: set() for key in known}
        for edge in self.edges:
            children[edge.parent].add(edge.child)
        affected = set(changed)
        queue = list(changed)
        while queue:
            parent = queue.pop(0)
            for child in sorted(children[parent]):
                if child not in affected:
                    affected.add(child)
                    queue.append(child)
        order = self.topological_order
        return tuple(key for key in order if key in affected)


def _topological_order(
    nodes: tuple[MediaNodeSpec, ...], edges: tuple[MediaEdgeSpec, ...]
) -> tuple[str, ...]:
    keys = {node.key for node in nodes}
    incoming = {key: 0 for key in keys}
    children: dict[str, set[str]] = {key: set() for key in keys}
    for edge in edges:
        if edge.parent not in keys or edge.child not in keys:
            raise MediaGraphError("media graph edge references an unknown node")
        if edge.child not in children[edge.parent]:
            children[edge.parent].add(edge.child)
            incoming[edge.child] += 1
    ready = sorted(key for key, count in incoming.items() if count == 0)
    result: list[str] = []
    while ready:
        key = ready.pop(0)
        result.append(key)
        for child in sorted(children[key]):
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
                ready.sort()
    if len(result) != len(keys):
        raise MediaGraphError("media graph must be acyclic")
    return tuple(result)



def media_graph_from_universal_storyboard(
    storyboard: dict[str, Any],
    *,
    output_profile_id: str = "video-mp4-h264",
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
) -> MediaGraphSpec:
    """Convert the Universal Builder editable storyboard into an executable media DAG."""
    if storyboard.get("format") != "editable-storyboard":
        raise MediaGraphError("universal media storyboard format is unsupported")
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 100:
        raise MediaGraphError("universal media storyboard scenes are invalid")
    profile = output_profile(output_profile_id)
    if profile.asset_kind != "video":
        raise MediaGraphError("universal media storyboard requires a video output profile")
    if width < 64 or width > 7680 or height < 64 or height > 4320 or width % 2 or height % 2:
        raise MediaGraphError("universal media storyboard dimensions are invalid")
    if fps < 1 or fps > 120:
        raise MediaGraphError("universal media storyboard frame rate is invalid")

    nodes: list[MediaNodeSpec] = []
    edges: list[MediaEdgeSpec] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(scenes, start=1):
        if not isinstance(raw, dict):
            raise MediaGraphError("universal media storyboard scene is invalid")
        scene_id = str(raw.get("id") or "").strip()
        if not scene_id or scene_id in seen_ids:
            raise MediaGraphError("universal media storyboard scene ids must be unique")
        seen_ids.add(scene_id)
        raw_duration = raw.get("duration_seconds")
        if raw_duration is None:
            raise MediaGraphError("universal media storyboard duration is invalid")
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            raise MediaGraphError("universal media storyboard duration is invalid") from None
        if not 0.1 <= duration <= 60.0:
            raise MediaGraphError("universal media storyboard duration is outside the allowed range")
        digest = hashlib.sha256(scene_id.encode("utf-8")).hexdigest()
        safe = "-".join(filter(None, "".join(ch.lower() if ch.isalnum() else "-" for ch in scene_id).split("-")))[:80]
        key = f"scene-{index:03d}-{safe or digest[:12]}"
        purpose = str(raw.get("purpose") or "scene").strip()[:160]
        nodes.append(
            MediaNodeSpec(
                key=key,
                node_type="scene",
                media_type=profile.media_type,
                parameters={
                    "operation": "render_scene",
                    "output_profile": output_profile_id,
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "duration_seconds": duration,
                    "color": f"#{digest[:6]}",
                    "tone_hz": 220 + (int(digest[6:10], 16) % 660),
                    "hardware_adapter": "software",
                },
                prompt_metadata={"purpose": purpose},
                provenance=(
                    {
                        "type": "universal-builder-storyboard-scene",
                        "storyboard_scene_id": scene_id,
                        "storyboard_schema_version": storyboard.get("schema_version"),
                    },
                ),
                scene_metadata={"id": scene_id, "purpose": purpose, "index": index},
                timeline_metadata={"duration_seconds": duration, "ordinal": index - 1},
            )
        )
        edges.append(MediaEdgeSpec(parent=key, child="assembly", ordinal=index - 1))

    nodes.append(
        MediaNodeSpec(
            key="assembly",
            node_type="assembly",
            media_type=profile.media_type,
            parameters={
                "operation": "assemble",
                "output_profile": output_profile_id,
                "hardware_adapter": "software",
            },
            provenance=(
                {
                    "type": "universal-builder-storyboard-assembly",
                    "project": storyboard.get("project"),
                },
            ),
            timeline_metadata={"scene_count": len(scenes)},
        )
    )
    return MediaGraphSpec(
        title=str(storyboard.get("title") or storyboard.get("project") or "Universal media project")[:240],
        asset_kind="video",
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_profile=output_profile_id,
        provenance=(
            {
                "type": "universal-builder-media-target",
                "project": storyboard.get("project"),
                "schema_version": storyboard.get("schema_version"),
            },
        ),
    )


def output_profile(profile_id: str) -> MediaOutputProfile:
    try:
        return OUTPUT_PROFILES[profile_id]
    except KeyError as exc:
        raise MediaGraphError("media output profile is unknown") from exc
