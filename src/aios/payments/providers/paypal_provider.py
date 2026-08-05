from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class PayPalOrderRequest:
    amount: Decimal
    currency: str
    return_url: str
    cancel_url: str
    description: str = "AIOS subscription"


class PayPalProvider:
    """PayPal checkout adapter for one-time payments and subscriptions."""

    name = "paypal"

    def __init__(self, client_id: str, client_secret: str, webhook_id: str) -> None:
        if not client_id:
            raise ValueError("PayPal client_id is required")
        if not client_secret:
            raise ValueError("PayPal client_secret is required")
        if not webhook_id:
            raise ValueError("PayPal webhook_id is required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._webhook_id = webhook_id

    def build_order_payload(self, request: PayPalOrderRequest) -> dict[str, Any]:
        if request.amount <= 0:
            raise ValueError("amount must be greater than zero")
        currency = request.currency.upper()
        return {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "description": request.description,
                    "amount": {
                        "currency_code": currency,
                        "value": f"{request.amount:.2f}",
                    },
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": request.return_url,
                        "cancel_url": request.cancel_url,
                        "user_action": "PAY_NOW",
                    }
                }
            },
        }

    def verify_webhook(self, headers: Mapping[str, str], event: Mapping[str, Any]) -> bool:
        required = {
            "paypal-auth-algo",
            "paypal-cert-url",
            "paypal-transmission-id",
            "paypal-transmission-sig",
            "paypal-transmission-time",
        }
        normalized = {key.lower(): value for key, value in headers.items()}
        if not required.issubset(normalized):
            return False
        return bool(event.get("id") and event.get("event_type"))
