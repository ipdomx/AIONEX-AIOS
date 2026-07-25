from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

class DeliveryMode(StrEnum):
    AT_MOST_ONCE='at_most_once'
    AT_LEAST_ONCE='at_least_once'

@dataclass(slots=True, frozen=True)
class Event:
    name: str
    payload: dict[str, Any]
    tenant_id: str
    source: str
    contract_version: str='1.0'
    correlation_id: str=field(default_factory=lambda: str(uuid4()))

@dataclass(slots=True, frozen=True)
class Contract:
    name: str
    version: str
    required_fields: tuple[str, ...]
    producer: str
    consumers: tuple[str, ...]

@dataclass(slots=True, frozen=True)
class Capability:
    capability_id: str
    provider: str
    skills: tuple[str, ...]
    languages: tuple[str, ...]=()
    trust_score: float=0.5
    available: bool=True

@dataclass(slots=True, frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...]
    obligations: tuple[str, ...]=()

@dataclass(slots=True)
class WorkflowStep:
    name: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    state: str='pending'
    attempts: int=0
    result: dict[str, Any]=field(default_factory=dict)

@dataclass(slots=True)
class WorkflowRecord:
    workflow_id: str
    tenant_id: str
    name: str
    state: str
    current_step: int
    context: dict[str, Any]
