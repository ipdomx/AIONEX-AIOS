"""Phase 29D durable billing, payments, and entitlement contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.api.v1.router import api_router
from app.core.auth import UserRecord, current_user, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    BillingAccount,
    BillingCheckoutSession,
    BillingCoupon,
    BillingCouponRedemption,
    BillingInvoice,
    BillingLicense,
    BillingPaymentMethod,
    BillingPlan,
    BillingPrice,
    BillingRefund,
    BillingSubscription,
    BillingTaxRate,
    BillingTransaction,
    BillingUsageRecord,
    BillingWallet,
    BillingWebhookEvent,
    Organization,
    Role,
    User,
)
from app.services import billing
from app.services.free_tier import DEFAULT_FREE_TIER_POLICY


def actor(
    user: User, organization: Organization, permissions: list[str] | None = None
) -> UserRecord:
    return UserRecord(
        id=user.id,
        email=user.email,
        name=user.name,
        role="Owner",
        password_hash=user.password_hash,
        organization_id=organization.id,
        organization_name=organization.name,
        organization_plan=organization.plan,
        permissions=permissions or ["billing:read", "billing:write"],
    )


async def identity(suffix: str, *, plan: str = "free") -> tuple[Organization, User]:
    organization = Organization(
        name=f"Billing {suffix}",
        slug=f"billing-{suffix}",
        plan=plan,
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name=f"Billing Owner {suffix}",
            status="active",
        )
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"billing-{suffix}@example.com",
            name="Billing Test",
            password_hash=pwd_context.hash(f"BillingTest!{suffix}"),
            status="active",
        )
        session.add(user)
        await session.commit()
        return organization, user


async def cleanup(organization_id: str, plan_codes: list[str]) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == organization_id)
        )
        for code in plan_codes:
            plan = await session.scalar(
                select(BillingPlan).where(BillingPlan.code == code)
            )
            if plan is not None:
                await session.delete(plan)
        await session.commit()


def published(plans: list[dict], *, version: int = 7) -> dict:
    return {
        "configuration": {
            "pricing": {
                "enabled": True,
                "show_tax_note": True,
                "default_currency": "USD",
                "default_period": "monthly",
                "heading": {"en": "Plans"},
                "description": {"en": "Billing"},
                "tax_note": {"en": "Tax calculated at checkout"},
                "plans": plans,
                "faq": [],
            }
        },
        "publication": {"version": version},
    }


@pytest.mark.asyncio
async def test_catalog_overlays_free_limits_and_creates_durable_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)

    async def portal(_session):
        return published(
            [
                {
                    "id": "free",
                    "enabled": True,
                    "featured": False,
                    "order": 1,
                    "name": {"en": "Free"},
                    "description": {"en": "Free"},
                    "features": [],
                    "limits": {"projects": 999},
                    "entitlements": ["projects.core"],
                    "metering": {},
                    "cta_label": {"en": "Start"},
                    "checkout_provider": "none",
                    "periods": [
                        {
                            "id": "monthly",
                            "months": 1,
                            "price": 0,
                            "currency": "USD",
                            "enabled": True,
                            "label": {"en": "Monthly"},
                            "checkout_reference": "",
                        }
                    ],
                }
            ]
        )

    async def free_policy(_session):
        return dict(DEFAULT_FREE_TIER_POLICY)

    monkeypatch.setattr(billing, "get_published_portal", portal)
    monkeypatch.setattr(billing, "get_free_tier_policy", free_policy)
    try:
        async with SessionLocal() as session:
            catalogue = await billing.sync_catalog(session)
            await session.commit()
            free = catalogue["plans"][0]
            assert free["limits"] == {
                "projects": DEFAULT_FREE_TIER_POLICY["project_limit"],
                "user_messages_per_month": DEFAULT_FREE_TIER_POLICY[
                    "monthly_user_message_limit"
                ],
                "assistant_responses_per_month": DEFAULT_FREE_TIER_POLICY[
                    "monthly_assistant_response_limit"
                ],
                "storage_bytes": DEFAULT_FREE_TIER_POLICY["storage_limit_bytes"],
                "max_message_characters": DEFAULT_FREE_TIER_POLICY[
                    "max_message_characters"
                ],
            }
            account = await session.scalar(
                select(BillingAccount).where(
                    BillingAccount.organization_id == organization.id
                )
            )
            plan = await session.get(BillingPlan, account.plan_id)
            assert account is not None and plan is not None
            assert plan.code == "free"
            assert account.limits == free["limits"]
            assert account.licensed_seats == 1
            assert user.id
    finally:
        await cleanup(organization.id, ["free"])


@pytest.mark.asyncio
async def test_stripe_checkout_is_idempotent_and_never_stores_card_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="professional")
    calls: list[httpx.Request] = []

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "STRIPE_SECRET_KEY", "sk_test_phase29d")
    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", "whsec_phase29d")
    monkeypatch.setattr(billing.settings, "PAYMENTS_ENVIRONMENT", "sandbox")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Idempotency-Key"] == f"phase29d-{suffix}"
        assert b"line_items%5B0%5D%5Bprice%5D=price_phase29d" in request.content
        assert b"card" not in request.content.lower()
        return httpx.Response(
            200,
            json={
                "id": f"cs_test_{suffix}",
                "url": "https://checkout.stripe.test/session",
                "expires_at": int(
                    (datetime.now(UTC) + timedelta(minutes=30)).timestamp()
                ),
            },
        )

    transport = httpx.MockTransport(handler)
    plan_code = f"professional-{suffix}"
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Professional",
                status="active",
                default_currency="USD",
                limits={"projects": 10},
                entitlements=["projects.core"],
                metering={},
                source_version=1,
                source_hash="a" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=2500,
                currency="USD",
                enabled=True,
                provider="stripe",
                provider_reference="price_phase29d",
            )
            session.add(price)
            await session.commit()
            first = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=plan_code,
                period_code="monthly",
                idempotency_key=f"phase29d-{suffix}",
                transport=transport,
            )
            second = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=plan_code,
                period_code="monthly",
                idempotency_key=f"phase29d-{suffix}",
                transport=transport,
            )
            assert first == second
            assert len(calls) == 1
            assert first["checkout_url"].startswith("https://checkout.stripe.test/")
            checkout = await session.scalar(
                select(BillingCheckoutSession).where(
                    BillingCheckoutSession.id == first["id"]
                )
            )
            assert "card" not in json.dumps(checkout.session_metadata).lower()
            assert await session.scalar(select(func.count(BillingInvoice.id))) >= 1
            assert await session.scalar(select(func.count(BillingTransaction.id))) >= 1
    finally:
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_signed_webhook_is_idempotent_and_activates_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="professional")
    plan_code = f"webhook-{suffix}"

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", "whsec_phase29d")
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Webhook",
                status="active",
                default_currency="USD",
                limits={"projects": 5},
                entitlements=["projects.core", "billing.webhooks"],
                metering={},
                source_version=1,
                source_hash="b" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=1000,
                currency="USD",
                enabled=True,
                provider="stripe",
                provider_reference="price_webhook",
            )
            session.add(price)
            account = BillingAccount(
                organization_id=organization.id,
                plan_id=plan.id,
                status="active",
                licensed_seats=1,
                limits=plan.limits,
                entitlements=plan.entitlements,
            )
            session.add(account)
            await session.flush()
            checkout = BillingCheckoutSession(
                organization_id=organization.id,
                user_id=user.id,
                plan_id=plan.id,
                price_id=price.id,
                provider="stripe",
                external_reference=f"cs_{suffix}",
                status="created",
                idempotency_key=f"webhook-checkout-{suffix}",
                session_metadata={"total_minor": 1000},
            )
            session.add(checkout)
            await session.flush()
            invoice = BillingInvoice(
                organization_id=organization.id,
                provider="stripe",
                number=f"INV-WH-{suffix}",
                status="open",
                currency="USD",
                subtotal_minor=1000,
                total_minor=1000,
                line_items=[],
            )
            session.add(invoice)
            await session.flush()
            transaction = BillingTransaction(
                organization_id=organization.id,
                user_id=user.id,
                invoice_id=invoice.id,
                provider="stripe",
                status="pending",
                amount_minor=1000,
                currency="USD",
                idempotency_key=f"transaction-{suffix}",
                transaction_metadata={"checkout_id": checkout.id},
            )
            session.add(transaction)
            await session.commit()

            payload = {
                "id": f"evt_{suffix}",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": f"cs_{suffix}",
                        "client_reference_id": checkout.id,
                        "subscription": f"sub_{suffix}",
                        "payment_intent": f"pi_{suffix}",
                        "customer": f"cus_{suffix}",
                        "payment_method": f"pm_{suffix}",
                        "payment_method_details": {
                            "type": "card",
                            "card": {
                                "brand": "visa",
                                "last4": "4242",
                                "exp_month": 12,
                                "exp_year": 2032,
                            },
                        },
                        "metadata": {
                            "checkout_id": checkout.id,
                            "organization_id": organization.id,
                        },
                    }
                },
            }
            raw = json.dumps(payload, separators=(",", ":")).encode()
            timestamp = str(int(datetime.now(UTC).timestamp()))
            signature = hmac.new(
                b"whsec_phase29d", timestamp.encode() + b"." + raw, hashlib.sha256
            ).hexdigest()
            verified = await billing.verify_webhook(
                "stripe", raw, {"Stripe-Signature": f"t={timestamp},v1={signature}"}
            )
            first = await billing.process_webhook_event(
                session, "stripe", verified, raw
            )
            second = await billing.process_webhook_event(
                session, "stripe", verified, raw
            )
            assert first["status"] == "processed"
            assert second["duplicate"] is True
            await session.refresh(checkout)
            await session.refresh(transaction)
            await session.refresh(invoice)
            await session.refresh(account)
            assert checkout.status == "completed"
            assert transaction.status == "succeeded"
            assert invoice.status == "paid"
            assert account.plan_id == plan.id
            assert account.provider_customers["stripe"] == f"cus_{suffix}"
            method = await session.scalar(
                select(BillingPaymentMethod).where(
                    BillingPaymentMethod.organization_id == organization.id
                )
            )
            assert method is not None
            assert method.external_reference == f"pm_{suffix}"
            assert method.brand == "visa" and method.last4 == "4242"
            stored_payment_metadata = {
                "provider": method.provider,
                "external_reference": method.external_reference,
                "type": method.method_type,
                "brand": method.brand,
                "last4": method.last4,
                "expiry_month": method.expiry_month,
                "expiry_year": method.expiry_year,
            }
            assert "4242424242424242" not in json.dumps(stored_payment_metadata)
            assert await session.scalar(select(func.count(BillingWebhookEvent.id))) == 1
    finally:
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_coupon_tax_wallet_usage_license_and_manual_refund_are_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="metered")
    owner = actor(user, organization, ["*"])
    plan_code = f"metered-{suffix}"

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Metered",
                status="active",
                default_currency="USD",
                limits={"projects": 3},
                entitlements=["projects.core"],
                metering={
                    "tokens": {
                        "included": 1000,
                        "unit_size": 1000,
                        "unit_price_minor": 25,
                        "currency": "USD",
                    }
                },
                source_version=1,
                source_hash="c" * 64,
            )
            session.add(plan)
            await session.flush()
            account = BillingAccount(
                organization_id=organization.id,
                plan_id=plan.id,
                status="active",
                licensed_seats=2,
                limits=plan.limits,
                entitlements=plan.entitlements,
            )
            session.add(account)
            await session.commit()

            coupon = await billing.owner_create_coupon(
                session,
                owner,
                code=f"SAVE{suffix}",
                discount_type="percent",
                percent_off=10,
                amount_off_minor=None,
                currency=None,
                max_redemptions=10,
                expires_at=now_plus(),
            )
            validated = await billing.validate_coupon(
                session, coupon["code"], 1000, "USD"
            )
            assert validated["discount_minor"] == 100
            tax = await billing.owner_upsert_tax(
                session,
                owner,
                code="VAT",
                country_code="AE",
                percentage=5,
                inclusive=False,
            )
            assert tax["percentage"] == 5

            credit = await billing.post_wallet_entry(
                session,
                organization.id,
                amount_minor=1000,
                idempotency_key=f"credit-{suffix}",
                entry_type="credit",
                description="Test credit",
            )
            await session.commit()
            assert credit.balance_after_minor == 1000
            included = await billing.record_usage(
                session,
                organization.id,
                metric="tokens",
                quantity=1000,
                idempotency_key=f"usage-included-{suffix}",
            )
            overage = await billing.record_usage(
                session,
                organization.id,
                metric="tokens",
                quantity=1001,
                idempotency_key=f"usage-overage-{suffix}",
            )
            replay = await billing.record_usage(
                session,
                organization.id,
                metric="tokens",
                quantity=1001,
                idempotency_key=f"usage-overage-{suffix}",
            )
            assert included["charge_minor"] == 0
            assert overage["charge_minor"] == 50
            assert replay == overage
            wallet = await session.scalar(
                select(BillingWallet).where(
                    BillingWallet.organization_id == organization.id
                )
            )
            assert wallet.balance_minor == 950

            issued = await billing.issue_license(
                session, owner, organization.id, seats=5
            )
            assert issued["license_key"].startswith("AIONEX-")
            stored_license = await session.get(BillingLicense, issued["id"])
            assert issued["license_key"] not in json.dumps(
                billing.license_snapshot(stored_license)
            )
            assert (
                stored_license.key_hash
                == hashlib.sha256(issued["license_key"].encode()).hexdigest()
            )

            invoice = BillingInvoice(
                organization_id=organization.id,
                provider="internal",
                number=f"INV-RF-{suffix}",
                status="paid",
                currency="USD",
                subtotal_minor=500,
                total_minor=500,
                amount_paid_minor=500,
                line_items=[],
                paid_at=datetime.now(UTC),
            )
            session.add(invoice)
            await session.flush()
            transaction = BillingTransaction(
                organization_id=organization.id,
                user_id=user.id,
                invoice_id=invoice.id,
                provider="internal",
                external_reference=f"internal-{suffix}",
                transaction_type="payment",
                status="succeeded",
                amount_minor=500,
                currency="USD",
                idempotency_key=f"paid-{suffix}",
                completed_at=datetime.now(UTC),
            )
            session.add(transaction)
            await session.commit()
            refund = await billing.owner_refund(
                session,
                owner,
                transaction.id,
                amount_minor=200,
                reason="Test refund",
                idempotency_key=f"refund-{suffix}",
            )
            replay_refund = await billing.owner_refund(
                session,
                owner,
                transaction.id,
                amount_minor=200,
                reason="Test refund",
                idempotency_key=f"refund-{suffix}",
            )
            assert refund == replay_refund
            assert refund["status"] == "succeeded"
            assert await session.scalar(select(func.count(BillingRefund.id))) == 1
            wallet = await session.scalar(
                select(BillingWallet).where(
                    BillingWallet.organization_id == organization.id
                )
            )
            assert wallet.balance_minor == 1150
    finally:
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_manual_checkout_coupon_settlement_and_reconciliation_are_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="manual")
    owner = actor(user, organization, ["*"])
    plan_code = f"manual-{suffix}"

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Manual",
                status="active",
                default_currency="USD",
                limits={"projects": 12},
                entitlements=["projects.core", "billing.manual"],
                metering={},
                source_version=1,
                source_hash="e" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=2000,
                currency="USD",
                enabled=True,
                provider="manual",
            )
            session.add(price)
            session.add(
                BillingAccount(
                    organization_id=organization.id,
                    plan_id=plan.id,
                    status="active",
                    licensed_seats=1,
                    limits=plan.limits,
                    entitlements=plan.entitlements,
                )
            )
            await session.commit()
            coupon = await billing.owner_create_coupon(
                session,
                owner,
                code=f"OFF{suffix}",
                discount_type="fixed",
                percent_off=None,
                amount_off_minor=200,
                currency="USD",
                max_redemptions=1,
                expires_at=now_plus(),
            )
            checkout = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=plan_code,
                period_code="monthly",
                coupon_code=coupon["code"],
                billing_country=None,
                idempotency_key=f"manual-checkout-{suffix}",
            )
            assert checkout["status"] == "awaiting_payment"
            assert checkout["checkout_url"] is None
            assert checkout["summary"]["instructions"]["type"] == "manual_invoice"
            assert checkout["summary"]["total_minor"] == 1800
            stored_coupon = await session.scalar(
                select(BillingCoupon).where(BillingCoupon.code == coupon["code"])
            )
            assert stored_coupon.redeemed_count == 1
            assert (
                await session.scalar(select(func.count(BillingCouponRedemption.id)))
                == 1
            )
            transaction = await session.scalar(
                select(BillingTransaction).where(
                    BillingTransaction.organization_id == organization.id,
                    BillingTransaction.status == "pending",
                )
            )
            settled = await billing.owner_settle_transaction(
                session,
                owner,
                transaction.id,
                succeeded=True,
                external_reference=f"receipt-{suffix}",
                note="Verified bank receipt",
            )
            replay = await billing.owner_settle_transaction(
                session,
                owner,
                transaction.id,
                succeeded=True,
                external_reference=f"receipt-{suffix}",
                note="Replay",
            )
            assert settled == replay
            assert settled["status"] == "succeeded"
            invoice = await session.get(BillingInvoice, transaction.invoice_id)
            subscription = await session.scalar(
                select(BillingSubscription).where(
                    BillingSubscription.organization_id == organization.id
                )
            )
            account = await session.scalar(
                select(BillingAccount).where(
                    BillingAccount.organization_id == organization.id
                )
            )
            assert invoice.status == "paid" and invoice.amount_paid_minor == 1800
            assert subscription is not None and subscription.status == "active"
            assert account.limits == {"projects": 12}
    finally:
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_stripe_cancellation_updates_provider_before_local_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="professional")
    calls: list[httpx.Request] = []

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "STRIPE_SECRET_KEY", "sk_test_phase29d")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == f"/v1/subscriptions/sub_{suffix}"
        assert request.method == "POST"
        assert b"cancel_at_period_end=true" in request.content
        return httpx.Response(200, json={"id": f"sub_{suffix}"})

    plan_code = f"cancel-{suffix}"
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Cancel",
                status="active",
                default_currency="USD",
                limits={},
                entitlements=[],
                metering={},
                source_version=1,
                source_hash="f" * 64,
            )
            session.add(plan)
            await session.flush()
            session.add(
                BillingAccount(
                    organization_id=organization.id,
                    plan_id=plan.id,
                    status="active",
                    licensed_seats=1,
                )
            )
            subscription = BillingSubscription(
                organization_id=organization.id,
                plan_id=plan.id,
                provider="stripe",
                external_reference=f"sub_{suffix}",
                status="active",
            )
            session.add(subscription)
            await session.commit()
            result = await billing.cancel_subscription(
                session,
                actor(user, organization),
                immediately=False,
                transport=httpx.MockTransport(handler),
            )
            assert len(calls) == 1
            assert result["cancel_at_period_end"] is True
            assert result["status"] == "active"
    finally:
        await cleanup(organization.id, [plan_code])


def now_plus() -> datetime:
    return datetime.now(UTC) + timedelta(days=30)


@pytest.mark.asyncio
async def test_billing_api_is_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    one = uuid4().hex[:12]
    two = uuid4().hex[:12]
    organization_one, user_one = await identity(one)
    organization_two, user_two = await identity(two)

    async def no_sync(_session):
        return {"source_version": 1, "plans": [], "providers": []}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[current_user] = lambda: actor(user_one, organization_one)
    try:
        async with SessionLocal() as session:
            free_plan = BillingPlan(
                code=f"free-{one}",
                name="Free",
                status="active",
                default_currency="USD",
                limits={},
                entitlements=[],
                metering={},
                source_version=1,
                source_hash="d" * 64,
            )
            session.add(free_plan)
            await session.flush()
            session.add_all(
                [
                    BillingAccount(
                        organization_id=organization_one.id,
                        plan_id=free_plan.id,
                        status="active",
                        licensed_seats=1,
                    ),
                    BillingAccount(
                        organization_id=organization_two.id,
                        plan_id=free_plan.id,
                        status="active",
                        licensed_seats=1,
                    ),
                    BillingInvoice(
                        organization_id=organization_one.id,
                        provider="internal",
                        number=f"INV-{one}",
                        status="paid",
                        currency="USD",
                        total_minor=100,
                        amount_paid_minor=100,
                        line_items=[],
                    ),
                    BillingInvoice(
                        organization_id=organization_two.id,
                        provider="internal",
                        number=f"INV-{two}",
                        status="paid",
                        currency="USD",
                        total_minor=999,
                        amount_paid_minor=999,
                        line_items=[],
                    ),
                ]
            )
            await session.commit()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/billing/invoices")
            assert response.status_code == 200, response.text
            assert [item["number"] for item in response.json()] == [f"INV-{one}"]
            owner = await client.get("/api/v1/billing/owner/overview")
            assert owner.status_code == 403
    finally:
        await cleanup(organization_one.id, [f"free-{one}"])
        await cleanup(organization_two.id, [])


@pytest.mark.asyncio
async def test_offline_checkout_reserves_coupon_and_owner_settlement_activates_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="manual")
    plan_code = f"manual-{suffix}"

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Manual",
                status="active",
                default_currency="USD",
                limits={"projects": 9},
                entitlements=["projects.core", "billing.offline"],
                metering={},
                source_version=1,
                source_hash="e" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=1200,
                currency="USD",
                enabled=True,
                provider="manual",
            )
            session.add(price)
            session.add(
                BillingAccount(
                    organization_id=organization.id,
                    plan_id=plan.id,
                    status="active",
                    licensed_seats=1,
                    limits={},
                    entitlements=[],
                )
            )
            coupon = BillingCoupon(
                code=f"ONCE{suffix}".upper(),
                discount_type="percent",
                percent_off_basis_points=1000,
                max_redemptions=1,
            )
            session.add(coupon)
            await session.commit()

            checkout = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=plan_code,
                period_code="monthly",
                coupon_code=coupon.code,
                idempotency_key=f"manual-checkout-{suffix}",
            )
            assert checkout["provider"] == "manual"
            assert checkout["status"] == "awaiting_payment"
            assert checkout["checkout_url"] is None
            assert checkout["summary"]["discount_minor"] == 120
            assert checkout["summary"]["total_minor"] == 1080
            await session.refresh(coupon)
            assert coupon.redeemed_count == 1

            with pytest.raises(Exception) as duplicate_coupon:
                await billing.create_checkout(
                    session,
                    actor(user, organization),
                    plan_code=plan_code,
                    period_code="monthly",
                    coupon_code=coupon.code,
                    idempotency_key=f"manual-second-{suffix}",
                )
            assert getattr(duplicate_coupon.value, "status_code", None) == 422

            transaction = await session.scalar(
                select(BillingTransaction).where(
                    BillingTransaction.transaction_metadata["checkout_id"].as_string()
                    == checkout["id"]
                )
            )
            assert transaction is not None and transaction.status == "pending"
            settled = await billing.owner_settle_transaction(
                session,
                actor(user, organization, ["*"]),
                transaction.id,
                succeeded=True,
                external_reference=f"bank-{suffix}",
                note="Verified offline payment",
            )
            assert settled["status"] == "succeeded"
            account = await session.scalar(
                select(BillingAccount).where(
                    BillingAccount.organization_id == organization.id
                )
            )
            assert account is not None
            assert account.plan_id == plan.id
            assert account.limits == plan.limits
            assert account.entitlements == plan.entitlements
    finally:
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_stripe_cancellation_is_forwarded_and_owner_overview_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="professional")
    plan_code = f"cancel-{suffix}"
    calls: list[httpx.Request] = []

    async def no_sync(_session):
        return {"source_version": 1, "plans": [], "providers": []}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "STRIPE_SECRET_KEY", "sk_test_phase29d")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": f"sub_{suffix}"})

    transport = httpx.MockTransport(handler)
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="Cancellation",
                status="active",
                default_currency="USD",
                limits={},
                entitlements=["projects.core"],
                metering={},
                source_version=1,
                source_hash="f" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=1000,
                currency="USD",
                enabled=True,
                provider="stripe",
                provider_reference="price_cancel",
            )
            session.add(price)
            account = BillingAccount(
                organization_id=organization.id,
                plan_id=plan.id,
                status="active",
                licensed_seats=1,
            )
            session.add(account)
            await session.flush()
            from app.db.models import BillingSubscription

            subscription = BillingSubscription(
                organization_id=organization.id,
                plan_id=plan.id,
                price_id=price.id,
                provider="stripe",
                external_reference=f"sub_{suffix}",
                status="active",
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(subscription)
            session.add(
                BillingTaxRate(
                    code=f"VAT{suffix[:6]}".upper(),
                    country_code="QZ",
                    percentage_basis_points=500,
                )
            )
            wallet = BillingWallet(
                organization_id=organization.id, currency="USD", balance_minor=750
            )
            session.add(wallet)
            await session.flush()
            usage = BillingUsageRecord(
                organization_id=organization.id,
                metric="tokens",
                quantity=10,
                included_quantity=0,
                billable_quantity=10,
                charge_minor=25,
                currency="USD",
                period_start=datetime.now(UTC).replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                ),
                period_end=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(usage)
            await session.commit()

            result = await billing.cancel_subscription(
                session,
                actor(user, organization),
                immediately=False,
                transport=transport,
            )
            assert result["cancel_at_period_end"] is True
            assert len(calls) == 1
            assert calls[0].method == "POST"
            assert calls[0].url.path.endswith(f"/v1/subscriptions/sub_{suffix}")
            assert b"cancel_at_period_end=true" in calls[0].content

            overview = await billing.owner_overview(session)
            assert any(
                item["organization_id"] == organization.id
                for item in overview["accounts"]
            )
            assert any(
                item["organization_id"] == organization.id
                for item in overview["wallets"]
            )
            assert any(
                item["organization_id"] == organization.id for item in overview["usage"]
            )
            assert any(
                item["country_code"] == "QZ"
                and item["code"] == f"VAT{suffix[:6]}".upper()
                for item in overview["tax_rates"]
            )
            assert "reconciliation_runs" in overview
            assert overview["summary"]["wallet_balance_minor"] >= 750
            assert overview["summary"]["usage_charge_minor"] >= 25
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(BillingTaxRate).where(
                    BillingTaxRate.country_code == "QZ",
                    BillingTaxRate.code == f"VAT{suffix[:6]}".upper(),
                )
            )
            await session.commit()
        await cleanup(organization.id, [plan_code])


@pytest.mark.asyncio
async def test_paypal_checkout_webhook_verification_and_refund_use_oauth_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix, plan="paypal")
    plan_code = f"paypal-{suffix}"
    calls: list[tuple[str, str]] = []

    async def no_sync(_session):
        return {"source_version": 1}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "PAYPAL_CLIENT_ID", "phase29d-client")
    monkeypatch.setattr(billing.settings, "PAYPAL_CLIENT_SECRET", "phase29d-secret")
    monkeypatch.setattr(billing.settings, "PAYPAL_WEBHOOK_ID", "phase29d-webhook")
    monkeypatch.setattr(billing.settings, "PAYMENTS_ENVIRONMENT", "sandbox")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/oauth2/token":
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "oauth-phase29d"})
        assert request.headers.get("Authorization") == "Bearer oauth-phase29d"
        if request.url.path == "/v1/billing/subscriptions":
            assert (
                request.headers.get("PayPal-Request-Id") == f"paypal-checkout-{suffix}"
            )
            return httpx.Response(
                201,
                json={
                    "id": f"sub_{suffix}",
                    "links": [
                        {
                            "rel": "approve",
                            "href": f"https://paypal.test/approve/{suffix}",
                        }
                    ],
                },
            )
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            payload = json.loads(request.content)
            assert payload["webhook_id"] == "phase29d-webhook"
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        if request.url.path == f"/v2/payments/captures/capture_{suffix}/refund":
            assert request.headers.get("PayPal-Request-Id") == f"paypal-refund-{suffix}"
            return httpx.Response(201, json={"id": f"refund_{suffix}"})
        return httpx.Response(404, json={"path": request.url.path})

    transport = httpx.MockTransport(handler)
    try:
        async with SessionLocal() as session:
            plan = BillingPlan(
                code=plan_code,
                name="PayPal",
                status="active",
                default_currency="USD",
                limits={"projects": 4},
                entitlements=["projects.core"],
                metering={},
                source_version=1,
                source_hash="9" * 64,
            )
            session.add(plan)
            await session.flush()
            price = BillingPrice(
                plan_id=plan.id,
                period_code="monthly",
                months=1,
                amount_minor=1900,
                currency="USD",
                enabled=True,
                provider="paypal",
                provider_reference=f"P-{suffix}",
            )
            session.add(price)
            session.add(
                BillingAccount(
                    organization_id=organization.id,
                    plan_id=plan.id,
                    status="active",
                    licensed_seats=1,
                    limits=plan.limits,
                    entitlements=plan.entitlements,
                )
            )
            await session.commit()

            checkout = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=plan_code,
                period_code="monthly",
                idempotency_key=f"paypal-checkout-{suffix}",
                transport=transport,
            )
            assert checkout["provider"] == "paypal"
            assert checkout["status"] == "created"
            assert checkout["checkout_url"] == f"https://paypal.test/approve/{suffix}"

            webhook_payload = {
                "id": f"WH-{suffix}",
                "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
                "resource": {"id": f"sub_{suffix}"},
            }
            raw = json.dumps(webhook_payload, separators=(",", ":")).encode()
            verified = await billing.verify_webhook(
                "paypal",
                raw,
                {
                    "PayPal-Auth-Algo": "SHA256withRSA",
                    "PayPal-Cert-Url": "https://paypal.test/cert.pem",
                    "PayPal-Transmission-Id": f"transmission-{suffix}",
                    "PayPal-Transmission-Sig": "signed-value",
                    "PayPal-Transmission-Time": datetime.now(UTC).isoformat(),
                },
                transport=transport,
            )
            assert verified == webhook_payload

            invoice = BillingInvoice(
                organization_id=organization.id,
                provider="paypal",
                number=f"INV-PP-{suffix}",
                status="paid",
                currency="USD",
                subtotal_minor=1900,
                total_minor=1900,
                amount_paid_minor=1900,
                line_items=[],
                paid_at=datetime.now(UTC),
            )
            session.add(invoice)
            await session.flush()
            transaction = BillingTransaction(
                organization_id=organization.id,
                user_id=user.id,
                invoice_id=invoice.id,
                provider="paypal",
                external_reference=f"capture_{suffix}",
                transaction_type="payment",
                status="succeeded",
                amount_minor=1900,
                currency="USD",
                idempotency_key=f"paypal-paid-{suffix}",
                completed_at=datetime.now(UTC),
            )
            session.add(transaction)
            await session.commit()

            refund = await billing.owner_refund(
                session,
                actor(user, organization, ["*"]),
                transaction.id,
                amount_minor=500,
                reason="PayPal regression coverage",
                idempotency_key=f"paypal-refund-{suffix}",
                transport=transport,
            )
            assert refund["status"] == "succeeded"
            assert refund["amount_minor"] == 500
            assert calls.count(("POST", "/v1/oauth2/token")) == 3
            assert ("POST", "/v1/billing/subscriptions") in calls
            assert ("POST", "/v1/notifications/verify-webhook-signature") in calls
            assert (
                "POST",
                f"/v2/payments/captures/capture_{suffix}/refund",
            ) in calls
    finally:
        await cleanup(organization.id, [plan_code])


def test_provider_readiness_accepts_restricted_stripe_live_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing.settings, "PAYMENTS_ENVIRONMENT", "live")
    monkeypatch.setattr(billing.settings, "STRIPE_SECRET_KEY", "rk_live_phase29d")
    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", "whsec_phase29d")

    stripe = next(
        item for item in billing.provider_readiness() if item["id"] == "stripe"
    )

    assert stripe["configured"] is True
    assert stripe["mode"] == "live"
    assert stripe["status"] == "ready"
    assert "apple_pay" not in stripe["capabilities"]
