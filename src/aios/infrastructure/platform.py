from __future__ import annotations

from .config import InfrastructureConfigLoader
from .connections import ConnectionManager
from .credentials import CredentialsManager
from .health import InfrastructureHealthMonitor
from .models import ConnectionProfile
from .registry import IntegrationRegistry
from .secrets import SecretBackend, SecretsVault


class InfrastructurePlatform:
    def __init__(self, master_key: bytes, *, secret_backend: SecretBackend | None = None) -> None:
        self.registry = IntegrationRegistry()
        self.vault = SecretsVault(master_key, secret_backend)
        self.credentials = CredentialsManager(self.vault)
        self.connections = ConnectionManager(self.registry, self.credentials, self.vault)
        self.health = InfrastructureHealthMonitor(self.registry)
        self.config = InfrastructureConfigLoader()

    def load_profiles(self, profiles: tuple[ConnectionProfile, ...], *, replace: bool = False) -> None:
        for profile in profiles:
            self.connections.register_profile(profile, replace=replace)
