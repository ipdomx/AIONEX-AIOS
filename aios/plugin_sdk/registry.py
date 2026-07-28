from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .models import PluginManifest, PluginPackage, PluginState


class PluginRegistry:
    def __init__(self) -> None:
        self._packages: dict[str, PluginPackage] = {}

    def register(self, package: PluginPackage) -> PluginPackage:
        plugin_id = package.manifest.plugin_id
        if plugin_id in self._packages:
            raise ValueError(f"plugin already registered: {plugin_id}")
        self._packages[plugin_id] = package
        return package

    def get(self, plugin_id: str) -> PluginPackage:
        try:
            return self._packages[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    def submit(self, plugin_id: str, owner_id: str) -> PluginPackage:
        package = self._require_owner(plugin_id, owner_id)
        if package.manifest.state is not PluginState.DRAFT:
            raise RuntimeError("only draft plugins can be submitted")
        package.manifest = replace(
            package.manifest,
            state=PluginState.SUBMITTED,
            updated_at=datetime.now(timezone.utc),
        )
        return package

    def approve(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        if package.manifest.state is not PluginState.SUBMITTED:
            raise RuntimeError("only submitted plugins can be approved")
        package.manifest = replace(
            package.manifest,
            state=PluginState.APPROVED,
            updated_at=datetime.now(timezone.utc),
        )
        return package

    def publish(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        if package.manifest.state is not PluginState.APPROVED:
            raise RuntimeError("only approved plugins can be published")
        package.manifest = replace(
            package.manifest,
            state=PluginState.PUBLISHED,
            updated_at=datetime.now(timezone.utc),
        )
        return package

    def suspend(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        if package.manifest.state not in {PluginState.APPROVED, PluginState.PUBLISHED}:
            raise RuntimeError("plugin cannot be suspended from current state")
        package.manifest = replace(
            package.manifest,
            state=PluginState.SUSPENDED,
            updated_at=datetime.now(timezone.utc),
        )
        return package

    def list_published(self) -> list[PluginPackage]:
        return sorted(
            (p for p in self._packages.values() if p.manifest.state is PluginState.PUBLISHED),
            key=lambda p: (p.manifest.name.lower(), p.manifest.version),
        )

    def _require_owner(self, plugin_id: str, owner_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        if package.manifest.owner_id != owner_id:
            raise PermissionError("plugin is not owned by this owner")
        return package
