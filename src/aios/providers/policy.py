from __future__ import annotations

from dataclasses import dataclass, field

from .models import DataSensitivity, ModelCapability, ModelRequest


@dataclass(slots=True)
class ProviderPolicy:
    blocked_providers: set[str] = field(default_factory=set)
    allowed_by_project: dict[str, set[str]] = field(default_factory=dict)
    external_data_limit: DataSensitivity = DataSensitivity.CONFIDENTIAL

    def allows(self, capability: ModelCapability, request: ModelRequest, project: str | None = None) -> tuple[bool, str]:
        if capability.provider in self.blocked_providers:
            return False, "provider-blocked"
        scoped = self.allowed_by_project.get(project or "")
        if scoped is not None and capability.provider not in scoped:
            return False, "provider-not-allowed-for-project"
        if request.require_local and not capability.local:
            return False, "local-provider-required"
        if request.sensitivity == DataSensitivity.RESTRICTED and not capability.local:
            return False, "restricted-data-must-stay-local"
        if request.require_tools and not capability.supports_tools:
            return False, "tools-required"
        if request.require_vision and not capability.supports_vision:
            return False, "vision-required"
        if request.require_audio and not capability.supports_audio:
            return False, "audio-required"
        return True, "allowed"
