from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4


class LocalProviderKind(str, Enum):
    PAYMOB = "paymob"
    FAWRY = "fawry"
    STC_PAY = "stc_pay"
    MADA = "mada"
    BANK_TRANSFER = "bank_transfer"


@dataclass(frozen=True)
class LocalCheckoutRequest:
    customer_id: str
    amount_minor: int
    currency: str
    success_url: str
    cancel_url: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class LocalCheckoutResult:
    provider: str
    external_id: str
    status: str
    redirect_url: str | None = None
    instructions: dict[str, Any] | None = None


class LocalPaymentProvider(Protocol):
    name: str

    def create_checkout(self, request: LocalCheckoutRequest) -> LocalCheckoutResult:
        ...

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        ...


class LocalProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LocalPaymentProvider] = {}

    def register(self, provider: LocalPaymentProvider) -> None:
        key = provider.name.strip().lower()
        if not key:
            raise ValueError("provider name is required")
        if key in self._providers:
            raise ValueError(f"provider already registered: {key}")
        self._providers[key] = provider

    def get(self, name: str) -> LocalPaymentProvider:
        try:
            return self._providers[name.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"unknown local payment provider: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


@dataclass
class ConfiguredLocalProvider:
    name: str
    api_key: str
    webhook_secret: str
    checkout_base_url: str

    def create_checkout(self, request: LocalCheckoutRequest) -> LocalCheckoutResult:
        if request.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        external_id = f"{self.name}_{uuid4().hex}"
        return LocalCheckoutResult(
            provider=self.name,
            external_id=external_id,
            status="pending",
            redirect_url=f"{self.checkout_base_url.rstrip('/')}/{external_id}",
        )

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return bool(payload) and bool(signature) and signature == self.webhook_secret


@dataclass
class BankTransferProvider:
    name: str = LocalProviderKind.BANK_TRANSFER.value
    bank_name: str = ""
    account_name: str = ""
    iban: str = ""
    swift: str = ""

    def create_checkout(self, request: LocalCheckoutRequest) -> LocalCheckoutResult:
        if request.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        reference = f"BT-{uuid4().hex[:12].upper()}"
        return LocalCheckoutResult(
            provider=self.name,
            external_id=reference,
            status="awaiting_transfer",
            instructions={
                "bank_name": self.bank_name,
                "account_name": self.account_name,
                "iban": self.iban,
                "swift": self.swift,
                "reference": reference,
                "amount_minor": request.amount_minor,
                "currency": request.currency.upper(),
            },
        )

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return False
