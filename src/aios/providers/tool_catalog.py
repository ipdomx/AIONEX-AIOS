from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from shutil import which
from typing import Mapping


class ToolActivation(str, Enum):
    READY = "ready"
    UNCONFIGURED = "unconfigured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ToolCapability:
    tool_id: str
    name: str
    category: str
    capabilities: frozenset[str]
    local: bool
    activation: ToolActivation
    reason: str
    executable: str | None = None
    credential_env: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapabilityRecord:
    provider_id: str
    name: str
    category: str
    capabilities: frozenset[str]
    local: bool
    activation: ToolActivation
    reason: str
    credential_env: str | None = None


THREE_D_PROVIDER_RECORDS: tuple[ProviderCapabilityRecord, ...] = (
    ProviderCapabilityRecord(
        provider_id="tripo3d",
        name="Tripo AI 3D",
        category="3d-generation",
        capabilities=frozenset({"text-to-3d", "image-to-3d", "mesh-generation", "3d-asset-generation"}),
        local=False,
        activation=ToolActivation.UNCONFIGURED,
        reason="Requires a configured Tripo API credential before live generation can run.",
        credential_env="TRIPO_API_KEY",
    ),
    ProviderCapabilityRecord(
        provider_id="meshy",
        name="Meshy",
        category="3d-generation",
        capabilities=frozenset({"text-to-3d", "image-to-3d", "texture-generation", "3d-asset-generation"}),
        local=False,
        activation=ToolActivation.UNCONFIGURED,
        reason="Requires a configured Meshy API credential before live generation can run.",
        credential_env="MESHY_API_KEY",
    ),
)


def local_tool_catalog(executable_overrides: Mapping[str, str] | None = None) -> tuple[ToolCapability, ...]:
    overrides = dict(executable_overrides or {})
    blender = overrides.get("blender") or which("blender")
    gltf_transform = overrides.get("gltf-transform") or which("gltf-transform")
    tools = [
        ToolCapability(
            tool_id="blender",
            name="Blender Runtime",
            category="3d-authoring-runtime",
            capabilities=frozenset({
                "mesh-authoring", "mesh-editing", "uv", "materials", "animation", "rendering",
                "gltf-import", "gltf-export", "decimation", "lod-generation", "headless-automation",
            }),
            local=True,
            activation=ToolActivation.READY if blender else ToolActivation.UNAVAILABLE,
            reason="Executable discovered on host." if blender else "Blender executable is not installed on this runtime host.",
            executable=blender,
        ),
        ToolCapability(
            tool_id="gltf-transform",
            name="glTF Transform CLI",
            category="3d-optimization-runtime",
            capabilities=frozenset({"gltf-optimize", "meshopt", "draco", "texture-compression", "inspection"}),
            local=True,
            activation=ToolActivation.READY if gltf_transform else ToolActivation.UNAVAILABLE,
            reason="Executable discovered on host." if gltf_transform else "glTF Transform CLI is not installed on this runtime host.",
            executable=gltf_transform,
        ),
    ]
    return tuple(tools)


def provider_activation(provider_id: str, configured_env: frozenset[str]) -> ProviderCapabilityRecord:
    record = next(item for item in THREE_D_PROVIDER_RECORDS if item.provider_id == provider_id)
    if record.credential_env and record.credential_env in configured_env:
        return ProviderCapabilityRecord(
            provider_id=record.provider_id,
            name=record.name,
            category=record.category,
            capabilities=record.capabilities,
            local=record.local,
            activation=ToolActivation.READY,
            reason="Credential boundary is configured.",
            credential_env=record.credential_env,
        )
    return record
