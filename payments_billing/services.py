from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from .domain import BillingCycle, Money, PaymentTransaction, Plan, Subscription, SubscriptionStatus
from .providers import CheckoutSession, ProviderRegistry


class BillingRepository(Protocol):
    def save_plan(self, plan: Plan) -> None: ...
    def get_plan(self, code: str) -> Plan: ...
    def list_plans(self) -> tuple[Plan, ...]: ...
    def save_subscription(self, subscription: Subscription) -> None: ...
    def get_subscription_for_user(self, user_id: UUID) -> Subscription | None: ...
    def save_transaction(self, transaction: PaymentTransaction) -> None: ...


class InMemoryBillingRepository:
    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._subscriptions: dict[UUID, Subscription] = {}
        self._transactions: dict[UUID, PaymentTransaction] = {}

    def save_plan(self, plan: Plan) -> None:
        self._plans[plan.code] = plan

    def get_plan(self, code: str) -> Plan:
        try:
            return self._plans[code]
        except KeyError as exc:
            raise KeyError(f"unknown plan: {code}") from exc

    def list_plans(self) -> tuple[Plan, ...]:
        return tuple(sorted(self._plans.values(), key=lambda plan: plan.code))

    def save_subscription(self, subscription: Subscription) -> None:
        self._subscriptions[subscription.user_id] = subscription

    def get_subscription_for_user(self, user_id: UUID) -> Subscription | None:
        return self._subscriptions.get(user_id)

    def save_transaction(self, transaction: PaymentTransaction) -> None:
        self._transactions[transaction.id] = transaction


class BillingService:
    def __init__(self, repository: BillingRepository, providers: ProviderRegistry) -> None:
        self._repository = repository
        self._providers = providers

    def create_plan(self, plan: Plan) -> Plan:
        self._repository.save_plan(plan)
        return plan

    def list_active_plans(self) -> tuple[Plan, ...]:
        return tuple(plan for plan in self._repository.list_plans() if plan.active)

    def start_subscription(self, user_id: UUID, plan_code: str) -> Subscription:
        plan = self._repository.get_plan(plan_code)
        if not plan.active:
            raise ValueError("plan is inactive")

        now = datetime.now(timezone.utc)
        status = SubscriptionStatus.TRIALING if plan.trial_days else SubscriptionStatus.ACTIVE
        period_end = self._period_end(now, plan)
        if plan.trial_days:
            period_end = now + timedelta(days=plan.trial_days)

        subscription = Subscription(
            user_id=user_id,
            plan_code=plan.code,
            status=status,
            started_at=now,
            current_period_end=period_end,
        )
        self._repository.save_subscription(subscription)
        return subscription

    def change_plan(self, user_id: UUID, target_plan_code: str) -> Subscription:
        subscription = self._require_subscription(user_id)
        target = self._repository.get_plan(target_plan_code)
        if not target.active:
            raise ValueError("target plan is inactive")

        updated = replace(
            subscription,
            plan_code=target.code,
            status=SubscriptionStatus.ACTIVE,
            current_period_end=self._period_end(datetime.now(timezone.utc), target),
            cancel_at_period_end=False,
        )
        self._repository.save_subscription(updated)
        return updated

    def cancel_subscription(self, user_id: UUID, at_period_end: bool = True) -> Subscription:
        subscription = self._require_subscription(user_id)
        updated = replace(
            subscription,
            status=subscription.status if at_period_end else SubscriptionStatus.CANCELED,
            cancel_at_period_end=at_period_end,
        )
        self._repository.save_subscription(updated)
        return updated

    def create_checkout(
        self,
        user_id: UUID,
        plan_code: str,
        provider_name: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        plan = self._repository.get_plan(plan_code)
        transaction = PaymentTransaction(
            user_id=user_id,
            amount=Money(Decimal(plan.price.amount), plan.price.currency),
            provider=provider_name,
            metadata={"plan_code": plan.code},
        )
        self._repository.save_transaction(transaction)
        return self._providers.get(provider_name).create_checkout(transaction, success_url, cancel_url)

    def _require_subscription(self, user_id: UUID) -> Subscription:
        subscription = self._repository.get_subscription_for_user(user_id)
        if subscription is None:
            raise KeyError(f"no subscription for user: {user_id}")
        return subscription

    @staticmethod
    def _period_end(start: datetime, plan: Plan) -> datetime | None:
        if plan.billing_cycle is BillingCycle.MONTHLY:
            return start + timedelta(days=30)
        if plan.billing_cycle is BillingCycle.YEARLY:
            return start + timedelta(days=365)
        return None
