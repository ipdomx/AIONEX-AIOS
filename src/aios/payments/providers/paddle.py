from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PaddleCheckoutRequest:
    customer_id: str
    price_id: str
    success_url: str
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PaddleCheckoutSession:
    transaction_id: str
    checkout_url: str
    status: str


class PaddleProvider:
    """Paddle Billing adapter contract with webhook verification.

    Network transport is injected so the provider remains testable and can be
    wired to the platform HTTP client without coupling the payment domain to a
    specific library.
    """

    name = "paddle"

    def __init__(self, *, api_key: str, webhook_secret: str, transport: Any) -> None:
        if not api_key:
            raise ValueError("Paddle api_key is required")
        if not webhook_secret:
            raise ValueError("Paddle webhook_secret is required")
        self._api_key = api_key
        self._webhook_secret = webhook_secret.encode("utf-8")
        self._transport = transport

    def create_checkout(self, request: PaddleCheckoutRequest) -> PaddleCheckoutSession:
        payload = {
            "items": [{"price_id": request.price_id, "quantity": 1}],
            "customer_id": request.customer_id,
            "checkout": {"url": request.success_url},
            "custom_data": dict(request.metadata),
        }
        response = self._transport.post(
            "/transactions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        data = response["data"]
        return PaddleCheckoutSession(
            transaction_id=data["id"],
            checkout_url=data["checkout"]["url"],
            status=data["status"],
        )

    def cancel_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        if not subscription_id:
            raise ValueError("subscription_id is required")
        response = self._transport.patch(
            f"/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"scheduled_change": {"action": "cancel", "effective_at": "next_billing_period"}},
        )
        return response["data"]

    def verify_webhook(self, *, raw_body: bytes, signature: str) -> Mapping[str, Any]:
        if not signature:
            raise ValueError("Paddle signature is required")
        expected = hmac.new(self._webhook_secret, raw_body, sha256).hexdigest()
        supplied = self._extract_signature(signature)
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("Invalid Paddle webhook signature")
        return json.loads(raw_body.decode("utf-8"))

    @staticmethod
    def _extract_signature(header: str) -> str:
        values = {}
        for part in header.split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                values[key] = value
        return values.get("h1", header)
