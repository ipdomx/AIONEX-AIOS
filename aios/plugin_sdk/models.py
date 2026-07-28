from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class PluginState(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    owner_id: str
    name: str
    version: str
    description: str
    entrypoint: str
    permissions: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)
    state: PluginState = PluginState.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class PluginPackage:
    manifest: PluginManifest
    checksum: str
    artifact_uri: str
    signature: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
