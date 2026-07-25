from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BudgetAccount:
    limit: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.spent)


class CostGovernor:
    def __init__(self) -> None:
        self._accounts: dict[str, BudgetAccount] = {}

    def set_limit(self, scope: str, amount: float) -> None:
        if amount < 0:
            raise ValueError("budget must be non-negative")
        previous = self._accounts.get(scope)
        self._accounts[scope] = BudgetAccount(amount, previous.spent if previous else 0.0)

    def authorize(self, scope: str, estimated_cost: float) -> bool:
        account = self._accounts.get(scope)
        return account is None or estimated_cost <= account.remaining

    def record(self, scope: str, cost: float) -> None:
        account = self._accounts.get(scope)
        if account is not None:
            account.spent += max(0.0, cost)

    def snapshot(self, scope: str) -> dict[str, float | None]:
        account = self._accounts.get(scope)
        if account is None:
            return {"limit": None, "spent": 0.0, "remaining": None}
        return {"limit": account.limit, "spent": account.spent, "remaining": account.remaining}
