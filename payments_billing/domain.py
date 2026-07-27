from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable
from uuid import UUID, uuid4


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ONE_TIME = "one_time"


class SubscriptionStatus(str, Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("amount must be non-negative")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be an ISO-4217 three-letter code")
        object.__setattr__(self, "currency", self.currency.upper())


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price: Money
    billing_cycle: BillingCycle
    features: frozenset[str] = field(default_factory=frozenset)
    trial_days: int = 0
    active: bool = True

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("plan code is required")
        if not self.name.strip():
            raise ValueError("plan name is required")
        if self.trial_days < 0:
            raise ValueError("trial_days must be non-negative")


@dataclass
class Subscription:
    user_id: UUID
    plan_code: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


@dataclass
class PaymentTransaction:
    user_id: UUID
    amount: Money
    provider: str
    status: PaymentStatus = PaymentStatus.PENDING
    id: UUID = field(default_factory=uuid4)
    external_reference: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


def normalize_features(features: Iterable[str]) -> frozenset[str]:
    return frozenset(feature.strip() for feature in features if feature.strip())
