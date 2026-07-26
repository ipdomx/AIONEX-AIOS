from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
import uuid

from .auth import DashboardTokenService
from .contracts import DashboardContractRegistry


@dataclass(frozen=True)
class DashboardRequest:
    contract_id: str
    operation: str
    token: str
    payload: dict[str, object] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class DashboardResponse:
    correlation_id: str
    success: bool
    data: dict[str, object]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Handler = Callable[[DashboardRequest], dict[str, object]]


class DashboardIntegrationGateway:
    def __init__(
        self,
        contracts: DashboardContractRegistry,
        tokens: DashboardTokenService,
    ) -> None:
        self.contracts = contracts
        self.tokens = tokens
        self._handlers: dict[tuple[str, str], Handler] = {}

    def register_handler(self, contract_id: str, operation: str, handler: Handler) -> None:
        self.contracts.get(contract_id)
        if not operation.strip():
            raise ValueError("operation is required")
        self._handlers[(contract_id, operation)] = handler

    def dispatch(self, request: DashboardRequest) -> DashboardResponse:
        contract = self.contracts.get(request.contract_id)
        required = next(iter(contract.capabilities), None)
        self.tokens.validate(request.token, required)
        try:
            handler = self._handlers[(request.contract_id, request.operation)]
        except KeyError as exc:
            raise LookupError(
                f"dashboard operation not found: {request.contract_id}/{request.operation}"
            ) from exc
        return DashboardResponse(
            correlation_id=request.correlation_id,
            success=True,
            data=dict(handler(request)),
        )
