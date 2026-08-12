from decimal import Decimal

import pytest

from aios.payments.providers.paypal_provider import PayPalOrderRequest, PayPalProvider
from aios.payments.providers.stripe_provider import StripeCheckoutRequest, StripeProvider


def test_stripe_checkout_keeps_apple_pay_outside_stripe_adapter() -> None:
    provider = StripeProvider("sk_test", "whsec_test")
    payload = provider.build_checkout_payload(
        StripeCheckoutRequest(
            customer_id="cus_123",
            price_id="price_pro",
            success_url="https://ai.vip-e.net/billing/success",
            cancel_url="https://ai.vip-e.net/billing/cancel",
        )
    )

    assert payload["automatic_payment_methods"] == {"enabled": True}
    assert "apple_pay_enabled" not in payload["metadata"]
    assert payload["metadata"]["google_pay_enabled"] == "true"
    assert payload["line_items"][0]["quantity"] == 1


def test_stripe_rejects_invalid_quantity() -> None:
    provider = StripeProvider("sk_test", "whsec_test")
    with pytest.raises(ValueError, match="quantity"):
        provider.build_checkout_payload(
            StripeCheckoutRequest(
                customer_id="cus_123",
                price_id="price_pro",
                success_url="https://ai.vip-e.net/billing/success",
                cancel_url="https://ai.vip-e.net/billing/cancel",
                quantity=0,
            )
        )


def test_paypal_order_payload() -> None:
    provider = PayPalProvider("client", "secret", "webhook")
    payload = provider.build_order_payload(
        PayPalOrderRequest(
            amount=Decimal("49.90"),
            currency="eur",
            return_url="https://ai.vip-e.net/billing/success",
            cancel_url="https://ai.vip-e.net/billing/cancel",
        )
    )

    amount = payload["purchase_units"][0]["amount"]
    assert amount == {"currency_code": "EUR", "value": "49.90"}
    assert payload["payment_source"]["paypal"]["experience_context"]["user_action"] == "PAY_NOW"


def test_paypal_webhook_requires_complete_headers() -> None:
    provider = PayPalProvider("client", "secret", "webhook")
    assert not provider.verify_webhook({}, {"id": "evt_1", "event_type": "PAYMENT.CAPTURE.COMPLETED"})

    headers = {
        "PayPal-Auth-Algo": "SHA256withRSA",
        "PayPal-Cert-Url": "https://api.paypal.com/cert.pem",
        "PayPal-Transmission-Id": "tx_1",
        "PayPal-Transmission-Sig": "signature",
        "PayPal-Transmission-Time": "2026-07-28T00:00:00Z",
    }
    assert provider.verify_webhook(
        headers,
        {"id": "evt_1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
