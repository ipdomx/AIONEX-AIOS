from __future__ import annotations

from typing import Any

from .credentials import CredentialsManager
from .models import ConnectionProfile
from .registry import IntegrationRegistry
from .secrets import SecretsVault


class ConnectionManager:
    def __init__(self, registry: IntegrationRegistry, credentials: CredentialsManager,
                 vault: SecretsVault) -> None:
        self.registry = registry
        self.credentials = credentials
        self.vault = vault
        self._profiles: dict[str, ConnectionProfile] = {}

    def register_profile(self, profile: ConnectionProfile, *, replace: bool = False) -> None:
        if profile.name in self._profiles and not replace:
            raise ValueError(f"connection profile already registered: {profile.name}")
        self.registry.get(profile.integration)
        self._profiles[profile.name] = profile

    def profile(self, name: str) -> ConnectionProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            raise KeyError(f"unknown connection profile: {name}") from exc

    def all_profiles(self) -> tuple[ConnectionProfile, ...]:
        return tuple(self._profiles[name] for name in sorted(self._profiles))

    def _context(self, profile: ConnectionProfile) -> dict[str, Any]:
        context: dict[str, Any] = {"secrets": {}}
        if profile.credential_ref:
            context["credential"] = self.credentials.resolve(profile.credential_ref)
        for alias, reference in profile.secret_refs.items():
            context["secrets"][alias] = self.vault.get(reference)
        return context

    async def connect(self, profile_name: str) -> None:
        profile = self.profile(profile_name)
        await self.registry.get(profile.integration).connect(profile, self._context(profile))

    async def disconnect(self, profile_name: str) -> None:
        profile = self.profile(profile_name)
        await self.registry.get(profile.integration).disconnect()

    async def execute(self, profile_name: str, capability: str,
                      payload: dict[str, Any] | None = None) -> Any:
        profile = self.profile(profile_name)
        return await self.registry.get(profile.integration).execute(capability, payload)
