"""P5.3 Stripe subscriptions end to end, with every Stripe API call mocked.

Owner decision 2026-11-06: no live money or live accounts before the
pre-launch window, so checkout, webhooks, lifecycle and entitlement
propagation are proven here against ``httpx.MockTransport`` and signed
synthetic events only.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.core.auth import UserRecord, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    BillingAccount,
    BillingCheckoutSession,
    BillingCoupon,
    BillingInvoice,
    BillingPlan,
    BillingPrice,
    BillingRefund,
    BillingSubscription,
    BillingTaxRate,
    BillingTransaction,
    BillingWebhookEvent,
    Notification,
    NotificationDelivery,
    Organization,
    Role,
    User,
)
from app.services import (
    ads_entitlement,
    aionex_ai_plan_signal,
    billing,
    security_entitlement,
    stripe_billing,
    three_d_product,
)

BACKEND = Path(__file__).resolve().parents[1]
WEBHOOK_SECRET = "whsec_p5_stripe"
DAY = 86_400


# --------------------------------------------------------------------- fixtures


def actor(user: User, organization: Organization) -> UserRecord:
    return UserRecord(
        id=user.id,
        email=user.email,
        name=user.name,
        role="Owner",
        password_hash=user.password_hash,
        organization_id=organization.id,
        organization_name=organization.name,
        organization_plan=organization.plan,
        permissions=["billing:read", "billing:write"],
    )


async def identity(suffix: str) -> tuple[Organization, User]:
    organization = Organization(
        name=f"Stripe P5 {suffix}", slug=f"stripe-p5-{suffix}", plan="free", status="active"
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id, name=f"Stripe Owner {suffix}", status="active"
        )
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"stripe-p5-{suffix}@example.com",
            name="Stripe P5",
            password_hash=pwd_context.hash(f"StripeP5!{suffix}"),
            status="active",
        )
        session.add(user)
        await session.commit()
        return organization, user


class Catalog:
    """Free, Pro (monthly + yearly) and Top (monthly) plans for one test."""

    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.pro_code = f"pro-p5-{suffix}"
        self.top_code = f"top-p5-{suffix}"
        self.pro_monthly = f"price_pro_m_{suffix}"
        self.pro_yearly = f"price_pro_y_{suffix}"
        self.top_monthly = f"price_top_m_{suffix}"
        self.created_free = False
        self.free_id = ""
        self.pro_id = ""
        self.top_id = ""

    async def create(self, organization: Organization, *, customer: str | None = None) -> None:
        async with SessionLocal() as session:
            free = await session.scalar(select(BillingPlan).where(BillingPlan.code == "free"))
            if free is None:
                free = BillingPlan(
                    code="free",
                    name="Free",
                    status="active",
                    default_currency="USD",
                    limits={},
                    entitlements=["projects.core"],
                    metering={},
                    source_version=1,
                    source_hash="0" * 64,
                )
                session.add(free)
                self.created_free = True
            pro = BillingPlan(
                code=self.pro_code,
                name="Pro",
                status="active",
                default_currency="USD",
                limits={"projects": 50},
                entitlements=["projects.core"],
                metering={},
                source_version=1,
                source_hash="1" * 64,
            )
            top = BillingPlan(
                code=self.top_code,
                name="Top",
                status="active",
                default_currency="USD",
                limits={"projects": 500},
                entitlements=[
                    "projects.core",
                    "security.web_scanning",
                    "ads.manage",
                    billing.THREE_D_BUSINESS_ENTITLEMENT,
                ],
                metering={},
                source_version=1,
                source_hash="2" * 64,
            )
            session.add_all([pro, top])
            await session.flush()
            session.add_all(
                [
                    BillingPrice(
                        plan_id=pro.id,
                        period_code="monthly",
                        months=1,
                        amount_minor=1000,
                        currency="USD",
                        enabled=True,
                        provider="stripe",
                        provider_reference=self.pro_monthly,
                        price_metadata={},
                    ),
                    BillingPrice(
                        plan_id=pro.id,
                        period_code="yearly",
                        months=12,
                        amount_minor=10000,
                        currency="USD",
                        enabled=True,
                        provider="stripe",
                        provider_reference=self.pro_yearly,
                        price_metadata={"trial_days": 7},
                    ),
                    BillingPrice(
                        plan_id=top.id,
                        period_code="monthly",
                        months=1,
                        amount_minor=5000,
                        currency="USD",
                        enabled=True,
                        provider="stripe",
                        provider_reference=self.top_monthly,
                        price_metadata={},
                    ),
                ]
            )
            session.add(
                BillingAccount(
                    organization_id=organization.id,
                    plan_id=free.id,
                    status="active",
                    licensed_seats=1,
                    limits=dict(free.limits or {}),
                    entitlements=[item for item in (free.entitlements or []) if item != "*"],
                    provider_customers={"stripe": customer} if customer else {},
                )
            )
            await session.commit()
            self.free_id, self.pro_id, self.top_id = free.id, pro.id, top.id

    async def cleanup(self, organization_id: str) -> None:
        async with SessionLocal() as session:
            await session.execute(
                delete(BillingWebhookEvent).where(
                    BillingWebhookEvent.external_event_id.like(f"evt_{self.suffix}%")
                )
            )
            await session.execute(delete(Organization).where(Organization.id == organization_id))
            await session.flush()
            for code in (self.pro_code, self.top_code):
                plan = await session.scalar(select(BillingPlan).where(BillingPlan.code == code))
                if plan is not None:
                    await session.delete(plan)
            if self.created_free:
                free = await session.scalar(select(BillingPlan).where(BillingPlan.code == "free"))
                if free is not None:
                    await session.delete(free)
            await session.commit()


@pytest.fixture
def stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sync(_session):
        return {"source_version": 1, "plans": [], "providers": []}

    monkeypatch.setattr(billing, "sync_catalog", no_sync)
    monkeypatch.setattr(billing.settings, "STRIPE_SECRET_KEY", "sk_test_p5_stripe")
    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(billing.settings, "PAYMENTS_ENVIRONMENT", "sandbox")
    monkeypatch.setattr(billing.settings, "PAYMENTS_PORTAL_BASE_URL", "https://ai.vip-e.net")
    monkeypatch.setattr(billing.settings, "STRIPE_AUTOMATIC_TAX", False)
    monkeypatch.setattr(billing.settings, "STRIPE_TAX_RATES", "")
    monkeypatch.setattr(billing.settings, "STRIPE_PORTAL_CONFIGURATION_ID", None)


def signed(payload: dict, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    stamp = str(timestamp if timestamp is not None else int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"Stripe-Signature": f"t={stamp},v1={signature}"}


def event(event_id: str, event_type: str, obj: dict, created: int) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "created": created,
        "data": {"object": obj},
    }


async def deliver(session, payload: dict) -> dict:
    raw, headers = signed(payload)
    verified = await billing.verify_webhook("stripe", raw, headers)
    return await billing.process_webhook_event(session, "stripe", verified, raw)


def subscription_object(
    suffix: str,
    *,
    status: str,
    price: str,
    start: int,
    end: int,
    organization_id: str,
    cancel_at_period_end: bool = False,
    legacy_period: bool = False,
    checkout_id: str | None = None,
) -> dict:
    item: dict = {"id": f"si_{suffix}", "price": {"id": price}}
    obj: dict = {
        "id": f"sub_{suffix}",
        "object": "subscription",
        "status": status,
        "customer": f"cus_{suffix}",
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": None,
        "trial_end": None,
        "canceled_at": None,
        "ended_at": end if status == "canceled" else None,
        "metadata": {"organization_id": organization_id, **({"checkout_id": checkout_id} if checkout_id else {})},
        "items": {"data": [item]},
    }
    if legacy_period:
        obj["current_period_start"] = start
        obj["current_period_end"] = end
    else:
        item["current_period_start"] = start
        item["current_period_end"] = end
    return obj


def invoice_object(
    suffix: str,
    number: str,
    *,
    amount: int,
    paid: bool,
    reason: str,
    price: str,
    start: int,
    end: int,
    attempt: int = 1,
) -> dict:
    return {
        "id": f"in_{suffix}_{number}",
        "object": "invoice",
        "customer": f"cus_{suffix}",
        "subscription": f"sub_{suffix}",
        "billing_reason": reason,
        "number": f"P5-{suffix}-{number}",
        "currency": "usd",
        "subtotal": amount,
        "total": amount,
        "tax": 0,
        "amount_due": amount,
        "amount_paid": amount if paid else 0,
        "attempt_count": attempt,
        "payment_intent": f"pi_{suffix}_{number}",
        "hosted_invoice_url": f"https://invoice.stripe.com/i/test_{suffix}_{number}",
        "invoice_pdf": f"https://pay.stripe.com/invoice/test_{suffix}_{number}/pdf",
        "status_transitions": {"paid_at": start if paid else None},
        "lines": {
            "data": [
                {
                    "description": "Subscription",
                    "amount": amount,
                    "quantity": 1,
                    "price": {"id": price},
                    "period": {"start": start, "end": end},
                }
            ]
        },
    }


async def account_of(session, organization_id: str) -> BillingAccount:
    session.expire_all()
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.organization_id == organization_id)
    )
    assert account is not None
    return account


async def security_level(session, user_actor: UserRecord, top_code: str) -> str | None:
    access = await security_entitlement.resolve_access(
        session,
        user_actor,
        policy={"subscription_access": {"enabled": True, "plan_codes": [top_code]}},
    )
    return access.level


# --------------------------------------------------------------------- checkout


@pytest.mark.asyncio
async def test_checkout_session_targets_portal_reuses_customer_and_maps_coupon(
    stripe_settings: None,
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)
    catalog = Catalog(suffix)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/v1/checkout/sessions"
        return httpx.Response(
            200,
            json={
                "id": f"cs_{suffix}_{len(calls)}",
                "url": f"https://checkout.stripe.com/c/pay/cs_{suffix}_{len(calls)}",
                "expires_at": int(time.time()) + 1800,
            },
        )

    transport = httpx.MockTransport(handler)
    try:
        await catalog.create(organization, customer=f"cus_{suffix}")
        async with SessionLocal() as session:
            session.add(
                BillingCoupon(
                    code=f"P5{suffix}".upper(),
                    discount_type="percent",
                    percent_off_basis_points=2000,
                    coupon_metadata={"stripe_coupon": f"co_{suffix}"},
                )
            )
            await session.commit()
            first = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=catalog.pro_code,
                period_code="yearly",
                coupon_code=f"P5{suffix}".upper(),
                idempotency_key=f"p5-checkout-{suffix}",
                locale="ar",
                transport=transport,
            )
            replay = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=catalog.pro_code,
                period_code="yearly",
                coupon_code=f"P5{suffix}".upper(),
                idempotency_key=f"p5-checkout-{suffix}",
                locale="ar",
                transport=transport,
            )
            assert replay == first
            assert len(calls) == 1
            request = calls[0]
            assert request.headers["Idempotency-Key"] == f"p5-checkout-{suffix}"
            body = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            assert body["mode"] == "subscription"
            assert body["success_url"] == (
                "https://ai.vip-e.net/ar/billing?checkout=success&session_id={CHECKOUT_SESSION_ID}"
            )
            assert body["cancel_url"] == "https://ai.vip-e.net/ar/billing?checkout=cancelled"
            assert body["customer"] == f"cus_{suffix}"
            assert "customer_email" not in body
            assert body["line_items[0][price]"] == catalog.pro_yearly
            assert body["discounts[0][coupon]"] == f"co_{suffix}"
            assert "allow_promotion_codes" not in body
            assert body["subscription_data[trial_period_days]"] == "7"
            assert body["subscription_data[metadata][organization_id]"] == organization.id
            assert body["subscription_data[metadata][checkout_id]"] == first["id"]
            # Not a Checkout Session parameter; Stripe would reject the request.
            assert "automatic_payment_methods[enabled]" not in body
            assert first["summary"]["discount_minor"] == 2000
            assert first["summary"]["total_minor"] == 8000
            assert first["summary"]["locale"] == "ar"

            # Unknown locales fall back to English; no stored customer means
            # Checkout creates one from the e-mail.
            account = await account_of(session, organization.id)
            account.provider_customers = {}
            await session.commit()
            second = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=catalog.pro_code,
                period_code="monthly",
                idempotency_key=f"p5-checkout-b-{suffix}",
                locale="xx-YY",
                transport=transport,
            )
            assert second["status"] == "created"
            body = {key: values[0] for key, values in parse_qs(calls[1].content.decode()).items()}
            assert body["success_url"].startswith("https://ai.vip-e.net/en/billing?checkout=success")
            assert body["customer_email"] == user.email
            assert body["allow_promotion_codes"] == "true"
            assert calls[1].headers["Idempotency-Key"] == f"p5-checkout-b-{suffix}"
    finally:
        await catalog.cleanup(organization.id)
        async with SessionLocal() as session:
            await session.execute(delete(BillingCoupon).where(BillingCoupon.code == f"P5{suffix}".upper()))
            await session.commit()


@pytest.mark.asyncio
async def test_card_checkout_rejects_unmapped_coupon_and_tax_and_blocks_second_subscription(
    stripe_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)
    catalog = Catalog(suffix)
    calls: list[httpx.Request] = []
    tax_code = f"VATP5{suffix[:6]}".upper()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"id": f"cs_{suffix}_{len(calls)}", "url": "https://checkout.stripe.com/c/pay/x"},
        )

    transport = httpx.MockTransport(handler)
    try:
        await catalog.create(organization)
        async with SessionLocal() as session:
            session.add(
                BillingCoupon(code=f"RAW{suffix}".upper(), discount_type="percent", percent_off_basis_points=1000)
            )
            session.add(
                BillingTaxRate(code=tax_code, country_code="QY", percentage_basis_points=500, inclusive=False)
            )
            await session.commit()
            with pytest.raises(HTTPException) as coupon_error:
                await billing.create_checkout(
                    session,
                    actor(user, organization),
                    plan_code=catalog.pro_code,
                    period_code="monthly",
                    coupon_code=f"RAW{suffix}".upper(),
                    idempotency_key=f"p5-coupon-{suffix}",
                    transport=transport,
                )
            assert coupon_error.value.status_code == 422
            with pytest.raises(HTTPException) as tax_error:
                await billing.create_checkout(
                    session,
                    actor(user, organization),
                    plan_code=catalog.pro_code,
                    period_code="monthly",
                    billing_country="QY",
                    idempotency_key=f"p5-tax-{suffix}",
                    transport=transport,
                )
            assert tax_error.value.status_code == 409
            assert calls == []

            monkeypatch.setattr(billing.settings, "STRIPE_TAX_RATES", f"{tax_code}=txr_{suffix}")
            mapped = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=catalog.pro_code,
                period_code="monthly",
                billing_country="QY",
                idempotency_key=f"p5-tax-mapped-{suffix}",
                transport=transport,
            )
            body = {key: values[0] for key, values in parse_qs(calls[-1].content.decode()).items()}
            assert body["line_items[0][tax_rates][0]"] == f"txr_{suffix}"
            assert mapped["summary"]["tax_minor"] == 50

            monkeypatch.setattr(billing.settings, "STRIPE_AUTOMATIC_TAX", True)
            automatic = await billing.create_checkout(
                session,
                actor(user, organization),
                plan_code=catalog.pro_code,
                period_code="monthly",
                billing_country="QY",
                idempotency_key=f"p5-tax-auto-{suffix}",
                transport=transport,
            )
            body = {key: values[0] for key, values in parse_qs(calls[-1].content.decode()).items()}
            assert body["automatic_tax[enabled]"] == "true"
            assert body["billing_address_collection"] == "required"
            assert "line_items[0][tax_rates][0]" not in body
            assert automatic["summary"]["tax_minor"] == 0
            assert automatic["summary"]["tax_mode"] == "stripe_automatic"

            session.add(
                BillingSubscription(
                    organization_id=organization.id,
                    plan_id=catalog.pro_id,
                    provider="stripe",
                    external_reference=f"sub_{suffix}",
                    status="past_due",
                )
            )
            await session.commit()
            with pytest.raises(HTTPException) as exists:
                await billing.create_checkout(
                    session,
                    actor(user, organization),
                    plan_code=catalog.top_code,
                    period_code="monthly",
                    idempotency_key=f"p5-second-{suffix}",
                    transport=transport,
                )
            assert exists.value.status_code == 409
            assert exists.value.detail["code"] == "SUBSCRIPTION_EXISTS"
    finally:
        await catalog.cleanup(organization.id)
        async with SessionLocal() as session:
            await session.execute(delete(BillingCoupon).where(BillingCoupon.code == f"RAW{suffix}".upper()))
            await session.execute(delete(BillingTaxRate).where(BillingTaxRate.code == tax_code))
            await session.commit()


# --------------------------------------------------------------------- signatures


@pytest.mark.asyncio
async def test_stripe_signature_failures_are_rejected(stripe_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = event(f"evt_sig_{uuid4().hex[:8]}", "invoice.paid", {"id": "in_x"}, int(time.time()))
    raw, headers = signed(payload)
    assert await billing.verify_webhook("stripe", raw, headers) == payload

    _, wrong = signed(payload, secret="whsec_other")
    with pytest.raises(HTTPException) as bad_secret:
        await billing.verify_webhook("stripe", raw, wrong)
    assert bad_secret.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        await billing.verify_webhook("stripe", raw, {})
    assert missing.value.status_code == 400

    _, stale = signed(payload, timestamp=int(time.time()) - 3600)
    with pytest.raises(HTTPException) as too_old:
        await billing.verify_webhook("stripe", raw, stale)
    assert too_old.value.status_code == 400

    tampered = raw.replace(b"in_x", b"in_y")
    with pytest.raises(HTTPException) as body_changed:
        await billing.verify_webhook("stripe", tampered, headers)
    assert body_changed.value.status_code == 400

    # Secret rotation: Stripe may send several v1 values; one valid is enough.
    stamp = headers["Stripe-Signature"].split(",")[0]
    rotated = {"Stripe-Signature": f"{stamp},v1={'0' * 64},{headers['Stripe-Signature'].split(',')[1]}"}
    assert await billing.verify_webhook("stripe", raw, rotated) == payload

    monkeypatch.setattr(billing.settings, "STRIPE_WEBHOOK_SECRET", None)
    with pytest.raises(HTTPException) as unconfigured:
        await billing.verify_webhook("stripe", raw, headers)
    assert unconfigured.value.status_code == 503


# --------------------------------------------------------------------- webhooks


@pytest.mark.asyncio
async def test_checkout_webhooks_out_of_order_receipt_and_entitlements(stripe_settings: None) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)
    catalog = Catalog(suffix)
    base = int(time.time())
    start, end = base - 60, base + 30 * DAY

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": f"cs_{suffix}", "url": f"https://checkout.stripe.com/c/pay/cs_{suffix}"}
        )

    try:
        await catalog.create(organization)
        user_actor = actor(user, organization)
        async with SessionLocal() as session:
            checkout = await billing.create_checkout(
                session,
                user_actor,
                plan_code=catalog.top_code,
                period_code="monthly",
                idempotency_key=f"p5-flow-{suffix}",
                locale="en",
                transport=httpx.MockTransport(handler),
            )
            assert await security_level(session, user_actor, catalog.top_code) is None

            # 1. The update (active) arrives before the creation (incomplete).
            updated = await deliver(
                session,
                event(
                    f"evt_{suffix}_updated",
                    "customer.subscription.updated",
                    subscription_object(
                        suffix,
                        status="active",
                        price=catalog.top_monthly,
                        start=start,
                        end=end,
                        organization_id=organization.id,
                        checkout_id=checkout["id"],
                    ),
                    base + 5,
                ),
            )
            assert updated["status"] == "processed"
            created = await deliver(
                session,
                event(
                    f"evt_{suffix}_created",
                    "customer.subscription.created",
                    subscription_object(
                        suffix,
                        status="incomplete",
                        price=catalog.top_monthly,
                        start=start,
                        end=end,
                        organization_id=organization.id,
                        checkout_id=checkout["id"],
                    ),
                    base,
                ),
            )
            assert created["status"] == "stale"
            session.expire_all()
            subscription = await session.scalar(
                select(BillingSubscription).where(BillingSubscription.external_reference == f"sub_{suffix}")
            )
            assert subscription is not None and subscription.status == "active"
            assert subscription.plan_id == catalog.top_id
            assert int(billing._as_utc(subscription.current_period_end).timestamp()) == end

            # 2. Checkout completion links the checkout and stores the customer.
            completed = await deliver(
                session,
                event(
                    f"evt_{suffix}_checkout",
                    "checkout.session.completed",
                    {
                        "id": f"cs_{suffix}",
                        "object": "checkout.session",
                        "mode": "subscription",
                        "payment_status": "paid",
                        "client_reference_id": checkout["id"],
                        "customer": f"cus_{suffix}",
                        "subscription": f"sub_{suffix}",
                        "invoice": f"in_{suffix}_1",
                        "metadata": {"checkout_id": checkout["id"], "organization_id": organization.id},
                    },
                    base + 3,
                ),
            )
            assert completed["status"] == "processed"
            session.expire_all()
            stored_checkout = await session.get(BillingCheckoutSession, checkout["id"])
            assert stored_checkout is not None and stored_checkout.status == "completed"
            account = await account_of(session, organization.id)
            assert account.provider_customers["stripe"] == f"cus_{suffix}"
            assert account.plan_id == catalog.top_id

            # 3. invoice.paid adopts the checkout invoice and transaction.
            invoice_payload = event(
                f"evt_{suffix}_invoice_paid",
                "invoice.paid",
                invoice_object(
                    suffix, "1", amount=5000, paid=True, reason="subscription_create",
                    price=catalog.top_monthly, start=start, end=end,
                ),
                base + 6,
            )
            assert (await deliver(session, invoice_payload))["status"] == "processed"
            duplicate = await deliver(session, invoice_payload)
            assert duplicate["duplicate"] is True
            session.expire_all()
            invoices = (
                await session.scalars(select(BillingInvoice).where(BillingInvoice.organization_id == organization.id))
            ).all()
            assert len(invoices) == 1
            invoice = invoices[0]
            assert invoice.external_reference == f"in_{suffix}_1"
            assert invoice.status == "paid" and invoice.amount_paid_minor == 5000
            assert invoice.invoice_metadata["hosted_invoice_url"].startswith("https://invoice.stripe.com/")
            transactions = (
                await session.scalars(
                    select(BillingTransaction).where(BillingTransaction.organization_id == organization.id)
                )
            ).all()
            assert len(transactions) == 1
            assert transactions[0].status == "succeeded"
            assert transactions[0].external_reference == f"pi_{suffix}_1"

            receipt = await session.scalar(
                select(Notification).where(
                    Notification.organization_id == organization.id,
                    Notification.recipient_id == user.id,
                    Notification.type == "billing.payment.receipt",
                )
            )
            assert receipt is not None
            assert invoice.number in receipt.message
            assert receipt.payload["hosted_invoice_url"].startswith("https://invoice.stripe.com/")
            email = await session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == receipt.id,
                    NotificationDelivery.channel == "email",
                )
            )
            assert email is not None  # the communication worker owns delivery

            # 4. Every paid check sees the top plan immediately.
            assert await security_level(session, user_actor, catalog.top_code) == "subscriber"
            ads = await ads_entitlement.resolve_access(
                session, user_actor, policy=ads_entitlement.normalize_policy({})
            )
            assert ads.granted and ads.plan_code == catalog.top_code
            _, plan_code, entitlements = await three_d_product._billing_access(session, user_actor)
            assert plan_code == catalog.top_code
            assert billing.THREE_D_BUSINESS_ENTITLEMENT in entitlements
            assert (
                await aionex_ai_plan_signal.resolve_plan(
                    session, organization_id=organization.id, role_name="Owner"
                )
                == "paid"
            )

            overview = await stripe_billing.owner_subscription_view(session)
            assert any(
                row["organization_id"] == organization.id and row["monthly_amount_minor"] == 5000
                for row in overview["subscriptions"]
            )
            assert overview["summary"]["mrr_by_currency"].get("USD", 0) >= 5000
            assert overview["summary"]["active_subscriptions"] >= 1
            webhook_rows = await session.scalar(
                select(func.count(BillingWebhookEvent.id)).where(
                    BillingWebhookEvent.external_event_id.like(f"evt_{suffix}%")
                )
            )
            assert webhook_rows == 4
    finally:
        await catalog.cleanup(organization.id)


@pytest.mark.asyncio
async def test_lifecycle_change_cancel_resume_past_due_refund_and_end(stripe_settings: None) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)
    catalog = Catalog(suffix)
    base = int(time.time())
    start, end = base - 60, base + 30 * DAY
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers.get("Idempotency-Key"), "every Stripe write is idempotent"
        return httpx.Response(200, json={"id": f"sub_{suffix}", "object": "subscription"})

    transport = httpx.MockTransport(handler)

    def sub(status: str, price: str, created: int, name: str, **extra) -> dict:
        return event(
            f"evt_{suffix}_{name}",
            "customer.subscription.deleted" if status == "canceled" else "customer.subscription.updated",
            subscription_object(
                suffix,
                status=status,
                price=price,
                start=start,
                end=end,
                organization_id=organization.id,
                **extra,
            ),
            created,
        )

    try:
        await catalog.create(organization)
        user_actor = actor(user, organization)
        async with SessionLocal() as session:
            assert (await deliver(session, sub("active", catalog.top_monthly, base, "start", legacy_period=True)))[
                "status"
            ] == "processed"
            assert await security_level(session, user_actor, catalog.top_code) == "subscriber"

            # Downgrade: prorated credit, no payment gate.
            changed = await stripe_billing.change_subscription_plan(
                session,
                user_actor,
                plan_code=catalog.pro_code,
                period_code="monthly",
                transport=transport,
            )
            body = {key: values[0] for key, values in parse_qs(calls[-1].content.decode()).items()}
            assert calls[-1].url.path == f"/v1/subscriptions/sub_{suffix}"
            assert body["items[0][id]"] == f"si_{suffix}"
            assert body["items[0][price]"] == catalog.pro_monthly
            assert body["proration_behavior"] == "create_prorations"
            assert "payment_behavior" not in body
            assert changed["change"]["direction"] == "downgrade"
            assert (await deliver(session, sub("active", catalog.pro_monthly, base + 10, "downgraded")))[
                "status"
            ] == "processed"
            account = await account_of(session, organization.id)
            assert account.plan_id == catalog.pro_id
            assert await security_level(session, user_actor, catalog.top_code) is None
            _, _, entitlements = await three_d_product._billing_access(session, user_actor)
            assert billing.THREE_D_BUSINESS_ENTITLEMENT not in entitlements

            # Upgrade: invoice the difference now, apply only after payment.
            await stripe_billing.change_subscription_plan(
                session,
                user_actor,
                plan_code=catalog.top_code,
                period_code="monthly",
                idempotency_key=f"p5-upgrade-{suffix}",
                transport=transport,
            )
            body = {key: values[0] for key, values in parse_qs(calls[-1].content.decode()).items()}
            assert calls[-1].headers["Idempotency-Key"] == f"p5-upgrade-{suffix}"
            assert body["proration_behavior"] == "always_invoice"
            assert body["payment_behavior"] == "pending_if_incomplete"
            assert (await deliver(session, sub("active", catalog.top_monthly, base + 20, "upgraded")))[
                "status"
            ] == "processed"
            assert await security_level(session, user_actor, catalog.top_code) == "subscriber"

            # An older event arriving late changes nothing.
            late = await deliver(session, sub("active", catalog.pro_monthly, base + 15, "late"))
            assert late["status"] == "stale"
            assert (await account_of(session, organization.id)).plan_id == catalog.top_id

            # Cancel at period end, then reactivate before the period ends.
            cancelled = await billing.cancel_subscription(
                session, user_actor, immediately=False, transport=transport
            )
            assert cancelled["cancel_at_period_end"] is True
            assert b"cancel_at_period_end=true" in calls[-1].content
            assert (
                await deliver(
                    session,
                    sub("active", catalog.top_monthly, base + 30, "cancel_flag", cancel_at_period_end=True),
                )
            )["status"] == "processed"
            assert await security_level(session, user_actor, catalog.top_code) == "subscriber"
            resumed = await stripe_billing.resume_subscription(session, user_actor, transport=transport)
            assert resumed["cancel_at_period_end"] is False
            assert b"cancel_at_period_end=false" in calls[-1].content

            # Renewal payment fails -> past_due: paid features stop, free stays.
            failed = await deliver(
                session,
                event(
                    f"evt_{suffix}_failed",
                    "invoice.payment_failed",
                    invoice_object(
                        suffix, "2", amount=5000, paid=False, reason="subscription_cycle",
                        price=catalog.top_monthly, start=start, end=end,
                    ),
                    base + 40,
                ),
            )
            assert failed["status"] == "processed"
            assert (await deliver(session, sub("past_due", catalog.top_monthly, base + 41, "past_due")))[
                "status"
            ] == "processed"
            account = await account_of(session, organization.id)
            assert account.status == "active"
            assert account.plan_id == catalog.free_id
            assert "*" not in account.entitlements
            assert await security_level(session, user_actor, catalog.top_code) is None
            assert await security_entitlement.active_subscription_plan(session, organization.id) is None
            assert (
                await aionex_ai_plan_signal.resolve_plan(
                    session, organization_id=organization.id, role_name="Owner"
                )
                == "free"
            )
            await billing.enforce_limit(session, organization.id, "p5_unlimited_key", 0)
            warning = await session.scalar(
                select(Notification).where(
                    Notification.organization_id == organization.id,
                    Notification.type == "billing.payment.failed",
                )
            )
            assert warning is not None and warning.severity == "warning"
            failed_invoice = await session.scalar(
                select(BillingInvoice).where(BillingInvoice.external_reference == f"in_{suffix}_2")
            )
            assert failed_invoice is not None and failed_invoice.status == "past_due"

            # Recovery: the retried invoice is paid, the subscription is active.
            assert (
                await deliver(
                    session,
                    event(
                        f"evt_{suffix}_recovered_invoice",
                        "invoice.paid",
                        invoice_object(
                            suffix, "2", amount=5000, paid=True, reason="subscription_cycle",
                            price=catalog.top_monthly, start=start, end=end, attempt=2,
                        ),
                        base + 50,
                    ),
                )
            )["status"] == "processed"
            assert (await deliver(session, sub("active", catalog.top_monthly, base + 51, "recovered")))[
                "status"
            ] == "processed"
            assert await security_level(session, user_actor, catalog.top_code) == "subscriber"
            session.expire_all()
            paid_transaction = await session.scalar(
                select(BillingTransaction).where(BillingTransaction.idempotency_key == f"stripe-invoice:in_{suffix}_2")
            )
            assert paid_transaction is not None and paid_transaction.status == "succeeded"
            assert paid_transaction.external_reference == f"pi_{suffix}_2"
            paid_transaction_id = paid_transaction.id

            # charge.refunded (full) is recorded once, even when redelivered.
            refund_payload = event(
                f"evt_{suffix}_refund",
                "charge.refunded",
                {
                    "id": f"ch_{suffix}_2",
                    "object": "charge",
                    "payment_intent": f"pi_{suffix}_2",
                    "amount": 5000,
                    "amount_refunded": 5000,
                    "refunded": True,
                    "currency": "usd",
                    "refunds": {
                        "data": [{"id": f"re_{suffix}", "amount": 5000, "status": "succeeded", "created": base}]
                    },
                },
                base + 60,
            )
            assert (await deliver(session, refund_payload))["status"] == "processed"
            assert (await deliver(session, refund_payload))["duplicate"] is True
            session.expire_all()
            refunds = (
                await session.scalars(
                    select(BillingRefund).where(BillingRefund.organization_id == organization.id)
                )
            ).all()
            assert [item.external_reference for item in refunds] == [f"re_{suffix}"]
            refreshed = await session.get(BillingTransaction, paid_transaction_id)
            assert refreshed is not None and refreshed.status == "refunded"

            # Trial ending notice.
            assert (
                await deliver(
                    session,
                    event(
                        f"evt_{suffix}_trial",
                        "customer.subscription.trial_will_end",
                        {
                            **subscription_object(
                                suffix, status="trialing", price=catalog.top_monthly,
                                start=start, end=end, organization_id=organization.id,
                            ),
                            "trial_end": base + 3 * DAY,
                        },
                        base + 65,
                    ),
                )
            )["status"] == "processed"
            assert await session.scalar(
                select(Notification.id).where(
                    Notification.organization_id == organization.id,
                    Notification.type == "billing.subscription.trial_ending",
                )
            )

            # The subscription ends: downgrade to free, canceled is terminal.
            assert (await deliver(session, sub("canceled", catalog.top_monthly, base + 70, "ended")))[
                "status"
            ] == "processed"
            assert (await account_of(session, organization.id)).plan_id == catalog.free_id
            assert await security_level(session, user_actor, catalog.top_code) is None
            ghost = await deliver(session, sub("active", catalog.top_monthly, base + 80, "ghost"))
            assert ghost["status"] == "stale"
            session.expire_all()
            ended = await session.scalar(
                select(BillingSubscription).where(BillingSubscription.external_reference == f"sub_{suffix}")
            )
            assert ended is not None and ended.status == "canceled" and ended.canceled_at is not None
            assert (await account_of(session, organization.id)).plan_id == catalog.free_id
    finally:
        await catalog.cleanup(organization.id)


@pytest.mark.asyncio
async def test_failed_event_rolls_back_and_is_reprocessed_on_retry(stripe_settings: None) -> None:
    suffix = uuid4().hex[:12]
    organization, _user = await identity(suffix)
    catalog = Catalog(suffix)
    base = int(time.time())
    start, end = base - 60, base + 30 * DAY
    try:
        await catalog.create(organization)
        invoice_payload = event(
            f"evt_{suffix}_early_invoice",
            "invoice.paid",
            {
                **invoice_object(
                    suffix, "1", amount=1000, paid=True, reason="subscription_cycle",
                    price=catalog.pro_monthly, start=start, end=end,
                ),
                "customer": f"cus_unknown_{suffix}",
            },
            base,
        )
        async with SessionLocal() as session:
            with pytest.raises(HTTPException) as early:
                await deliver(session, invoice_payload)
            assert early.value.status_code == 409
            session.expire_all()
            row = await session.scalar(
                select(BillingWebhookEvent).where(
                    BillingWebhookEvent.external_event_id == f"evt_{suffix}_early_invoice"
                )
            )
            assert row is not None and row.status == "failed" and row.error == "ValueError"
            assert (
                await session.scalar(
                    select(func.count(BillingInvoice.id)).where(BillingInvoice.organization_id == organization.id)
                )
                == 0
            )

            await deliver(
                session,
                event(
                    f"evt_{suffix}_mapping",
                    "customer.subscription.created",
                    subscription_object(
                        suffix, status="active", price=catalog.pro_monthly, start=start, end=end,
                        organization_id=organization.id,
                    ),
                    base + 1,
                ),
            )
            retried = await deliver(session, invoice_payload)
            assert retried["duplicate"] is False and retried["status"] == "processed"
            session.expire_all()
            row = await session.scalar(
                select(BillingWebhookEvent).where(
                    BillingWebhookEvent.external_event_id == f"evt_{suffix}_early_invoice"
                )
            )
            assert row is not None and row.status == "processed" and row.error is None
            assert (await deliver(session, invoice_payload))["duplicate"] is True

            ignored = await deliver(
                session, event(f"evt_{suffix}_other", "customer.created", {"id": f"cus_{suffix}"}, base + 2)
            )
            assert ignored["status"] == "ignored"
    finally:
        await catalog.cleanup(organization.id)


@pytest.mark.asyncio
async def test_portal_session_and_immediate_cancel_downgrade_without_suspension(
    stripe_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = uuid4().hex[:12]
    organization, user = await identity(suffix)
    catalog = Catalog(suffix)
    calls: list[httpx.Request] = []
    base = int(time.time())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers.get("Idempotency-Key")
        if request.url.path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": f"https://billing.stripe.com/p/session/{suffix}"})
        return httpx.Response(200, json={"id": f"sub_{suffix}", "status": "canceled"})

    transport = httpx.MockTransport(handler)
    try:
        await catalog.create(organization)
        user_actor = actor(user, organization)
        async with SessionLocal() as session:
            with pytest.raises(HTTPException) as no_customer:
                await billing.create_billing_portal_session(session, user_actor, transport=transport)
            assert no_customer.value.status_code == 409

            await deliver(
                session,
                event(
                    f"evt_{suffix}_active",
                    "customer.subscription.created",
                    subscription_object(
                        suffix, status="active", price=catalog.top_monthly, start=base - 60,
                        end=base + 30 * DAY, organization_id=organization.id,
                    ),
                    base,
                ),
            )
            assert (await account_of(session, organization.id)).provider_customers["stripe"] == f"cus_{suffix}"
            monkeypatch.setattr(billing.settings, "STRIPE_PORTAL_CONFIGURATION_ID", f"bpc_{suffix}")
            portal = await billing.create_billing_portal_session(
                session, user_actor, locale="fr", transport=transport
            )
            assert portal["url"] == f"https://billing.stripe.com/p/session/{suffix}"
            body = {key: values[0] for key, values in parse_qs(calls[-1].content.decode()).items()}
            assert body["customer"] == f"cus_{suffix}"
            assert body["return_url"] == "https://ai.vip-e.net/fr/billing?portal=return"
            assert body["configuration"] == f"bpc_{suffix}"

            result = await billing.cancel_subscription(
                session, user_actor, immediately=True, idempotency_key=f"p5-cancel-now-{suffix}", transport=transport
            )
            assert result["status"] == "canceled"
            assert calls[-1].method == "DELETE"
            assert calls[-1].headers["Idempotency-Key"] == f"p5-cancel-now-{suffix}"
            account = await account_of(session, organization.id)
            assert account.status == "active"  # downgraded, not suspended
            assert account.plan_id == catalog.free_id
            assert await security_level(session, user_actor, catalog.top_code) is None
            # The deletion webhook that follows is consistent and idempotent.
            deleted = await deliver(
                session,
                event(
                    f"evt_{suffix}_deleted",
                    "customer.subscription.deleted",
                    subscription_object(
                        suffix, status="canceled", price=catalog.top_monthly, start=base - 60,
                        end=base, organization_id=organization.id,
                    ),
                    base + 5,
                ),
            )
            assert deleted["status"] == "processed"
            assert (await account_of(session, organization.id)).plan_id == catalog.free_id
    finally:
        await catalog.cleanup(organization.id)


# --------------------------------------------------------------------- contracts


@pytest.mark.asyncio
async def test_stripe_writes_require_idempotency_keys(stripe_settings: None) -> None:
    with pytest.raises(ValueError):
        await stripe_billing.stripe_request(
            "POST", "/v1/subscriptions/sub_x", data=[("a", "b")], transport=httpx.MockTransport(lambda r: httpx.Response(200))
        )


def test_portal_urls_and_handled_event_contract() -> None:
    assert stripe_billing.portal_locale("ar-EG") == "ar"
    assert stripe_billing.portal_locale(None) == "en"
    assert stripe_billing.portal_locale("zz") == "en"
    required = {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.trial_will_end",
        "invoice.paid",
        "invoice.payment_failed",
        "charge.refunded",
    }
    assert required <= set(stripe_billing.HANDLED_EVENTS)
    assert stripe_billing.webhook_contract()["path"] == "/api/v1/billing/webhooks/stripe"
    start, end = stripe_billing.subscription_period(
        {"items": {"data": [{"current_period_start": 10, "current_period_end": 20}]}}
    )
    assert start == datetime.fromtimestamp(10, UTC) and end == datetime.fromtimestamp(20, UTC)
    assert stripe_billing.invoice_subscription_ref(
        {"parent": {"subscription_details": {"subscription": "sub_basil"}}}
    ) == "sub_basil"
    assert stripe_billing.invoice_payment_refs(
        {"payments": {"data": [{"payment": {"payment_intent": "pi_basil"}}]}}
    ) == ("pi_basil", None)
    assert stripe_billing.coupon_stripe_discount({"stripe_promotion_code": "promo_1"}) == (
        "promotion_code",
        "promo_1",
    )
    assert stripe_billing.coupon_stripe_discount({}) is None


def test_stripe_billing_modules_have_no_dead_placeholders() -> None:
    for relative in (
        "app/services/stripe_billing.py",
        "app/services/billing.py",
        "app/api/v1/endpoints/billing.py",
    ):
        source = (BACKEND / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(isinstance(node, ast.Pass) for node in ast.walk(tree)), relative
        assert "NotImplementedError" not in source, relative
