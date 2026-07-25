from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class MinistryState(str, Enum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    DISABLED = 'disabled'

@dataclass(frozen=True)
class MinistryDefinition:
    ministry_id: str
    name: str
    mission: str
    capabilities: tuple[str, ...]
    manager_role: str
    required_contracts: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class MinistryAssignment:
    ministry_id: str
    project_id: str
    worker_ids: tuple[str, ...]
    objective: str
