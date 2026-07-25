from __future__ import annotations

from .models import Credential
from .secrets import SecretsVault


class CredentialsManager:
    def __init__(self, vault: SecretsVault) -> None:
        self._vault = vault
        self._records: dict[str, Credential] = {}

    def register(self, name: str, credential: Credential, *, replace: bool = False) -> None:
        if name in self._records and not replace:
            raise ValueError(f"credential already registered: {name}")
        stored = credential
        if credential.token:
            self._vault.put(f"credentials/{name}/token", credential.token)
        if credential.password:
            self._vault.put(f"credentials/{name}/password", credential.password)
        if credential.private_key:
            self._vault.put(f"credentials/{name}/private_key", credential.private_key)
        stored = Credential(username=credential.username, metadata=dict(credential.metadata))
        self._records[name] = stored

    def resolve(self, name: str) -> Credential:
        try:
            record = self._records[name]
        except KeyError as exc:
            raise KeyError(f"unknown credential: {name}") from exc

        def optional(path: str) -> str | None:
            try:
                return self._vault.get(path)
            except KeyError:
                return None

        return Credential(
            username=record.username,
            token=optional(f"credentials/{name}/token"),
            password=optional(f"credentials/{name}/password"),
            private_key=optional(f"credentials/{name}/private_key"),
            metadata=dict(record.metadata),
        )

    def redacted(self, name: str) -> dict:
        return self.resolve(name).redacted()

    def remove(self, name: str) -> None:
        self._records.pop(name, None)
        for suffix in ("token", "password", "private_key"):
            self._vault.delete(f"credentials/{name}/{suffix}")
