from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from threading import RLock
from typing import Dict, List
from uuid import uuid4


class InsufficientBalanceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WalletEntry:
    id: str
    wallet_id: str
    kind: str
    amount: Decimal
    balance_after: Decimal
    reference: str


@dataclass(slots=True)
class Wallet:
    id: str
    owner_id: str
    currency: str
    balance: Decimal = Decimal("0")
    entries: List[WalletEntry] = field(default_factory=list)


class WalletService:
    """Thread-safe credit wallet for top-ups and pay-as-you-go usage."""

    def __init__(self) -> None:
        self._wallets: Dict[str, Wallet] = {}
        self._owner_index: Dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def get_or_create(self, *, owner_id: str, currency: str) -> Wallet:
        normalized = currency.upper()
        key = (owner_id, normalized)
        with self._lock:
            wallet_id = self._owner_index.get(key)
            if wallet_id:
                return self._wallets[wallet_id]
            wallet = Wallet(id=str(uuid4()), owner_id=owner_id, currency=normalized)
            self._wallets[wallet.id] = wallet
            self._owner_index[key] = wallet.id
            return wallet

    def credit(self, *, wallet: Wallet, amount: Decimal, reference: str) -> WalletEntry:
        self._validate_amount(amount)
        with self._lock:
            wallet.balance += amount
            return self._append(wallet, "credit", amount, reference)

    def debit(self, *, wallet: Wallet, amount: Decimal, reference: str) -> WalletEntry:
        self._validate_amount(amount)
        with self._lock:
            if wallet.balance < amount:
                raise InsufficientBalanceError("Wallet balance is insufficient")
            wallet.balance -= amount
            return self._append(wallet, "debit", -amount, reference)

    def charge_usage(self, *, wallet: Wallet, units: Decimal, unit_price: Decimal, reference: str) -> WalletEntry:
        self._validate_amount(units)
        self._validate_amount(unit_price)
        return self.debit(wallet=wallet, amount=units * unit_price, reference=reference)

    @staticmethod
    def _validate_amount(amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Amount must be positive")

    @staticmethod
    def _append(wallet: Wallet, kind: str, amount: Decimal, reference: str) -> WalletEntry:
        entry = WalletEntry(
            id=str(uuid4()),
            wallet_id=wallet.id,
            kind=kind,
            amount=amount,
            balance_after=wallet.balance,
            reference=reference,
        )
        wallet.entries.append(entry)
        return entry
