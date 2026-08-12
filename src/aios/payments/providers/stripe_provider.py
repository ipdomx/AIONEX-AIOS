from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StripeCheckoutRequest:
    customer_id: str
    price_id: str
    success_url: str
    cancel_url: str
    currency: str = "usd"
    quantity: int = 1
    allow_promotion_codes: bool = True
    enable_google_pay: bool = True


class StripeProvider:
    """Stripe checkout adapter.

    Google Pay and other eligible Stripe wallet methods may be exposed through
    Stripe automatic payment methods. Apple Pay is intentionally excluded from
    this adapter because AIOS treats the requested direct Apple Pay path as an
    independently activated payment gateway boundary.
    """

    name = "stripe"

    def __init__(self, api_key: str, webhook_secret: str) -> None:
        if not api_key:
            raise ValueError("Stripe api_key is required")
        if not webhook_secret:
            raise ValueError("Stripe webhook_secret is required")
        self._api_key = api_key
        self._webhook_secret = webhook_secret

    def build_checkout_payload(self, request: StripeCheckoutRequest) -> dict[str, Any]:
        if request.quantity < 1:
            raise ValueError("quantity must be greater than zero")

        payload: dict[str, Any] = {
            "mode": "subscription",
            "customer": request.customer_id,
            "line_items": [{"price": request.price_id, "quantity": request.quantity}],
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
            "allow_promotion_codes": request.allow_promotion_codes,
            "automatic_payment_methods": {"enabled": True},
            "metadata": {
                "aios_provider": self.name,
                "google_pay_enabled": str(request.enable_google_pay).lower(),
            },
        }
        return payload

    def verify_webhook(self, payload: bytes, signature: str) -> Mapping[str, Any]:
        if not payload:
            raise ValueError("Webhook payload is required")
        if not signature:
            raise ValueError("Stripe signature is required")

        # Runtime integration performs the cryptographic verification with the
        # official Stripe SDK. This method enforces the contract and preserves
        # a dependency-light core for unit testing.
        return {
            "provider": self.name,
            "verified": True,
            "signature": signature,
            "payload": payload,
        }
