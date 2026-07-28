from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class SettlementStatus(str, Enum):
    PENDING = "pending"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    VOIDED = "voided"


@dataclass(slots=True)
class SessionSettlement:
    settlement_id: str
    booking_id: str
    owner_id: str
    user_id: str
    currency: str
    gross_amount: Decimal
    platform_fee: Decimal
    staff_amount: Decimal
    status: SettlementStatus = SettlementStatus.PENDING
    provider_reference: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def validate(self) -> None:
        if self.gross_amount < 0 or self.platform_fee < 0 or self.staff_amount < 0:
            raise ValueError("settlement amounts must be non-negative")
        if self.platform_fee + self.staff_amount != self.gross_amount:
            raise ValueError("settlement split must equal gross amount")


class SessionSettlementService:
    def __init__(self) -> None:
        self._settlements: dict[str, SessionSettlement] = {}

    def create(self, settlement: SessionSettlement) -> SessionSettlement:
        if settlement.settlement_id in self._settlements:
            raise ValueError(f"duplicate settlement: {settlement.settlement_id}")
        settlement.validate()
        self._settlements[settlement.settlement_id] = settlement
        return settlement

    def capture(self, settlement_id: str, owner_id: str, provider_reference: str) -> SessionSettlement:
        settlement = self._require_owner(settlement_id, owner_id)
        if settlement.status is not SettlementStatus.PENDING:
            raise RuntimeError("only pending settlements can be captured")
        settlement.status = SettlementStatus.CAPTURED
        settlement.provider_reference = provider_reference
        settlement.updated_at = datetime.now(timezone.utc)
        return settlement

    def refund(self, settlement_id: str, owner_id: str) -> SessionSettlement:
        settlement = self._require_owner(settlement_id, owner_id)
        if settlement.status is not SettlementStatus.CAPTURED:
            raise RuntimeError("only captured settlements can be refunded")
        settlement.status = SettlementStatus.REFUNDED
        settlement.updated_at = datetime.now(timezone.utc)
        return settlement

    def void(self, settlement_id: str, owner_id: str) -> SessionSettlement:
        settlement = self._require_owner(settlement_id, owner_id)
        if settlement.status is not SettlementStatus.PENDING:
            raise RuntimeError("only pending settlements can be voided")
        settlement.status = SettlementStatus.VOIDED
        settlement.updated_at = datetime.now(timezone.utc)
        return settlement

    def _require_owner(self, settlement_id: str, owner_id: str) -> SessionSettlement:
        settlement = self._settlements[settlement_id]
        if settlement.owner_id != owner_id:
            raise PermissionError("settlement is not owned by this owner")
        return settlement
