from decimal import Decimal
import hashlib
import hmac
import json

import pytest

from aios.payments.providers.paddle import PaddleCheckoutRequest, PaddleProvider
from aios.payments.usage import UsageBillingService
from aios.payments.wallet import InsufficientBalanceError, WalletService


class FakeTransport:
    def post(self, path, headers, json):
        assert path == "/transactions"
        assert headers["Authorization"] == "Bearer test_key"
        return {
            "data": {
                "id": "txn_123",
                "status": "ready",
                "checkout": {"url": "https://checkout.paddle.test/txn_123"},
            }
        }

    def patch(self, path, headers, json):
        return {"data": {"id": path.rsplit("/", 1)[-1], "status": "active", "scheduled_change": json["scheduled_change"]}}


def test_paddle_checkout_and_webhook_verification():
    provider = PaddleProvider(api_key="test_key", webhook_secret="secret", transport=FakeTransport())
    checkout = provider.create_checkout(
        PaddleCheckoutRequest(
            customer_id="ctm_1",
            price_id="pri_1",
            success_url="https://ai.vip-e.net/billing/success",
            metadata={"user_id": "user_1"},
        )
    )
    assert checkout.transaction_id == "txn_123"

    body = json.dumps({"event_type": "transaction.completed"}).encode()
    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    event = provider.verify_webhook(raw_body=body, signature=f"ts=1;h1={signature}")
    assert event["event_type"] == "transaction.completed"


def test_wallet_credits_usage_and_idempotency():
    wallets = WalletService()
    wallet = wallets.get_or_create(owner_id="user_1", currency="USD")
    wallets.credit(wallet=wallet, amount=Decimal("25.00"), reference="topup:1")

    usage = UsageBillingService(wallets)
    record, first_entry = usage.charge(
        wallet=wallet,
        metric="ai_tokens",
        units=Decimal("1000"),
        unit_price=Decimal("0.002"),
        idempotency_key="request-1",
    )
    duplicate, duplicate_entry = usage.charge(
        wallet=wallet,
        metric="ai_tokens",
        units=Decimal("1000"),
        unit_price=Decimal("0.002"),
        idempotency_key="request-1",
    )

    assert record == duplicate
    assert first_entry == duplicate_entry
    assert wallet.balance == Decimal("23.000")


def test_wallet_rejects_overdraft():
    wallets = WalletService()
    wallet = wallets.get_or_create(owner_id="user_2", currency="EUR")
    with pytest.raises(InsufficientBalanceError):
        wallets.debit(wallet=wallet, amount=Decimal("1.00"), reference="usage:1")
