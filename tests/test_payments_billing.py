from decimal import Decimal
from uuid import uuid4

import pytest

from payments_billing import (
    BillingCycle,
    BillingService,
    CheckoutSession,
    InMemoryBillingRepository,
    Money,
    PaymentProvider,
    Plan,
    ProviderRegistry,
    SubscriptionStatus,
)


class FakeProvider(PaymentProvider):
    name = "fake"

    def create_checkout(self, transaction, success_url, cancel_url):
        return CheckoutSession(self.name, str(transaction.id), success_url)

    def refund(self, external_reference, amount=None):
        return f"refund:{external_reference}"

    def verify_webhook(self, payload, headers):
        return headers.get("x-test-signature") == "valid"


def build_service():
    repository = InMemoryBillingRepository()
    providers = ProviderRegistry()
    providers.register(FakeProvider())
    return BillingService(repository, providers)


def test_create_and_list_active_plan():
    service = build_service()
    plan = Plan(
        code="pro-monthly",
        name="Pro Monthly",
        price=Money(Decimal("29.00"), "usd"),
        billing_cycle=BillingCycle.MONTHLY,
        features=frozenset({"projects", "agents"}),
    )
    service.create_plan(plan)

    assert service.list_active_plans() == (plan,)
    assert plan.price.currency == "USD"


def test_trial_subscription_and_change_plan():
    service = build_service()
    service.create_plan(
        Plan(
            code="starter",
            name="Starter",
            price=Money(Decimal("9.00"), "USD"),
            billing_cycle=BillingCycle.MONTHLY,
            trial_days=14,
        )
    )
    service.create_plan(
        Plan(
            code="business",
            name="Business",
            price=Money(Decimal("99.00"), "USD"),
            billing_cycle=BillingCycle.YEARLY,
        )
    )

    user_id = uuid4()
    subscription = service.start_subscription(user_id, "starter")
    assert subscription.status is SubscriptionStatus.TRIALING
    assert subscription.current_period_end is not None

    upgraded = service.change_plan(user_id, "business")
    assert upgraded.plan_code == "business"
    assert upgraded.status is SubscriptionStatus.ACTIVE


def test_cancel_subscription_at_period_end():
    service = build_service()
    service.create_plan(
        Plan(
            code="pro",
            name="Pro",
            price=Money(Decimal("49.00"), "USD"),
            billing_cycle=BillingCycle.MONTHLY,
        )
    )
    user_id = uuid4()
    service.start_subscription(user_id, "pro")

    canceled = service.cancel_subscription(user_id, at_period_end=True)
    assert canceled.cancel_at_period_end is True
    assert canceled.status is SubscriptionStatus.ACTIVE


def test_checkout_uses_registered_provider():
    service = build_service()
    service.create_plan(
        Plan(
            code="team",
            name="Team",
            price=Money(Decimal("79.00"), "USD"),
            billing_cycle=BillingCycle.MONTHLY,
        )
    )

    checkout = service.create_checkout(
        uuid4(),
        "team",
        "fake",
        "https://example.test/success",
        "https://example.test/cancel",
    )

    assert checkout.provider == "fake"
    assert checkout.checkout_url == "https://example.test/success"


def test_money_rejects_negative_amount():
    with pytest.raises(ValueError):
        Money(Decimal("-1.00"), "USD")
