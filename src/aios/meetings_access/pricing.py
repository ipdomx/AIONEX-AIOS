from __future__ import annotations

from dataclasses import dataclass

from .models import SessionRole


@dataclass(frozen=True, slots=True)
class RoleRate:
    role: SessionRole
    price_per_minute_minor: int
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if self.price_per_minute_minor < 0:
            raise ValueError("price_per_minute_minor cannot be negative")
        if not self.currency:
            raise ValueError("currency is required")


class SessionPricingService:
    def __init__(self, rates: list[RoleRate]) -> None:
        self._rates = {rate.role: rate for rate in rates}

    def quote(self, *, role: SessionRole, minutes: int) -> tuple[int, str]:
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        try:
            rate = self._rates[role]
        except KeyError as exc:
            raise KeyError(f"missing rate for role: {role.value}") from exc
        return rate.price_per_minute_minor * minutes, rate.currency
