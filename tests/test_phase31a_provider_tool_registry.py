from __future__ import annotations

from aios.providers.adapters.catalog import default_providers
from aios.providers.tool_catalog import (
    THREE_D_PROVIDER_RECORDS,
    ToolActivation,
    local_tool_catalog,
    provider_activation,
)


def test_3d_generation_providers_are_in_default_catalog() -> None:
    providers = {provider.name: provider for provider in default_providers()}
    assert {"tripo3d", "meshy"}.issubset(providers)
    assert "3d-asset-generation" in providers["tripo3d"].capabilities()[0].tasks
    assert "3d-asset-generation" in providers["meshy"].capabilities()[0].tasks


def test_3d_provider_activation_is_truthful_without_credentials() -> None:
    for record in THREE_D_PROVIDER_RECORDS:
        result = provider_activation(record.provider_id, frozenset())
        assert result.activation is ToolActivation.UNCONFIGURED
        assert result.credential_env


def test_3d_provider_activation_becomes_ready_only_with_matching_credential_boundary() -> None:
    tripo = provider_activation("tripo3d", frozenset({"TRIPO_API_KEY"}))
    meshy = provider_activation("meshy", frozenset({"MESHY_API_KEY"}))
    assert tripo.activation is ToolActivation.READY
    assert meshy.activation is ToolActivation.READY


def test_local_tool_catalog_never_fakes_blender_or_gltf_transform_readiness() -> None:
    tools = {tool.tool_id: tool for tool in local_tool_catalog({"blender": "/opt/bin/blender", "gltf-transform": "/opt/bin/gltf-transform"})}
    assert tools["blender"].activation is ToolActivation.READY
    assert tools["gltf-transform"].activation is ToolActivation.READY
    assert "headless-automation" in tools["blender"].capabilities
    assert "meshopt" in tools["gltf-transform"].capabilities


def test_runtime_supported_provider_catalog_contains_3d_providers() -> None:
    from pathlib import Path
    text = Path("web-dashboard/backend/app/core/ai_runtime.py").read_text(encoding="utf-8")
    assert '"tripo3d"' in text
    assert '"meshy"' in text
