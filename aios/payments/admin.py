from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Iterable, Protocol


class FinanceSnapshotSource(Protocol):
    def transactions(self) -> Iterable[object]: ...

    def subscriptions(self) -> Iterable[object]: ...

    def invoices(self) -> Iterable[object]: ...

    def refunds(self) -> Iterable[object]: ...


@dataclass(frozen=True)
class FinanceSummary:
    gross_volume: Decimal
    refunded_volume: Decimal
    net_volume: Decimal
    successful_transactions: int
    failed_transactions: int
    active_subscriptions: int
    open_invoices: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["gross_volume"] = str(self.gross_volume)
        payload["refunded_volume"] = str(self.refunded_volume)
        payload["net_volume"] = str(self.net_volume)
        return payload


class FinanceAdminService:
    """Read-only finance reporting surface for the owner dashboard."""

    def __init__(self, source: FinanceSnapshotSource) -> None:
        self._source = source

    @staticmethod
    def _amount(item: object) -> Decimal:
        value = getattr(item, "amount", Decimal("0"))
        if hasattr(value, "amount"):
            value = value.amount
        return Decimal(str(value))

    def summary(self) -> FinanceSummary:
        transactions = list(self._source.transactions())
        subscriptions = list(self._source.subscriptions())
        invoices = list(self._source.invoices())
        refunds = list(self._source.refunds())

        successful = [item for item in transactions if getattr(item, "status", "") in {"succeeded", "paid", "completed"}]
        failed = [item for item in transactions if getattr(item, "status", "") in {"failed", "cancelled", "canceled"}]
        gross = sum((self._amount(item) for item in successful), Decimal("0"))
        refunded = sum((self._amount(item) for item in refunds if getattr(item, "status", "succeeded") in {"succeeded", "completed"}), Decimal("0"))

        return FinanceSummary(
            gross_volume=gross,
            refunded_volume=refunded,
            net_volume=gross - refunded,
            successful_transactions=len(successful),
            failed_transactions=len(failed),
            active_subscriptions=sum(1 for item in subscriptions if getattr(item, "status", "") in {"active", "trialing"}),
            open_invoices=sum(1 for item in invoices if getattr(item, "status", "") in {"draft", "open", "issued", "past_due"}),
        )

    def provider_health(self, registry: object) -> list[dict[str, object]]:
        providers = getattr(registry, "providers", lambda: [])()
        result: list[dict[str, object]] = []
        for provider in providers:
            result.append(
                {
                    "name": getattr(provider, "name", provider.__class__.__name__),
                    "enabled": bool(getattr(provider, "enabled", True)),
                    "supports_webhooks": callable(getattr(provider, "verify_webhook", None)),
                    "supports_refunds": callable(getattr(provider, "refund", None)),
                }
            )
        return result
