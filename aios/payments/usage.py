from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict

from .wallet import Wallet, WalletEntry, WalletService


@dataclass(frozen=True, slots=True)
class UsageRecord:
    idempotency_key: str
    owner_id: str
    metric: str
    units: Decimal
    unit_price: Decimal
    amount: Decimal
    wallet_entry_id: str


class UsageBillingService:
    """Meters usage and prevents duplicate wallet charges."""

    def __init__(self, wallet_service: WalletService) -> None:
        self._wallet_service = wallet_service
        self._records: Dict[str, UsageRecord] = {}

    def charge(
        self,
        *,
        wallet: Wallet,
        metric: str,
        units: Decimal,
        unit_price: Decimal,
        idempotency_key: str,
    ) -> tuple[UsageRecord, WalletEntry]:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = self._records.get(idempotency_key)
        if existing:
            entry = next(item for item in wallet.entries if item.id == existing.wallet_entry_id)
            return existing, entry
        reference = f"usage:{metric}:{idempotency_key}"
        entry = self._wallet_service.charge_usage(
            wallet=wallet,
            units=units,
            unit_price=unit_price,
            reference=reference,
        )
        record = UsageRecord(
            idempotency_key=idempotency_key,
            owner_id=wallet.owner_id,
            metric=metric,
            units=units,
            unit_price=unit_price,
            amount=units * unit_price,
            wallet_entry_id=entry.id,
        )
        self._records[idempotency_key] = record
        return record, entry
