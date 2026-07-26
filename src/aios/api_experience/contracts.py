from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class APIMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass(frozen=True)
class APIContract:
    contract_id: str
    version: str
    method: APIMethod
    path: str
    required_capabilities: frozenset[str] = frozenset()
    deprecated: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.contract_id.strip() or not self.version.strip():
            raise ValueError("contract_id and version are required")
        if not self.path.startswith("/"):
            raise ValueError("API path must start with /")


@dataclass(frozen=True)
class APIResponse:
    status_code: int
    body: dict[str, object]
    headers: dict[str, str] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def successful(self) -> bool:
        return 200 <= self.status_code < 400
