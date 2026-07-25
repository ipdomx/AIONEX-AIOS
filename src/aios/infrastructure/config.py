from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ConnectionProfile


class InfrastructureConfigLoader:
    def load_mapping(self, data: dict[str, Any]) -> tuple[ConnectionProfile, ...]:
        profiles = data.get("connections", data)
        if not isinstance(profiles, dict):
            raise ValueError("connections configuration must be an object")
        result: list[ConnectionProfile] = []
        for name, item in profiles.items():
            if not isinstance(item, dict):
                raise ValueError(f"connection {name} must be an object")
            integration = item.get("integration")
            if not integration:
                raise ValueError(f"connection {name} has no integration")
            result.append(ConnectionProfile(
                name=name,
                integration=str(integration),
                endpoint=item.get("endpoint"),
                credential_ref=item.get("credential_ref"),
                secret_refs=dict(item.get("secret_refs", {})),
                options=dict(item.get("options", {})),
                enabled=bool(item.get("enabled", True)),
            ))
        return tuple(result)

    def load_file(self, path: str | Path) -> tuple[ConnectionProfile, ...]:
        source = Path(path)
        if source.suffix.lower() != ".json":
            raise ValueError("phase 8 part 1 supports JSON configuration files")
        return self.load_mapping(json.loads(source.read_text(encoding="utf-8")))
