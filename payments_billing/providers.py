from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

from .domain import Money, PaymentTransaction


@dataclass(frozen=True)
class CheckoutSession:
    provider: str
    external_reference: str
    checkout_url: str


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def create_checkout(
        self,
        transaction: PaymentTransaction,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        raise NotImplementedError

    @abstractmethod
    def refund(self, external_reference: str, amount: Money | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> bool:
        raise NotImplementedError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, PaymentProvider] = {}

    def register(self, provider: PaymentProvider) -> None:
        name = provider.name.strip().lower()
        if not name:
            raise ValueError("provider name is required")
        if name in self._providers:
            raise ValueError(f"provider already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> PaymentProvider:
        try:
            return self._providers[name.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"unknown payment provider: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
