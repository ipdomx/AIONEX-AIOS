from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PurchaseState(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    VOID = "void"


@dataclass(slots=True)
class PluginPurchase:
    purchase_id: str
    plugin_id: str
    buyer_owner_id: str
    seller_owner_id: str
    amount_cents: int
    currency: str = "EUR"
    platform_fee_cents: int = 0
    state: PurchaseState = PurchaseState.PENDING

    @property
    def seller_net_cents(self) -> int:
        return self.amount_cents - self.platform_fee_cents


class PluginBillingService:
    def __init__(self) -> None:
        self._purchases: dict[str, PluginPurchase] = {}

    def create(self, purchase: PluginPurchase) -> PluginPurchase:
        if purchase.purchase_id in self._purchases:
            raise ValueError(f"duplicate purchase: {purchase.purchase_id}")
        if purchase.amount_cents < 0 or purchase.platform_fee_cents < 0:
            raise ValueError("amounts must be non-negative")
        if purchase.platform_fee_cents > purchase.amount_cents:
            raise ValueError("platform fee cannot exceed purchase amount")
        self._purchases[purchase.purchase_id] = purchase
        return purchase

    def mark_paid(self, purchase_id: str) -> PluginPurchase:
        purchase = self._purchases[purchase_id]
        if purchase.state is not PurchaseState.PENDING:
            raise RuntimeError("only pending purchases can be paid")
        purchase.state = PurchaseState.PAID
        return purchase

    def refund(self, purchase_id: str) -> PluginPurchase:
        purchase = self._purchases[purchase_id]
        if purchase.state is not PurchaseState.PAID:
            raise RuntimeError("only paid purchases can be refunded")
        purchase.state = PurchaseState.REFUNDED
        return purchase

    def void(self, purchase_id: str) -> PluginPurchase:
        purchase = self._purchases[purchase_id]
        if purchase.state is not PurchaseState.PENDING:
            raise RuntimeError("only pending purchases can be voided")
        purchase.state = PurchaseState.VOID
        return purchase
