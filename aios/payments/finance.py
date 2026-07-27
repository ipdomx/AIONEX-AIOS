from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Iterable
from uuid import uuid4


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.currency or len(self.currency) != 3:
            raise ValueError("currency must be an ISO-4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "amount", self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _assert_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError("currency mismatch")

    def __add__(self, other: "Money") -> "Money":
        self._assert_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_currency(other)
        return Money(self.amount - other.amount, self.currency)


@dataclass(frozen=True)
class TaxRate:
    code: str
    percentage: Decimal
    inclusive: bool = False

    def __post_init__(self) -> None:
        if self.percentage < 0 or self.percentage > 100:
            raise ValueError("tax percentage must be between 0 and 100")


@dataclass(frozen=True)
class Coupon:
    code: str
    percent_off: Decimal | None = None
    amount_off: Money | None = None
    max_redemptions: int | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.percent_off is None) == (self.amount_off is None):
            raise ValueError("coupon requires exactly one discount mode")
        if self.percent_off is not None and not (Decimal("0") < self.percent_off <= Decimal("100")):
            raise ValueError("percent_off must be between 0 and 100")


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    quantity: Decimal
    unit_price: Money
    tax_rate: TaxRate | None = None

    @property
    def subtotal(self) -> Money:
        return Money(self.unit_price.amount * self.quantity, self.unit_price.currency)


@dataclass
class Invoice:
    customer_id: str
    lines: list[InvoiceLine]
    id: str = field(default_factory=lambda: str(uuid4()))
    status: InvoiceStatus = InvoiceStatus.DRAFT
    coupon: Coupon | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    paid_at: datetime | None = None

    def _currency(self) -> str:
        if not self.lines:
            raise ValueError("invoice requires at least one line")
        currencies = {line.unit_price.currency for line in self.lines}
        if len(currencies) != 1:
            raise ValueError("invoice lines must use one currency")
        return next(iter(currencies))

    @property
    def subtotal(self) -> Money:
        currency = self._currency()
        return Money(sum((line.subtotal.amount for line in self.lines), Decimal("0")), currency)

    @property
    def discount(self) -> Money:
        subtotal = self.subtotal
        if self.coupon is None:
            return Money(Decimal("0"), subtotal.currency)
        if self.coupon.percent_off is not None:
            return Money(subtotal.amount * self.coupon.percent_off / Decimal("100"), subtotal.currency)
        assert self.coupon.amount_off is not None
        if self.coupon.amount_off.currency != subtotal.currency:
            raise ValueError("coupon currency mismatch")
        return Money(min(subtotal.amount, self.coupon.amount_off.amount), subtotal.currency)

    @property
    def taxable_subtotal(self) -> Money:
        return self.subtotal - self.discount

    @property
    def tax(self) -> Money:
        currency = self._currency()
        raw_subtotal = self.subtotal.amount
        discount_ratio = Decimal("0") if raw_subtotal == 0 else self.discount.amount / raw_subtotal
        total_tax = Decimal("0")
        for line in self.lines:
            if line.tax_rate is None:
                continue
            discounted = line.subtotal.amount * (Decimal("1") - discount_ratio)
            rate = line.tax_rate.percentage / Decimal("100")
            if line.tax_rate.inclusive:
                total_tax += discounted - (discounted / (Decimal("1") + rate))
            else:
                total_tax += discounted * rate
        return Money(total_tax, currency)

    @property
    def total(self) -> Money:
        exclusive_tax = Decimal("0")
        raw_subtotal = self.subtotal.amount
        discount_ratio = Decimal("0") if raw_subtotal == 0 else self.discount.amount / raw_subtotal
        for line in self.lines:
            if line.tax_rate is None or line.tax_rate.inclusive:
                continue
            discounted = line.subtotal.amount * (Decimal("1") - discount_ratio)
            exclusive_tax += discounted * line.tax_rate.percentage / Decimal("100")
        return Money(self.taxable_subtotal.amount + exclusive_tax, self._currency())

    def open(self) -> None:
        if self.status is not InvoiceStatus.DRAFT:
            raise ValueError("only draft invoices can be opened")
        self.status = InvoiceStatus.OPEN

    def mark_paid(self) -> None:
        if self.status is not InvoiceStatus.OPEN:
            raise ValueError("only open invoices can be paid")
        self.status = InvoiceStatus.PAID
        self.paid_at = datetime.now(timezone.utc)

    def refund(self) -> None:
        if self.status is not InvoiceStatus.PAID:
            raise ValueError("only paid invoices can be refunded")
        self.status = InvoiceStatus.REFUNDED


@dataclass(frozen=True)
class Refund:
    payment_id: str
    amount: Money
    reason: str
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def invoice_total(lines: Iterable[InvoiceLine], coupon: Coupon | None = None) -> Money:
    return Invoice(customer_id="preview", lines=list(lines), coupon=coupon).total
