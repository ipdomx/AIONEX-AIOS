"""Durable billing, licensing, payment, entitlement, and metering runtime.

The Owner-published portal catalogue is the commercial source of truth. The
free plan is overlaid with the actually enforced free-tier policy so public
pricing and runtime limits cannot drift. Provider credentials remain external
to the database; only provider references and masked payment metadata persist.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    BillingAccount,
    BillingCheckoutSession,
    BillingCoupon,
    BillingCouponRedemption,
    BillingInvoice,
    BillingLicense,
    BillingPaymentMethod,
    BillingPlan,
    BillingPrice,
    BillingReconciliationRun,
    BillingRefund,
    BillingSubscription,
    BillingTaxRate,
    BillingTransaction,
    BillingUsageRecord,
    BillingWallet,
    BillingWalletEntry,
    BillingWebhookEvent,
    Notification,
    Organization,
    Project,
    User,
    Workspace,
)
from app.services.free_tier import get_free_tier_policy, public_free_tier_policy
from app.services.portal_cms import get_published_portal

SUPPORTED_PROVIDERS = (
    "stripe",
    "paypal",
    "paddle",
    "paymob",
    "fawry",
    "stc_pay",
    "mada",
    "bank_transfer",
    "manual",
)
CHECKOUT_PROVIDERS = {"stripe", "paypal", "paddle", "bank_transfer", "manual"}
EXTERNAL_SUBSCRIPTION_PROVIDERS = {"stripe", "paypal", "paddle"}
ACTIVE_ACCOUNT_STATUSES = {"active", "trial"}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
SENSITIVE_EVENT_KEYS = {
    "number",
    "card_number",
    "cvc",
    "cvv",
    "client_secret",
    "secret",
    "api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
}


def now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _minor(value: int | float | str | Decimal | None) -> int | None:
    if value is None:
        return None
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def _currency(value: str | None) -> str:
    normalized = (value or settings.PAYMENTS_DEFAULT_CURRENCY).strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise HTTPException(status_code=422, detail="Currency must be an ISO-4217 code")
    return normalized


def _catalog_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _redact_event(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:300]:
            key = str(raw_key)[:120]
            normalized = key.lower().replace("-", "_")
            result[key] = (
                "[REDACTED]"
                if normalized in SENSITIVE_EVENT_KEYS
                else _redact_event(item, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [_redact_event(item, depth=depth + 1) for item in value[:300]]
    if isinstance(value, str):
        return value[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def provider_readiness() -> list[dict[str, Any]]:
    stripe_key = (settings.STRIPE_SECRET_KEY or "").strip()
    environment = settings.PAYMENTS_ENVIRONMENT.strip().lower()
    stripe_mode = (
        "test"
        if stripe_key.startswith("sk_test_")
        else "live" if stripe_key.startswith("sk_live_") else "unknown"
    )
    definitions = [
        {
            "id": "stripe",
            "configured": bool(stripe_key and settings.STRIPE_WEBHOOK_SECRET),
            "mode": stripe_mode,
            "capabilities": [
                "checkout",
                "subscriptions",
                "refunds",
                "webhooks",
                "apple_pay",
                "google_pay",
                "billing_portal",
            ],
        },
        {
            "id": "paypal",
            "configured": bool(
                settings.PAYPAL_CLIENT_ID
                and settings.PAYPAL_CLIENT_SECRET
                and settings.PAYPAL_WEBHOOK_ID
            ),
            "mode": environment,
            "capabilities": ["checkout", "subscriptions", "refunds", "webhooks"],
        },
        {
            "id": "paddle",
            "configured": bool(
                settings.PADDLE_API_KEY and settings.PADDLE_WEBHOOK_SECRET
            ),
            "mode": environment,
            "capabilities": ["checkout", "subscriptions", "refunds", "webhooks", "tax"],
        },
        {
            "id": "paymob",
            "configured": bool(settings.PAYMOB_WEBHOOK_SECRET),
            "mode": environment,
            "capabilities": ["webhooks"],
        },
        {
            "id": "fawry",
            "configured": bool(settings.FAWRY_WEBHOOK_SECRET),
            "mode": environment,
            "capabilities": ["webhooks"],
        },
        {
            "id": "stc_pay",
            "configured": bool(settings.STC_PAY_WEBHOOK_SECRET),
            "mode": environment,
            "capabilities": ["webhooks"],
        },
        {
            "id": "mada",
            "configured": bool(stripe_key),
            "mode": stripe_mode,
            "capabilities": ["checkout_via_stripe"],
        },
        {
            "id": "bank_transfer",
            "configured": bool(
                settings.BANK_TRANSFER_ACCOUNT_NAME and settings.BANK_TRANSFER_IBAN
            ),
            "mode": "manual",
            "capabilities": ["checkout", "instructions", "reconciliation"],
        },
        {
            "id": "manual",
            "configured": True,
            "mode": "manual",
            "capabilities": ["invoice", "reconciliation"],
        },
    ]
    for item in definitions:
        item["status"] = "ready" if item["configured"] else "unconfigured"
        if (
            item["id"] == "stripe"
            and item["configured"]
            and environment == "sandbox"
            and stripe_mode != "test"
        ):
            item["status"] = "blocked"
            item["configured"] = False
        if (
            item["id"] == "stripe"
            and item["configured"]
            and environment == "live"
            and stripe_mode != "live"
        ):
            item["status"] = "blocked"
            item["configured"] = False
    return definitions


def _provider(provider: str) -> dict[str, Any]:
    normalized = provider.strip().lower()
    item = next(
        (item for item in provider_readiness() if item["id"] == normalized), None
    )
    if item is None:
        raise HTTPException(status_code=422, detail="Unsupported payment provider")
    return item


async def _portal_catalog(session: AsyncSession) -> tuple[dict[str, Any], int]:
    published = await get_published_portal(session)
    configuration = dict(published["configuration"])
    pricing = dict(configuration.get("pricing") or {})
    publication = dict(published.get("publication") or {})
    return pricing, int(publication.get("version") or 0)


def _normalized_plan_code(value: str) -> str:
    code = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {"starter": "free", "team": "professional", "enterprise": "business"}
    return aliases.get(code, code)


def _localized_english(value: Any, fallback: str) -> str:
    if isinstance(value, Mapping):
        return str(value.get("en") or value.get("ar") or fallback).strip()
    return str(value or fallback).strip()


async def sync_catalog(session: AsyncSession) -> dict[str, Any]:
    pricing, source_version = await _portal_catalog(session)
    free_policy = public_free_tier_policy(await get_free_tier_policy(session))
    source_plans = list(pricing.get("plans") or [])
    seen_codes: set[str] = set()
    result: list[dict[str, Any]] = []

    for raw in source_plans:
        code = _normalized_plan_code(str(raw.get("id") or ""))
        if not code:
            continue
        seen_codes.add(code)
        limits = dict(raw.get("limits") or {})
        entitlements = list(raw.get("entitlements") or [])
        if code == "free":
            limits = dict(free_policy["limits"])
            entitlements = sorted(
                set(entitlements)
                | {"projects.core", "account.profile", "support.requests"}
            )
        metering = dict(raw.get("metering") or {})
        public_plan = {
            "code": code,
            "name": raw.get("name") or {"en": code.title()},
            "description": raw.get("description") or {},
            "enabled": bool(raw.get("enabled")),
            "featured": bool(raw.get("featured")),
            "order": int(raw.get("order") or 0),
            "features": list(raw.get("features") or []),
            "limits": limits,
            "entitlements": entitlements,
            "metering": metering,
            "cta_label": raw.get("cta_label") or {},
            "checkout_provider": str(raw.get("checkout_provider") or "none").lower(),
            "periods": [],
        }
        plan_hash = _catalog_hash(public_plan | {"periods": raw.get("periods") or []})
        plan = await session.scalar(
            select(BillingPlan).where(BillingPlan.code == code).with_for_update()
        )
        if plan is None:
            plan = BillingPlan(
                code=code,
                name=_localized_english(raw.get("name"), code.title()),
                description=_localized_english(raw.get("description"), ""),
                status="active" if raw.get("enabled") else "inactive",
                default_currency=_currency(pricing.get("default_currency")),
                limits=limits,
                entitlements=entitlements,
                metering=metering,
                source_version=source_version,
                source_hash=plan_hash,
            )
            session.add(plan)
            await session.flush()
        else:
            plan.name = _localized_english(raw.get("name"), code.title())
            plan.description = _localized_english(raw.get("description"), "")
            plan.status = "active" if raw.get("enabled") else "inactive"
            plan.default_currency = _currency(pricing.get("default_currency"))
            plan.limits = limits
            plan.entitlements = entitlements
            plan.metering = metering
            plan.source_version = source_version
            plan.source_hash = plan_hash

        period_codes: set[tuple[str, str]] = set()
        for raw_period in list(raw.get("periods") or []):
            period_code = str(raw_period.get("id") or "monthly").strip().lower()
            currency = _currency(raw_period.get("currency") or plan.default_currency)
            period_codes.add((period_code, currency))
            provider_reference = (
                str(
                    raw_period.get("checkout_reference")
                    or raw.get("checkout_reference")
                    or ""
                ).strip()
                or None
            )
            price = await session.scalar(
                select(BillingPrice)
                .where(
                    BillingPrice.plan_id == plan.id,
                    BillingPrice.period_code == period_code,
                    BillingPrice.currency == currency,
                )
                .with_for_update()
            )
            values = {
                "months": int(raw_period.get("months") or 0),
                "amount_minor": _minor(raw_period.get("price")),
                "compare_at_minor": _minor(raw_period.get("compare_at_price")),
                "enabled": bool(raw_period.get("enabled")),
                "provider": str(
                    raw_period.get("checkout_provider")
                    or raw.get("checkout_provider")
                    or "none"
                ).lower(),
                "provider_reference": provider_reference,
                "price_metadata": {"label": raw_period.get("label") or {}},
            }
            if price is None:
                price = BillingPrice(
                    plan_id=plan.id,
                    period_code=period_code,
                    currency=currency,
                    **values,
                )
                session.add(price)
                await session.flush()
            else:
                for key, value in values.items():
                    setattr(price, key, value)
            public_plan["periods"].append(
                {
                    "id": period_code,
                    "label": raw_period.get("label") or {},
                    "months": price.months,
                    "amount_minor": price.amount_minor,
                    "compare_at_minor": price.compare_at_minor,
                    "currency": price.currency,
                    "enabled": price.enabled,
                    "provider": price.provider,
                    "checkout_available": bool(
                        public_plan["enabled"]
                        and price.enabled
                        and price.amount_minor is not None
                        and price.amount_minor > 0
                        and price.provider in CHECKOUT_PROVIDERS
                        and _provider(price.provider)["configured"]
                        and (
                            price.provider in {"manual", "bank_transfer"}
                            or bool(price.provider_reference)
                        )
                    ),
                }
            )
        stale_prices = (
            await session.scalars(
                select(BillingPrice).where(BillingPrice.plan_id == plan.id)
            )
        ).all()
        for price in stale_prices:
            if (price.period_code, price.currency) not in period_codes:
                price.enabled = False
        result.append(public_plan)

    existing = (await session.scalars(select(BillingPlan))).all()
    for plan in existing:
        if plan.source_version > 0 and plan.code not in seen_codes:
            plan.status = "inactive"

    await _ensure_accounts_for_organizations(session)
    await session.flush()
    return {
        "enabled": bool(pricing.get("enabled", True)),
        "default_currency": _currency(pricing.get("default_currency")),
        "default_period": str(pricing.get("default_period") or "monthly"),
        "show_tax_note": bool(pricing.get("show_tax_note", True)),
        "heading": pricing.get("heading") or {},
        "description": pricing.get("description") or {},
        "tax_note": pricing.get("tax_note") or {},
        "faq": pricing.get("faq") or [],
        "source_version": source_version,
        "plans": sorted(result, key=lambda item: (item["order"], item["code"])),
        "providers": provider_readiness(),
    }


async def _internal_plan(session: AsyncSession, organization_plan: str) -> BillingPlan:
    code = _normalized_plan_code(organization_plan or "business")
    plan = await session.scalar(select(BillingPlan).where(BillingPlan.code == code))
    if plan is not None:
        return plan
    plan = BillingPlan(
        code=code,
        name=code.replace("-", " ").title(),
        description="Internal organization plan retained until Owner pricing is published.",
        status="internal",
        default_currency=_currency(None),
        limits={},
        entitlements=["*"],
        metering={},
        source_version=0,
        source_hash=_catalog_hash({"internal": code}),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _ensure_accounts_for_organizations(session: AsyncSession) -> None:
    organizations = (await session.scalars(select(Organization))).all()
    for organization in organizations:
        account = await session.scalar(
            select(BillingAccount).where(
                BillingAccount.organization_id == organization.id
            )
        )
        plan = await _internal_plan(session, organization.plan)
        active_users = int(
            await session.scalar(
                select(func.count(User.id)).where(
                    User.organization_id == organization.id,
                    User.deleted_at.is_(None),
                    User.status.in_(("active", "online")),
                )
            )
            or 0
        )
        if account is None:
            account = BillingAccount(
                organization_id=organization.id,
                plan_id=plan.id,
                status=(
                    "active"
                    if organization.status in {"active", "trial"}
                    else "suspended"
                ),
                licensed_seats=max(
                    1000 if organization.id == "aionex-org" else 1, active_users
                ),
                limits=dict(plan.limits or {}),
                entitlements=list(plan.entitlements or []),
            )
            session.add(account)
        else:
            # Preserve explicit Owner plan assignments, while keeping the
            # selected plan's limits and entitlements synchronized with the
            # published commercial catalogue.
            if account.plan_id is None:
                account.plan_id = plan.id
            if account.plan_id == plan.id:
                account.limits = dict(plan.limits or {})
                account.entitlements = list(plan.entitlements or [])
            account.licensed_seats = max(account.licensed_seats, active_users, 1)


async def ensure_billing_account(
    session: AsyncSession, organization_id: str, *, lock: bool = False
) -> BillingAccount:
    await sync_catalog(session)
    statement = select(BillingAccount).where(
        BillingAccount.organization_id == organization_id
    )
    if lock:
        statement = statement.with_for_update()
    account = await session.scalar(statement)
    if account is None:
        raise HTTPException(
            status_code=503, detail="Billing account could not be initialized"
        )
    return account


async def billing_context(
    session: AsyncSession, organization_id: str
) -> dict[str, Any]:
    account = await ensure_billing_account(session, organization_id)
    plan = await session.get(BillingPlan, account.plan_id) if account.plan_id else None
    subscription = await session.scalar(
        select(BillingSubscription)
        .where(BillingSubscription.organization_id == organization_id)
        .order_by(BillingSubscription.created_at.desc())
        .limit(1)
    )
    active_users = int(
        await session.scalar(
            select(func.count(User.id)).where(
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
                User.status.in_(("active", "online")),
            )
        )
        or 0
    )
    projects = int(
        await session.scalar(
            select(func.count(Project.id)).where(
                Project.organization_id == organization_id,
                Project.status != "deleted",
            )
        )
        or 0
    )
    workspaces = int(
        await session.scalar(
            select(func.count(Workspace.id)).where(
                Workspace.organization_id == organization_id,
                Workspace.status != "deleted",
            )
        )
        or 0
    )
    limits = dict(account.limits or (plan.limits if plan else {}) or {})
    entitlements = list(
        account.entitlements or (plan.entitlements if plan else []) or []
    )
    return {
        "account": account,
        "plan": plan,
        "subscription": subscription,
        "limits": limits,
        "entitlements": entitlements,
        "usage": {
            "seats": active_users,
            "projects": projects,
            "workspaces": workspaces,
        },
    }


async def enforce_limit(
    session: AsyncSession,
    organization_id: str,
    key: str,
    current: int,
    increment: int = 1,
) -> None:
    context = await billing_context(session, organization_id)
    account: BillingAccount = context["account"]
    if account.status not in ACTIVE_ACCOUNT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Organization billing access is suspended",
        )
    limit = context["limits"].get(key)
    if limit is None:
        return
    try:
        normalized = int(limit)
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail=f"Billing limit {key} is invalid")
    if normalized >= 0 and current + increment > normalized:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "BILLING_LIMIT_REACHED",
                "limit": key,
                "allowed": normalized,
                "used": current,
            },
        )


async def enforce_seat_limit(
    session: AsyncSession, organization_id: str, increment: int = 1
) -> None:
    context = await billing_context(session, organization_id)
    account: BillingAccount = context["account"]
    current = int(context["usage"]["seats"])
    if account.status not in ACTIVE_ACCOUNT_STATUSES:
        raise HTTPException(
            status_code=402, detail="Organization billing access is suspended"
        )
    if current + increment > account.licensed_seats:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "SEAT_LIMIT_REACHED",
                "allowed": account.licensed_seats,
                "used": current,
            },
        )


def has_entitlement(context: Mapping[str, Any], entitlement: str) -> bool:
    granted = set(context.get("entitlements") or [])
    return "*" in granted or entitlement in granted


async def require_entitlement(
    session: AsyncSession, organization_id: str, entitlement: str
) -> None:
    context = await billing_context(session, organization_id)
    if not has_entitlement(context, entitlement):
        raise HTTPException(
            status_code=402,
            detail={"code": "ENTITLEMENT_REQUIRED", "entitlement": entitlement},
        )


def _audit(
    actor: UserRecord | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: dict[str, Any],
) -> AuditEvent:
    return AuditEvent(
        organization_id=(
            actor.organization_id if actor else details.get("organization_id")
        ),
        user_id=actor.id if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=_redact_event(details),
    )


async def _notify_owner_and_org(
    session: AsyncSession,
    organization_id: str,
    *,
    title: str,
    message: str,
    event_type: str,
    severity: str = "info",
) -> None:
    recipients = (
        await session.scalars(
            select(User.id).where(
                User.deleted_at.is_(None),
                User.status.in_(("active", "online")),
                (User.organization_id == organization_id) | (User.id == "owner-1"),
            )
        )
    ).all()
    for recipient_id in sorted(set(recipients)):
        recipient = await session.get(User, recipient_id)
        if recipient is None:
            continue
        session.add(
            Notification(
                organization_id=recipient.organization_id,
                recipient_id=recipient.id,
                type=event_type,
                title=title,
                message=message,
                severity=severity,
            )
        )


def _coupon_discount(
    coupon: BillingCoupon | None, subtotal_minor: int, currency: str
) -> int:
    if coupon is None:
        return 0
    if not coupon.active or (coupon.expires_at and _as_utc(coupon.expires_at) <= now()):
        raise HTTPException(status_code=422, detail="Coupon is inactive or expired")
    if (
        coupon.max_redemptions is not None
        and coupon.redeemed_count >= coupon.max_redemptions
    ):
        raise HTTPException(status_code=422, detail="Coupon redemption limit reached")
    if coupon.discount_type == "percent":
        basis = int(coupon.percent_off_basis_points or 0)
        if basis <= 0 or basis > 10_000:
            raise HTTPException(status_code=503, detail="Coupon percentage is invalid")
        return min(
            subtotal_minor,
            int(
                (Decimal(subtotal_minor) * Decimal(basis) / Decimal(10_000)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            ),
        )
    if coupon.discount_type == "fixed":
        if coupon.currency and coupon.currency != currency:
            raise HTTPException(
                status_code=422, detail="Coupon currency does not match checkout"
            )
        return min(subtotal_minor, int(coupon.amount_off_minor or 0))
    raise HTTPException(status_code=503, detail="Coupon type is invalid")


async def _tax(
    session: AsyncSession, country_code: str | None, taxable_minor: int
) -> tuple[BillingTaxRate | None, int]:
    if not country_code:
        return None, 0
    country = country_code.strip().upper()
    rate = await session.scalar(
        select(BillingTaxRate)
        .where(BillingTaxRate.country_code == country, BillingTaxRate.active.is_(True))
        .order_by(
            BillingTaxRate.region_code.is_not(None), BillingTaxRate.created_at.desc()
        )
        .limit(1)
    )
    if rate is None:
        return None, 0
    basis = Decimal(rate.percentage_basis_points) / Decimal(10_000)
    if rate.inclusive:
        tax = Decimal(taxable_minor) - (Decimal(taxable_minor) / (Decimal(1) + basis))
    else:
        tax = Decimal(taxable_minor) * basis
    return rate, int(tax.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _stripe_checkout(
    checkout: BillingCheckoutSession,
    actor: UserRecord,
    plan: BillingPlan,
    price: BillingPrice,
    *,
    idempotency_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    if not price.provider_reference:
        raise HTTPException(status_code=409, detail="Stripe price reference is missing")
    data = [
        ("mode", "subscription"),
        ("success_url", settings.PAYMENTS_SUCCESS_URL),
        ("cancel_url", settings.PAYMENTS_CANCEL_URL),
        ("customer_email", actor.email),
        ("client_reference_id", checkout.id),
        ("line_items[0][price]", price.provider_reference),
        ("line_items[0][quantity]", "1"),
        ("allow_promotion_codes", "true"),
        ("automatic_payment_methods[enabled]", "true"),
        ("metadata[organization_id]", actor.organization_id),
        ("metadata[user_id]", actor.id),
        ("metadata[plan_code]", plan.code),
        ("metadata[price_id]", price.id),
        ("metadata[checkout_id]", checkout.id),
        ("metadata[apple_pay_enabled]", "true"),
        ("metadata[google_pay_enabled]", "true"),
    ]
    async with httpx.AsyncClient(
        base_url=settings.STRIPE_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/v1/checkout/sessions",
            headers={
                "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=urlencode(data),
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Stripe checkout creation failed")
    payload = response.json()
    return {
        "external_reference": str(payload["id"]),
        "checkout_url": str(payload["url"]),
        "expires_at": payload.get("expires_at"),
    }


async def _paypal_token(transport: httpx.AsyncBaseTransport | None = None) -> str:
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="PayPal is not configured")
    async with httpx.AsyncClient(
        base_url=settings.PAYPAL_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="PayPal authentication failed")
    return str(response.json()["access_token"])


async def _paypal_checkout(
    checkout: BillingCheckoutSession,
    actor: UserRecord,
    plan: BillingPlan,
    price: BillingPrice,
    *,
    idempotency_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not price.provider_reference:
        raise HTTPException(status_code=409, detail="PayPal plan reference is missing")
    oauth_value = await _paypal_token(transport)
    payload = {
        "plan_id": price.provider_reference,
        "custom_id": checkout.id,
        "subscriber": {"email_address": actor.email},
        "application_context": {
            "return_url": settings.PAYMENTS_SUCCESS_URL,
            "cancel_url": settings.PAYMENTS_CANCEL_URL,
            "user_action": "SUBSCRIBE_NOW",
        },
    }
    async with httpx.AsyncClient(
        base_url=settings.PAYPAL_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/v1/billing/subscriptions",
            headers={
                "Authorization": f"Bearer {oauth_value}",
                "PayPal-Request-Id": idempotency_key,
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="PayPal checkout creation failed")
    data = response.json()
    approval = next(
        (
            item.get("href")
            for item in data.get("links", [])
            if item.get("rel") == "approve"
        ),
        None,
    )
    if not approval:
        raise HTTPException(status_code=502, detail="PayPal approval URL is missing")
    return {
        "external_reference": str(data["id"]),
        "checkout_url": str(approval),
        "expires_at": None,
    }


async def _paddle_checkout(
    checkout: BillingCheckoutSession,
    actor: UserRecord,
    plan: BillingPlan,
    price: BillingPrice,
    *,
    idempotency_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not settings.PADDLE_API_KEY:
        raise HTTPException(status_code=503, detail="Paddle is not configured")
    if not price.provider_reference:
        raise HTTPException(status_code=409, detail="Paddle price reference is missing")
    payload = {
        "items": [{"price_id": price.provider_reference, "quantity": 1}],
        "checkout": {"url": settings.PAYMENTS_SUCCESS_URL},
        "custom_data": {
            "organization_id": actor.organization_id,
            "user_id": actor.id,
            "plan_code": plan.code,
            "price_id": price.id,
            "checkout_id": checkout.id,
        },
    }
    async with httpx.AsyncClient(
        base_url=settings.PADDLE_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/transactions",
            headers={
                "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
                "Idempotency-Key": idempotency_key,
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Paddle checkout creation failed")
    data = response.json()["data"]
    return {
        "external_reference": str(data["id"]),
        "checkout_url": str(data.get("checkout", {}).get("url") or ""),
        "expires_at": None,
    }


async def _offline_checkout(
    checkout: BillingCheckoutSession,
    price: BillingPrice,
) -> dict[str, Any]:
    reference = (
        f"BT-{secrets.token_hex(6).upper()}"
        if price.provider == "bank_transfer"
        else f"MANUAL-{secrets.token_hex(6).upper()}"
    )
    summary = dict(checkout.session_metadata or {})
    if price.provider == "bank_transfer":
        instructions = {
            "type": "bank_transfer",
            "bank_name": settings.BANK_TRANSFER_BANK_NAME,
            "account_name": settings.BANK_TRANSFER_ACCOUNT_NAME,
            "iban": settings.BANK_TRANSFER_IBAN,
            "swift": settings.BANK_TRANSFER_SWIFT,
            "reference": reference,
            "amount_minor": int(summary.get("total_minor") or 0),
            "currency": price.currency,
        }
        if not instructions["account_name"] or not instructions["iban"]:
            raise HTTPException(
                status_code=503,
                detail="Bank-transfer instructions are not configured",
            )
    else:
        instructions = {
            "type": "manual_invoice",
            "reference": reference,
            "amount_minor": int(summary.get("total_minor") or 0),
            "currency": price.currency,
            "message": (
                "Payment is awaiting Owner reconciliation. Access is activated "
                "only after the transaction is marked as settled."
            ),
        }
    return {
        "external_reference": reference,
        "checkout_url": None,
        "expires_at": int((now() + timedelta(days=7)).timestamp()),
        "status": "awaiting_payment",
        "instructions": instructions,
    }


async def _release_coupon_reservation(
    session: AsyncSession,
    checkout_id: str,
) -> bool:
    redemption = await session.scalar(
        select(BillingCouponRedemption)
        .where(BillingCouponRedemption.checkout_session_id == checkout_id)
        .with_for_update()
    )
    if redemption is None:
        return False
    coupon = await session.scalar(
        select(BillingCoupon)
        .where(BillingCoupon.id == redemption.coupon_id)
        .with_for_update()
    )
    if coupon is not None:
        coupon.redeemed_count = max(0, coupon.redeemed_count - 1)
    await session.delete(redemption)
    return True


async def create_checkout(
    session: AsyncSession,
    actor: UserRecord,
    *,
    plan_code: str,
    period_code: str,
    idempotency_key: str,
    coupon_code: str | None = None,
    billing_country: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    key = idempotency_key.strip()
    if len(key) < 12 or len(key) > 160:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be 12 to 160 characters",
        )
    existing = await session.scalar(
        select(BillingCheckoutSession).where(
            BillingCheckoutSession.idempotency_key == key
        )
    )
    if existing is not None:
        if (
            existing.organization_id != actor.organization_id
            or existing.user_id != actor.id
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key is already in use",
            )
        return checkout_snapshot(existing)

    await sync_catalog(session)
    plan = await session.scalar(
        select(BillingPlan).where(BillingPlan.code == _normalized_plan_code(plan_code))
    )
    if plan is None or plan.status != "active":
        raise HTTPException(status_code=404, detail="Active billing plan not found")
    price = await session.scalar(
        select(BillingPrice).where(
            BillingPrice.plan_id == plan.id,
            BillingPrice.period_code == period_code.strip().lower(),
            BillingPrice.enabled.is_(True),
        )
    )
    if price is None:
        raise HTTPException(status_code=404, detail="Active billing price not found")
    if price.amount_minor is None or price.amount_minor <= 0:
        raise HTTPException(
            status_code=409,
            detail="This plan does not have a payable price",
        )
    provider_info = _provider(price.provider)
    if price.provider not in CHECKOUT_PROVIDERS or not provider_info["configured"]:
        raise HTTPException(
            status_code=409,
            detail="Checkout is not available for this plan",
        )
    if (
        price.provider in EXTERNAL_SUBSCRIPTION_PROVIDERS
        and not price.provider_reference
    ):
        raise HTTPException(
            status_code=409,
            detail="Provider price reference is missing",
        )

    coupon = None
    if coupon_code:
        coupon = await session.scalar(
            select(BillingCoupon)
            .where(func.upper(BillingCoupon.code) == coupon_code.strip().upper())
            .with_for_update()
        )
        if coupon is None:
            raise HTTPException(status_code=422, detail="Coupon is not valid")
    discount_minor = _coupon_discount(coupon, price.amount_minor, price.currency)
    taxable_minor = max(0, price.amount_minor - discount_minor)
    tax_rate, tax_minor = await _tax(session, billing_country, taxable_minor)
    total_minor = taxable_minor + (0 if tax_rate and tax_rate.inclusive else tax_minor)

    checkout = BillingCheckoutSession(
        organization_id=actor.organization_id,
        user_id=actor.id,
        plan_id=plan.id,
        price_id=price.id,
        provider=price.provider,
        idempotency_key=key,
        coupon_code=coupon.code if coupon else None,
        billing_country=(billing_country.strip().upper() if billing_country else None),
        expires_at=now() + timedelta(minutes=30),
        session_metadata={
            "subtotal_minor": price.amount_minor,
            "discount_minor": discount_minor,
            "tax_minor": tax_minor,
            "total_minor": total_minor,
            "currency": price.currency,
            "plan_code": plan.code,
            "period_code": price.period_code,
        },
    )
    session.add(checkout)
    await session.flush()
    invoice = BillingInvoice(
        organization_id=actor.organization_id,
        provider=price.provider,
        number=f"INV-{now():%Y%m%d}-{secrets.token_hex(5).upper()}",
        status="open",
        currency=price.currency,
        subtotal_minor=price.amount_minor,
        discount_minor=discount_minor,
        tax_minor=tax_minor,
        total_minor=total_minor,
        line_items=[
            {
                "plan": plan.code,
                "period": price.period_code,
                "quantity": 1,
                "unit_amount_minor": price.amount_minor,
            }
        ],
        invoice_metadata={
            "checkout_id": checkout.id,
            "price_id": price.id,
            "coupon": coupon.code if coupon else None,
            "tax_code": tax_rate.code if tax_rate else None,
        },
    )
    session.add(invoice)
    await session.flush()
    transaction = BillingTransaction(
        organization_id=actor.organization_id,
        user_id=actor.id,
        invoice_id=invoice.id,
        provider=price.provider,
        status="pending",
        amount_minor=total_minor,
        currency=price.currency,
        idempotency_key=f"checkout:{key}",
        transaction_metadata={
            "checkout_id": checkout.id,
            "plan_code": plan.code,
            "plan_id": plan.id,
            "price_id": price.id,
        },
    )
    session.add(transaction)
    if coupon is not None:
        coupon.redeemed_count += 1
        session.add(
            BillingCouponRedemption(
                coupon_id=coupon.id,
                organization_id=actor.organization_id,
                checkout_session_id=checkout.id,
                discount_minor=discount_minor,
            )
        )
    session.add(
        _audit(
            actor,
            "billing.checkout.requested",
            "billing_checkout",
            checkout.id,
            {
                "organization_id": actor.organization_id,
                "provider": price.provider,
                "plan": plan.code,
                "period": price.period_code,
                "amount_minor": total_minor,
                "currency": price.currency,
            },
        )
    )
    await session.commit()

    try:
        if price.provider == "stripe":
            result = await _stripe_checkout(
                checkout,
                actor,
                plan,
                price,
                idempotency_key=key,
                transport=transport,
            )
        elif price.provider == "paypal":
            result = await _paypal_checkout(
                checkout,
                actor,
                plan,
                price,
                idempotency_key=key,
                transport=transport,
            )
        elif price.provider == "paddle":
            result = await _paddle_checkout(
                checkout,
                actor,
                plan,
                price,
                idempotency_key=key,
                transport=transport,
            )
        else:
            result = await _offline_checkout(checkout, price)
        checkout.external_reference = result["external_reference"]
        checkout.checkout_url = result.get("checkout_url")
        checkout.status = str(result.get("status") or "created")
        if result.get("instructions"):
            checkout.session_metadata = {
                **dict(checkout.session_metadata or {}),
                "instructions": _redact_event(result["instructions"]),
            }
        if result.get("expires_at"):
            checkout.expires_at = datetime.fromtimestamp(int(result["expires_at"]), UTC)
        transaction.external_reference = result["external_reference"]
        await session.commit()
    except Exception as exc:
        checkout.status = "failed"
        transaction.status = "failed"
        transaction.transaction_metadata = {
            **dict(transaction.transaction_metadata or {}),
            "error_type": type(exc).__name__,
        }
        invoice.status = "void"
        await _release_coupon_reservation(session, checkout.id)
        await session.commit()
        raise
    return checkout_snapshot(checkout)


def checkout_snapshot(item: BillingCheckoutSession) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.provider,
        "status": item.status,
        "checkout_url": item.checkout_url,
        "expires_at": _as_utc(item.expires_at).isoformat() if item.expires_at else None,
        "completed_at": (
            _as_utc(item.completed_at).isoformat() if item.completed_at else None
        ),
        "summary": dict(item.session_metadata or {}),
    }


def _stripe_signature(raw: bytes, header: str) -> str:
    values: dict[str, list[str]] = {}
    for part in header.split(","):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            values.setdefault(key, []).append(value)
    timestamp = (values.get("t") or [""])[0]
    if not timestamp.isdigit():
        raise HTTPException(
            status_code=400, detail="Invalid Stripe signature timestamp"
        )
    if (
        abs(int(now().timestamp()) - int(timestamp))
        > settings.PAYMENTS_WEBHOOK_TOLERANCE_SECONDS
    ):
        raise HTTPException(
            status_code=400, detail="Stripe webhook timestamp is outside tolerance"
        )
    secret = (settings.STRIPE_WEBHOOK_SECRET or "").encode()
    expected = hmac.new(
        secret, timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    if not any(
        hmac.compare_digest(expected, supplied) for supplied in values.get("v1", [])
    ):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
    return expected


def _paddle_signature(raw: bytes, header: str) -> str:
    values = dict(
        part.strip().split("=", 1) for part in header.split(";") if "=" in part
    )
    timestamp = values.get("ts", "")
    supplied = values.get("h1", "")
    if not timestamp.isdigit() or not supplied:
        raise HTTPException(status_code=400, detail="Invalid Paddle signature")
    if (
        abs(int(now().timestamp()) - int(timestamp))
        > settings.PAYMENTS_WEBHOOK_TOLERANCE_SECONDS
    ):
        raise HTTPException(
            status_code=400, detail="Paddle webhook timestamp is outside tolerance"
        )
    expected = hmac.new(
        (settings.PADDLE_WEBHOOK_SECRET or "").encode(),
        timestamp.encode() + b":" + raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook signature")
    return expected


async def _verify_paypal(
    payload: dict[str, Any],
    headers: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    if not settings.PAYPAL_WEBHOOK_ID:
        raise HTTPException(
            status_code=503, detail="PayPal webhook verification is not configured"
        )
    oauth_value = await _paypal_token(transport)
    normalized = {key.lower(): value for key, value in headers.items()}
    required = [
        "paypal-auth-algo",
        "paypal-cert-url",
        "paypal-transmission-id",
        "paypal-transmission-sig",
        "paypal-transmission-time",
    ]
    if not all(normalized.get(key) for key in required):
        raise HTTPException(
            status_code=400, detail="PayPal webhook headers are incomplete"
        )
    body = {
        "auth_algo": normalized["paypal-auth-algo"],
        "cert_url": normalized["paypal-cert-url"],
        "transmission_id": normalized["paypal-transmission-id"],
        "transmission_sig": normalized["paypal-transmission-sig"],
        "transmission_time": normalized["paypal-transmission-time"],
        "webhook_id": settings.PAYPAL_WEBHOOK_ID,
        "webhook_event": payload,
    }
    async with httpx.AsyncClient(
        base_url=settings.PAYPAL_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {oauth_value}"},
            json=body,
        )
    if (
        response.status_code >= 400
        or response.json().get("verification_status") != "SUCCESS"
    ):
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature")


async def verify_webhook(
    provider: str,
    raw: bytes,
    headers: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    normalized = provider.strip().lower()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Webhook payload is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")
    lowered = {key.lower(): value for key, value in headers.items()}
    if normalized == "stripe":
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=503, detail="Stripe webhook verification is not configured"
            )
        _stripe_signature(raw, lowered.get("stripe-signature", ""))
    elif normalized == "paddle":
        if not settings.PADDLE_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=503, detail="Paddle webhook verification is not configured"
            )
        _paddle_signature(raw, lowered.get("paddle-signature", ""))
    elif normalized == "paypal":
        await _verify_paypal(payload, lowered, transport)
    elif normalized in {"paymob", "fawry", "stc_pay"}:
        secret = {
            "paymob": settings.PAYMOB_WEBHOOK_SECRET,
            "fawry": settings.FAWRY_WEBHOOK_SECRET,
            "stc_pay": settings.STC_PAY_WEBHOOK_SECRET,
        }[normalized]
        supplied = lowered.get("x-aios-signature", "")
        expected = hmac.new((secret or "").encode(), raw, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, supplied):
            raise HTTPException(
                status_code=400, detail="Invalid local-provider webhook signature"
            )
    else:
        raise HTTPException(status_code=404, detail="Webhook provider not found")
    return payload


def _event_identity(provider: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    if provider == "paddle":
        return str(payload.get("event_id") or payload.get("id") or ""), str(
            payload.get("event_type") or ""
        )
    return str(payload.get("id") or ""), str(
        payload.get("type") or payload.get("event_type") or ""
    )


def _event_object(provider: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if provider == "stripe":
        return dict(((payload.get("data") or {}).get("object") or {}))
    if provider == "paddle":
        return dict(payload.get("data") or {})
    return dict(payload.get("resource") or payload.get("data") or payload)


def _metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata") or payload.get("custom_data") or {}
    return dict(value) if isinstance(value, Mapping) else {}


async def _sync_verified_payment_method(
    session: AsyncSession,
    account: BillingAccount,
    provider: str,
    payload: Mapping[str, Any],
) -> None:
    customer_reference = str(
        payload.get("customer")
        or payload.get("customer_id")
        or (
            (payload.get("subscriber") or {}).get("payer_id")
            if isinstance(payload.get("subscriber"), Mapping)
            else ""
        )
        or ""
    )
    if customer_reference:
        account.provider_customers = {
            **dict(account.provider_customers or {}),
            provider: customer_reference[:255],
        }

    details = (
        payload.get("payment_method_details") or payload.get("payment_source") or {}
    )
    if not isinstance(details, Mapping):
        details = {}
    card = details.get("card") if isinstance(details.get("card"), Mapping) else details
    if not isinstance(card, Mapping):
        card = {}
    external_reference = str(
        payload.get("payment_method") or details.get("id") or card.get("id") or ""
    )
    if not external_reference:
        return
    method = await session.scalar(
        select(BillingPaymentMethod).where(
            BillingPaymentMethod.provider == provider,
            BillingPaymentMethod.external_reference == external_reference,
        )
    )
    method_type = str(
        details.get("type") or payload.get("payment_method_type") or "card"
    )[:40]
    brand = str(card.get("brand") or details.get("brand") or "")[:40] or None
    last4_raw = str(card.get("last4") or details.get("last4") or "")
    last4 = last4_raw[-4:] if len(last4_raw) >= 4 else None
    expiry_month = card.get("exp_month") or details.get("expiry_month")
    expiry_year = card.get("exp_year") or details.get("expiry_year")
    if method is None:
        has_default = await session.scalar(
            select(BillingPaymentMethod.id).where(
                BillingPaymentMethod.organization_id == account.organization_id,
                BillingPaymentMethod.status == "active",
                BillingPaymentMethod.is_default.is_(True),
            )
        )
        method = BillingPaymentMethod(
            organization_id=account.organization_id,
            provider=provider,
            external_reference=external_reference[:255],
            method_type=method_type,
            brand=brand,
            last4=last4,
            expiry_month=int(expiry_month) if expiry_month else None,
            expiry_year=int(expiry_year) if expiry_year else None,
            is_default=has_default is None,
            status="active",
        )
        session.add(method)
    else:
        method.organization_id = account.organization_id
        method.method_type = method_type
        method.brand = brand
        method.last4 = last4
        method.expiry_month = int(expiry_month) if expiry_month else None
        method.expiry_year = int(expiry_year) if expiry_year else None
        method.status = "active"


async def process_webhook_event(
    session: AsyncSession,
    provider: str,
    payload: dict[str, Any],
    raw: bytes,
) -> dict[str, Any]:
    provider = provider.strip().lower()
    event_id, event_type = _event_identity(provider, payload)
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Webhook event identity is missing")
    existing = await session.scalar(
        select(BillingWebhookEvent).where(
            BillingWebhookEvent.provider == provider,
            BillingWebhookEvent.external_event_id == event_id,
        )
    )
    if existing is not None:
        return {
            "accepted": True,
            "duplicate": True,
            "event_id": existing.id,
            "status": existing.status,
        }
    event = BillingWebhookEvent(
        provider=provider,
        external_event_id=event_id,
        event_type=event_type,
        payload_hash=hashlib.sha256(raw).hexdigest(),
        event_payload=_redact_event(payload),
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return {"accepted": True, "duplicate": True, "status": "processed"}
    try:
        obj = _event_object(provider, payload)
        metadata = _metadata(obj)
        checkout_id = str(
            metadata.get("checkout_id")
            or obj.get("client_reference_id")
            or obj.get("custom_id")
            or ""
        )
        organization_id = str(metadata.get("organization_id") or "")
        checkout = (
            await session.get(BillingCheckoutSession, checkout_id)
            if checkout_id
            else None
        )
        if checkout is not None:
            organization_id = checkout.organization_id
        if event_type in {
            "checkout.session.completed",
            "PAYMENT.CAPTURE.COMPLETED",
            "BILLING.SUBSCRIPTION.ACTIVATED",
            "transaction.completed",
        }:
            if checkout is None:
                raise ValueError("checkout session not found for completed event")
            checkout.status = "completed"
            checkout.completed_at = now()
            external_subscription = (
                str(obj.get("subscription") or obj.get("id") or "") or None
            )
            subscription = await session.scalar(
                select(BillingSubscription)
                .where(
                    BillingSubscription.organization_id == checkout.organization_id,
                    BillingSubscription.provider == provider,
                    BillingSubscription.status.in_(("pending", "active", "trialing")),
                )
                .order_by(BillingSubscription.created_at.desc())
                .limit(1)
            )
            if subscription is None:
                price = await session.get(BillingPrice, checkout.price_id)
                subscription = BillingSubscription(
                    organization_id=checkout.organization_id,
                    plan_id=checkout.plan_id,
                    price_id=checkout.price_id,
                    provider=provider,
                    external_reference=external_subscription,
                    status="active",
                    current_period_start=now(),
                    current_period_end=now()
                    + timedelta(days=30 * max(1, price.months if price else 1)),
                    subscription_metadata={"checkout_id": checkout.id},
                )
                session.add(subscription)
                await session.flush()
            else:
                subscription.status = "active"
                subscription.external_reference = (
                    external_subscription or subscription.external_reference
                )
            account = await ensure_billing_account(
                session, checkout.organization_id, lock=True
            )
            plan = await session.get(BillingPlan, checkout.plan_id)
            account.plan_id = checkout.plan_id
            account.status = "active"
            account.limits = dict(plan.limits or {}) if plan else {}
            account.entitlements = list(plan.entitlements or []) if plan else []
            account.current_period_end = subscription.current_period_end
            await _sync_verified_payment_method(session, account, provider, obj)
            organization = await session.get(Organization, checkout.organization_id)
            if organization is not None and plan is not None:
                organization.plan = plan.code
                organization.status = "active"
            transaction = await session.scalar(
                select(BillingTransaction)
                .where(
                    BillingTransaction.transaction_metadata["checkout_id"].as_string()
                    == checkout.id
                )
                .order_by(BillingTransaction.created_at.desc())
                .limit(1)
            )
            if transaction is not None:
                transaction.status = "succeeded"
                transaction.external_reference = (
                    str(
                        obj.get("payment_intent")
                        or obj.get("id")
                        or transaction.external_reference
                        or ""
                    )
                    or None
                )
                transaction.completed_at = now()
                invoice = (
                    await session.get(BillingInvoice, transaction.invoice_id)
                    if transaction.invoice_id
                    else None
                )
                if invoice is not None:
                    invoice.status = "paid"
                    invoice.amount_paid_minor = invoice.total_minor
                    invoice.paid_at = now()
                    invoice.external_reference = (
                        str(obj.get("invoice") or invoice.external_reference or "")
                        or None
                    )
            await _notify_owner_and_org(
                session,
                checkout.organization_id,
                title="Subscription activated",
                message="The organization subscription was activated from a verified payment event.",
                event_type="billing.subscription.activated",
            )
        elif event_type in {
            "invoice.paid",
            "INVOICING.INVOICE.PAID",
            "transaction.paid",
        }:
            external = str(obj.get("id") or "")
            invoice = await session.scalar(
                select(BillingInvoice).where(
                    BillingInvoice.provider == provider,
                    BillingInvoice.external_reference == external,
                )
            )
            if invoice is not None:
                invoice.status = "paid"
                invoice.amount_paid_minor = invoice.total_minor
                invoice.paid_at = now()
        elif event_type in {
            "invoice.payment_failed",
            "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
            "transaction.payment_failed",
        }:
            if not organization_id:
                organization_id = checkout.organization_id if checkout else ""
            if organization_id:
                account = await ensure_billing_account(
                    session, organization_id, lock=True
                )
                account.status = "past_due"
                await _notify_owner_and_org(
                    session,
                    organization_id,
                    title="Payment failed",
                    message="A subscription payment failed and the billing account is past due.",
                    event_type="billing.payment.failed",
                    severity="warning",
                )
        elif event_type in {
            "customer.subscription.deleted",
            "BILLING.SUBSCRIPTION.CANCELLED",
            "subscription.canceled",
        }:
            external = str(obj.get("id") or "")
            subscription = await session.scalar(
                select(BillingSubscription).where(
                    BillingSubscription.provider == provider,
                    BillingSubscription.external_reference == external,
                )
            )
            if subscription is not None:
                subscription.status = "canceled"
                subscription.canceled_at = now()
                account = await ensure_billing_account(
                    session, subscription.organization_id, lock=True
                )
                account.status = "suspended"
                account.suspended_at = now()
        elif event_type in {
            "charge.refunded",
            "PAYMENT.CAPTURE.REFUNDED",
            "adjustment.updated",
        }:
            external = str(obj.get("payment_intent") or obj.get("id") or "")
            transaction = await session.scalar(
                select(BillingTransaction).where(
                    BillingTransaction.provider == provider,
                    BillingTransaction.external_reference == external,
                )
            )
            if transaction is not None:
                transaction.status = "refunded"
        event.status = "processed"
        event.processed_at = now()
        session.add(
            _audit(
                None,
                "billing.webhook.processed",
                "billing_webhook",
                event.id,
                {
                    "organization_id": organization_id or None,
                    "provider": provider,
                    "event_type": event_type,
                },
            )
        )
        await session.commit()
    except Exception as exc:
        event.status = "failed"
        event.error = type(exc).__name__
        await session.commit()
        raise HTTPException(
            status_code=409, detail="Webhook was verified but could not be reconciled"
        ) from exc
    return {
        "accepted": True,
        "duplicate": False,
        "event_id": event.id,
        "status": event.status,
    }


async def billing_summary(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    catalog = await sync_catalog(session)
    context = await billing_context(session, actor.organization_id)
    account: BillingAccount = context["account"]
    plan: BillingPlan | None = context["plan"]
    subscription: BillingSubscription | None = context["subscription"]
    invoices = (
        await session.scalars(
            select(BillingInvoice)
            .where(BillingInvoice.organization_id == actor.organization_id)
            .order_by(BillingInvoice.created_at.desc())
            .limit(50)
        )
    ).all()
    transactions = (
        await session.scalars(
            select(BillingTransaction)
            .where(BillingTransaction.organization_id == actor.organization_id)
            .order_by(BillingTransaction.created_at.desc())
            .limit(50)
        )
    ).all()
    wallet = await ensure_wallet(session, actor.organization_id)
    await session.commit()
    return {
        "account": {
            "id": account.id,
            "status": account.status,
            "licensed_seats": account.licensed_seats,
            "plan": plan.code if plan else None,
            "plan_name": plan.name if plan else None,
            "limits": context["limits"],
            "entitlements": context["entitlements"],
            "usage": context["usage"],
            "current_period_end": (
                _as_utc(account.current_period_end).isoformat()
                if account.current_period_end
                else None
            ),
        },
        "subscription": subscription_snapshot(subscription) if subscription else None,
        "invoices": [invoice_snapshot(item) for item in invoices],
        "transactions": [transaction_snapshot(item) for item in transactions],
        "wallet": wallet_snapshot(wallet),
        "catalog_version": catalog["source_version"],
    }


def subscription_snapshot(item: BillingSubscription) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.provider,
        "status": item.status,
        "cancel_at_period_end": item.cancel_at_period_end,
        "current_period_start": (
            _as_utc(item.current_period_start).isoformat()
            if item.current_period_start
            else None
        ),
        "current_period_end": (
            _as_utc(item.current_period_end).isoformat()
            if item.current_period_end
            else None
        ),
        "canceled_at": (
            _as_utc(item.canceled_at).isoformat() if item.canceled_at else None
        ),
    }


def invoice_snapshot(item: BillingInvoice) -> dict[str, Any]:
    return {
        "id": item.id,
        "number": item.number,
        "provider": item.provider,
        "status": item.status,
        "currency": item.currency,
        "subtotal_minor": item.subtotal_minor,
        "discount_minor": item.discount_minor,
        "tax_minor": item.tax_minor,
        "total_minor": item.total_minor,
        "amount_paid_minor": item.amount_paid_minor,
        "amount_refunded_minor": item.amount_refunded_minor,
        "line_items": item.line_items,
        "created_at": _as_utc(item.created_at).isoformat(),
        "paid_at": _as_utc(item.paid_at).isoformat() if item.paid_at else None,
    }


def transaction_snapshot(item: BillingTransaction) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.provider,
        "type": item.transaction_type,
        "status": item.status,
        "amount_minor": item.amount_minor,
        "currency": item.currency,
        "created_at": _as_utc(item.created_at).isoformat(),
        "completed_at": (
            _as_utc(item.completed_at).isoformat() if item.completed_at else None
        ),
    }


async def ensure_wallet(
    session: AsyncSession, organization_id: str, *, lock: bool = False
) -> BillingWallet:
    statement = select(BillingWallet).where(
        BillingWallet.organization_id == organization_id
    )
    if lock:
        statement = statement.with_for_update()
    wallet = await session.scalar(statement)
    if wallet is None:
        wallet = BillingWallet(
            organization_id=organization_id, currency=_currency(None), balance_minor=0
        )
        session.add(wallet)
        await session.flush()
    return wallet


def wallet_snapshot(wallet: BillingWallet) -> dict[str, Any]:
    return {
        "id": wallet.id,
        "currency": wallet.currency,
        "balance_minor": wallet.balance_minor,
        "status": wallet.status,
    }


async def post_wallet_entry(
    session: AsyncSession,
    organization_id: str,
    *,
    amount_minor: int,
    idempotency_key: str,
    entry_type: str,
    description: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> BillingWalletEntry:
    existing = await session.scalar(
        select(BillingWalletEntry).where(
            BillingWalletEntry.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing
    wallet = await ensure_wallet(session, organization_id, lock=True)
    next_balance = wallet.balance_minor + amount_minor
    if next_balance < 0:
        raise HTTPException(
            status_code=402, detail="Wallet credit balance is insufficient"
        )
    wallet.balance_minor = next_balance
    entry = BillingWalletEntry(
        wallet_id=wallet.id,
        entry_type=entry_type,
        amount_minor=amount_minor,
        balance_after_minor=next_balance,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
    )
    session.add(entry)
    await session.flush()
    return entry


def _period_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    current = (moment or now()).astimezone(UTC)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def record_usage(
    session: AsyncSession,
    organization_id: str,
    *,
    metric: str,
    quantity: int,
    idempotency_key: str,
) -> dict[str, Any]:
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Usage quantity must be positive")
    existing_entry = await session.scalar(
        select(BillingWalletEntry).where(
            BillingWalletEntry.idempotency_key == f"usage:{idempotency_key}"
        )
    )
    if existing_entry is not None:
        usage = await session.scalar(
            select(BillingUsageRecord).where(
                BillingUsageRecord.id == existing_entry.reference_id
            )
        )
        return usage_snapshot(usage) if usage else {"idempotent": True}
    context = await billing_context(session, organization_id)
    plan: BillingPlan | None = context["plan"]
    metering = dict(plan.metering or {}) if plan else {}
    rule = dict(metering.get(metric) or {})
    included = int(rule.get("included") or context["limits"].get(metric) or 0)
    unit_size = max(1, int(rule.get("unit_size") or 1))
    unit_price_minor = max(0, int(rule.get("unit_price_minor") or 0))
    currency = _currency(
        rule.get("currency") or (plan.default_currency if plan else None)
    )
    start, end = _period_bounds()
    usage = await session.scalar(
        select(BillingUsageRecord)
        .where(
            BillingUsageRecord.organization_id == organization_id,
            BillingUsageRecord.metric == metric,
            BillingUsageRecord.period_start == start,
        )
        .with_for_update()
    )
    if usage is None:
        usage = BillingUsageRecord(
            organization_id=organization_id,
            metric=metric,
            included_quantity=included,
            period_start=start,
            period_end=end,
            currency=currency,
        )
        session.add(usage)
        await session.flush()
    previous_billable = usage.billable_quantity
    usage.quantity += quantity
    usage.billable_quantity = max(0, usage.quantity - included)
    newly_billable = max(0, usage.billable_quantity - previous_billable)
    charge = (
        math.ceil(newly_billable / unit_size) * unit_price_minor
        if newly_billable and unit_price_minor
        else 0
    )
    usage.charge_minor += charge
    usage.last_event_at = now()
    if charge:
        await post_wallet_entry(
            session,
            organization_id,
            amount_minor=-charge,
            idempotency_key=f"usage:{idempotency_key}",
            entry_type="debit",
            description=f"Metered usage: {metric}",
            reference_type="billing_usage",
            reference_id=usage.id,
        )
    else:
        # Zero-value ledger entry still makes the usage event idempotent.
        await post_wallet_entry(
            session,
            organization_id,
            amount_minor=0,
            idempotency_key=f"usage:{idempotency_key}",
            entry_type="usage",
            description=f"Included usage: {metric}",
            reference_type="billing_usage",
            reference_id=usage.id,
        )
    await session.commit()
    return usage_snapshot(usage)


def usage_snapshot(item: BillingUsageRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "metric": item.metric,
        "quantity": item.quantity,
        "included_quantity": item.included_quantity,
        "billable_quantity": item.billable_quantity,
        "charge_minor": item.charge_minor,
        "currency": item.currency,
        "period_start": _as_utc(item.period_start).isoformat(),
        "period_end": _as_utc(item.period_end).isoformat(),
    }


async def cancel_subscription(
    session: AsyncSession,
    actor: UserRecord,
    *,
    immediately: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    subscription = await session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.organization_id == actor.organization_id,
            BillingSubscription.status.in_(("active", "trialing", "past_due")),
        )
        .order_by(BillingSubscription.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Active subscription not found")

    effective_immediately = immediately
    if subscription.provider in EXTERNAL_SUBSCRIPTION_PROVIDERS:
        if not subscription.external_reference:
            raise HTTPException(
                status_code=409,
                detail="Provider subscription reference is missing",
            )
        if subscription.provider == "stripe":
            if not settings.STRIPE_SECRET_KEY:
                raise HTTPException(status_code=503, detail="Stripe is not configured")
            async with httpx.AsyncClient(
                base_url=settings.STRIPE_API_BASE,
                timeout=30,
                transport=transport,
            ) as client:
                if immediately:
                    response = await client.delete(
                        f"/v1/subscriptions/{subscription.external_reference}",
                        headers={
                            "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"
                        },
                    )
                else:
                    response = await client.post(
                        f"/v1/subscriptions/{subscription.external_reference}",
                        headers={
                            "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        content=urlencode({"cancel_at_period_end": "true"}),
                    )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail="Stripe cancellation failed"
                )
        elif subscription.provider == "paypal":
            oauth_value = await _paypal_token(transport)
            async with httpx.AsyncClient(
                base_url=settings.PAYPAL_API_BASE,
                timeout=30,
                transport=transport,
            ) as client:
                response = await client.post(
                    f"/v1/billing/subscriptions/{subscription.external_reference}/cancel",
                    headers={"Authorization": f"Bearer {oauth_value}"},
                    json={"reason": "Customer requested cancellation in AIONEX AIOS"},
                )
            if response.status_code not in {200, 204}:
                raise HTTPException(
                    status_code=502, detail="PayPal cancellation failed"
                )
            # PayPal's cancel operation is immediate.
            effective_immediately = True
        elif subscription.provider == "paddle":
            if not settings.PADDLE_API_KEY:
                raise HTTPException(status_code=503, detail="Paddle is not configured")
            async with httpx.AsyncClient(
                base_url=settings.PADDLE_API_BASE,
                timeout=30,
                transport=transport,
            ) as client:
                response = await client.post(
                    f"/subscriptions/{subscription.external_reference}/cancel",
                    headers={"Authorization": f"Bearer {settings.PADDLE_API_KEY}"},
                    json={
                        "effective_from": (
                            "immediately" if immediately else "next_billing_period"
                        )
                    },
                )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail="Paddle cancellation failed"
                )

    if effective_immediately:
        subscription.status = "canceled"
        subscription.canceled_at = now()
        subscription.cancel_at_period_end = False
        account = await ensure_billing_account(
            session, actor.organization_id, lock=True
        )
        account.status = "suspended"
        account.suspended_at = now()
    else:
        subscription.cancel_at_period_end = True
    session.add(
        _audit(
            actor,
            "billing.subscription.cancelled",
            "billing_subscription",
            subscription.id,
            {
                "organization_id": actor.organization_id,
                "requested_immediately": immediately,
                "effective_immediately": effective_immediately,
                "provider": subscription.provider,
            },
        )
    )
    await _notify_owner_and_org(
        session,
        actor.organization_id,
        title="Subscription cancellation requested",
        message=(
            "The subscription was canceled immediately."
            if effective_immediately
            else "The subscription will end at the current billing-period boundary."
        ),
        event_type="billing.subscription.cancelled",
        severity="warning",
    )
    await session.commit()
    return subscription_snapshot(subscription)


async def list_payment_methods(
    session: AsyncSession, organization_id: str
) -> list[dict[str, Any]]:
    items = (
        await session.scalars(
            select(BillingPaymentMethod)
            .where(
                BillingPaymentMethod.organization_id == organization_id,
                BillingPaymentMethod.status == "active",
            )
            .order_by(
                BillingPaymentMethod.is_default.desc(),
                BillingPaymentMethod.created_at.desc(),
            )
        )
    ).all()
    return [
        {
            "id": item.id,
            "provider": item.provider,
            "type": item.method_type,
            "brand": item.brand,
            "last4": item.last4,
            "expiry_month": item.expiry_month,
            "expiry_year": item.expiry_year,
            "is_default": item.is_default,
        }
        for item in items
    ]


async def set_default_payment_method(
    session: AsyncSession, actor: UserRecord, method_id: str
) -> dict[str, Any]:
    method = await session.scalar(
        select(BillingPaymentMethod)
        .where(
            BillingPaymentMethod.id == method_id,
            BillingPaymentMethod.organization_id == actor.organization_id,
            BillingPaymentMethod.status == "active",
        )
        .with_for_update()
    )
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    await session.execute(
        update(BillingPaymentMethod)
        .where(BillingPaymentMethod.organization_id == actor.organization_id)
        .values(is_default=False)
    )
    method.is_default = True
    session.add(
        _audit(
            actor,
            "billing.payment_method.default",
            "billing_payment_method",
            method.id,
            {"organization_id": actor.organization_id},
        )
    )
    await session.commit()
    return (await list_payment_methods(session, actor.organization_id))[0]


async def remove_payment_method(
    session: AsyncSession, actor: UserRecord, method_id: str
) -> None:
    method = await session.scalar(
        select(BillingPaymentMethod)
        .where(
            BillingPaymentMethod.id == method_id,
            BillingPaymentMethod.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    method.status = "removed"
    method.is_default = False
    session.add(
        _audit(
            actor,
            "billing.payment_method.removed",
            "billing_payment_method",
            method.id,
            {"organization_id": actor.organization_id},
        )
    )
    await session.commit()


async def owner_overview(session: AsyncSession) -> dict[str, Any]:
    catalog = await sync_catalog(session)
    accounts = (
        await session.execute(
            select(BillingAccount, Organization, BillingPlan)
            .join(Organization, Organization.id == BillingAccount.organization_id)
            .outerjoin(BillingPlan, BillingPlan.id == BillingAccount.plan_id)
            .order_by(Organization.name)
        )
    ).all()
    invoices = (
        await session.scalars(
            select(BillingInvoice).order_by(BillingInvoice.created_at.desc()).limit(200)
        )
    ).all()
    transactions = (
        await session.scalars(
            select(BillingTransaction)
            .order_by(BillingTransaction.created_at.desc())
            .limit(200)
        )
    ).all()
    refunds = (
        await session.scalars(
            select(BillingRefund).order_by(BillingRefund.created_at.desc()).limit(200)
        )
    ).all()
    webhooks = (
        await session.scalars(
            select(BillingWebhookEvent)
            .order_by(BillingWebhookEvent.created_at.desc())
            .limit(100)
        )
    ).all()
    licenses = (
        await session.scalars(
            select(BillingLicense).order_by(BillingLicense.created_at.desc()).limit(200)
        )
    ).all()
    coupons = (
        await session.scalars(
            select(BillingCoupon).order_by(BillingCoupon.created_at.desc()).limit(200)
        )
    ).all()
    tax_rates = (
        await session.scalars(
            select(BillingTaxRate)
            .order_by(BillingTaxRate.country_code, BillingTaxRate.code)
            .limit(500)
        )
    ).all()
    usage_records = (
        await session.scalars(
            select(BillingUsageRecord)
            .order_by(BillingUsageRecord.period_start.desc(), BillingUsageRecord.metric)
            .limit(500)
        )
    ).all()
    wallet_rows = (
        await session.execute(
            select(BillingWallet, Organization)
            .join(Organization, Organization.id == BillingWallet.organization_id)
            .order_by(Organization.name)
        )
    ).all()
    reconciliation_runs = (
        await session.scalars(
            select(BillingReconciliationRun)
            .order_by(BillingReconciliationRun.created_at.desc())
            .limit(100)
        )
    ).all()
    successful = [item for item in transactions if item.status == "succeeded"]
    return {
        "catalog": catalog,
        "accounts": [
            {
                "id": account.id,
                "organization_id": organization.id,
                "organization": organization.name,
                "organization_status": organization.status,
                "plan": plan.code if plan else None,
                "plan_name": plan.name if plan else None,
                "status": account.status,
                "licensed_seats": account.licensed_seats,
                "active_seats": int(
                    await session.scalar(
                        select(func.count(User.id)).where(
                            User.organization_id == organization.id,
                            User.deleted_at.is_(None),
                            User.status.in_(("active", "online")),
                        )
                    )
                    or 0
                ),
                "limits": account.limits,
                "entitlements": account.entitlements,
                "current_period_end": (
                    _as_utc(account.current_period_end).isoformat()
                    if account.current_period_end
                    else None
                ),
                "protected": organization.id == "aionex-org",
            }
            for account, organization, plan in accounts
        ],
        "invoices": [
            invoice_snapshot(item) | {"organization_id": item.organization_id}
            for item in invoices
        ],
        "transactions": [
            transaction_snapshot(item) | {"organization_id": item.organization_id}
            for item in transactions
        ],
        "refunds": [
            {
                "id": item.id,
                "organization_id": item.organization_id,
                "transaction_id": item.transaction_id,
                "provider": item.provider,
                "amount_minor": item.amount_minor,
                "currency": item.currency,
                "reason": item.reason,
                "status": item.status,
                "created_at": _as_utc(item.created_at).isoformat(),
            }
            for item in refunds
        ],
        "webhooks": [
            {
                "id": item.id,
                "provider": item.provider,
                "event_type": item.event_type,
                "status": item.status,
                "created_at": _as_utc(item.created_at).isoformat(),
                "processed_at": (
                    _as_utc(item.processed_at).isoformat()
                    if item.processed_at
                    else None
                ),
            }
            for item in webhooks
        ],
        "licenses": [license_snapshot(item) for item in licenses],
        "coupons": [coupon_snapshot(item) for item in coupons],
        "tax_rates": [tax_snapshot(item) for item in tax_rates],
        "wallets": [
            wallet_snapshot(wallet)
            | {
                "organization_id": organization.id,
                "organization": organization.name,
            }
            for wallet, organization in wallet_rows
        ],
        "usage": [
            usage_snapshot(item) | {"organization_id": item.organization_id}
            for item in usage_records
        ],
        "reconciliation_runs": [
            {
                "id": item.id,
                "provider": item.provider,
                "status": item.status,
                "summary": dict(item.summary or {}),
                "created_at": _as_utc(item.created_at).isoformat(),
                "completed_at": (
                    _as_utc(item.completed_at).isoformat()
                    if item.completed_at
                    else None
                ),
            }
            for item in reconciliation_runs
        ],
        "summary": {
            "gross_minor": sum(item.amount_minor for item in successful),
            "refunded_minor": sum(
                item.amount_minor for item in refunds if item.status == "succeeded"
            ),
            "successful_transactions": len(successful),
            "failed_transactions": sum(
                item.status == "failed" for item in transactions
            ),
            "open_invoices": sum(
                item.status in {"draft", "open", "past_due"} for item in invoices
            ),
            "active_accounts": sum(
                account.status in ACTIVE_ACCOUNT_STATUSES for account, _, _ in accounts
            ),
            "wallet_balance_minor": sum(
                wallet.balance_minor for wallet, _ in wallet_rows
            ),
            "usage_charge_minor": sum(item.charge_minor for item in usage_records),
        },
        "providers": provider_readiness(),
    }


async def owner_update_account(
    session: AsyncSession,
    actor: UserRecord,
    organization_id: str,
    *,
    plan_code: str | None = None,
    seats: int | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    account = await ensure_billing_account(session, organization_id, lock=True)
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if seats is not None:
        active = int(
            await session.scalar(
                select(func.count(User.id)).where(
                    User.organization_id == organization_id,
                    User.deleted_at.is_(None),
                    User.status.in_(("active", "online")),
                )
            )
            or 0
        )
        if seats < max(1, active) or seats > 1_000_000:
            raise HTTPException(
                status_code=422, detail="Licensed seats cannot be below active users"
            )
        account.licensed_seats = seats
    if plan_code is not None:
        plan = await session.scalar(
            select(BillingPlan).where(
                BillingPlan.code == _normalized_plan_code(plan_code)
            )
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Billing plan not found")
        account.plan_id = plan.id
        account.limits = dict(plan.limits or {})
        account.entitlements = list(plan.entitlements or [])
        organization.plan = plan.code
    if action == "suspend":
        if organization.id == "aionex-org":
            raise HTTPException(
                status_code=422, detail="Platform billing account is protected"
            )
        account.status = "suspended"
        account.suspended_at = now()
        organization.status = "inactive"
    elif action == "restore":
        account.status = "active"
        account.suspended_at = None
        account.suspension_reason = None
        organization.status = "active"
    session.add(
        _audit(
            actor,
            "billing.account.updated",
            "billing_account",
            account.id,
            {
                "organization_id": organization_id,
                "plan_code": plan_code,
                "seats": seats,
                "action": action,
            },
        )
    )
    await session.commit()
    return next(
        item
        for item in (await owner_overview(session))["accounts"]
        if item["organization_id"] == organization_id
    )


async def owner_create_coupon(
    session: AsyncSession,
    actor: UserRecord,
    *,
    code: str,
    discount_type: str,
    percent_off: float | None,
    amount_off_minor: int | None,
    currency: str | None,
    max_redemptions: int | None,
    expires_at: datetime | None,
) -> dict[str, Any]:
    normalized = code.strip().upper()
    if not normalized or len(normalized) > 80:
        raise HTTPException(status_code=422, detail="Coupon code is invalid")
    if discount_type == "percent":
        if (
            percent_off is None
            or not (0 < percent_off <= 100)
            or amount_off_minor is not None
        ):
            raise HTTPException(
                status_code=422, detail="Percent coupon requires one valid percentage"
            )
        basis = int((Decimal(str(percent_off)) * Decimal(100)).quantize(Decimal("1")))
        amount = None
        money_currency = None
    elif discount_type == "fixed":
        if amount_off_minor is None or amount_off_minor <= 0 or percent_off is not None:
            raise HTTPException(
                status_code=422, detail="Fixed coupon requires one positive amount"
            )
        basis = None
        amount = amount_off_minor
        money_currency = _currency(currency)
    else:
        raise HTTPException(
            status_code=422, detail="Coupon type must be percent or fixed"
        )
    coupon = BillingCoupon(
        code=normalized,
        discount_type=discount_type,
        percent_off_basis_points=basis,
        amount_off_minor=amount,
        currency=money_currency,
        max_redemptions=max_redemptions,
        expires_at=expires_at,
    )
    session.add(coupon)
    session.add(
        _audit(
            actor,
            "billing.coupon.created",
            "billing_coupon",
            coupon.id,
            {
                "organization_id": actor.organization_id,
                "code": normalized,
                "type": discount_type,
            },
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Coupon code already exists"
        ) from exc
    return coupon_snapshot(coupon)


def coupon_snapshot(item: BillingCoupon) -> dict[str, Any]:
    return {
        "id": item.id,
        "code": item.code,
        "type": item.discount_type,
        "percent_off": (
            item.percent_off_basis_points / 100
            if item.percent_off_basis_points is not None
            else None
        ),
        "amount_off_minor": item.amount_off_minor,
        "currency": item.currency,
        "max_redemptions": item.max_redemptions,
        "redeemed_count": item.redeemed_count,
        "expires_at": _as_utc(item.expires_at).isoformat() if item.expires_at else None,
        "active": item.active,
    }


async def validate_coupon(
    session: AsyncSession, code: str, amount_minor: int, currency: str
) -> dict[str, Any]:
    coupon = await session.scalar(
        select(BillingCoupon).where(
            func.upper(BillingCoupon.code) == code.strip().upper()
        )
    )
    if coupon is None:
        raise HTTPException(status_code=404, detail="Coupon not found")
    discount = _coupon_discount(coupon, amount_minor, _currency(currency))
    return {
        "coupon": coupon_snapshot(coupon),
        "discount_minor": discount,
        "total_minor": max(0, amount_minor - discount),
    }


async def owner_upsert_tax(
    session: AsyncSession,
    actor: UserRecord,
    *,
    code: str,
    country_code: str,
    percentage: float,
    inclusive: bool,
) -> dict[str, Any]:
    country = country_code.strip().upper()
    if len(country) != 2 or not country.isalpha() or not (0 <= percentage <= 100):
        raise HTTPException(
            status_code=422, detail="Tax scope or percentage is invalid"
        )
    record = await session.scalar(
        select(BillingTaxRate)
        .where(
            BillingTaxRate.country_code == country,
            BillingTaxRate.region_code.is_(None),
            BillingTaxRate.code == code.strip().upper(),
        )
        .with_for_update()
    )
    basis = int((Decimal(str(percentage)) * Decimal(100)).quantize(Decimal("1")))
    if record is None:
        record = BillingTaxRate(
            code=code.strip().upper(),
            country_code=country,
            percentage_basis_points=basis,
            inclusive=inclusive,
        )
        session.add(record)
    else:
        record.percentage_basis_points = basis
        record.inclusive = inclusive
        record.active = True
    session.add(
        _audit(
            actor,
            "billing.tax.saved",
            "billing_tax",
            record.id,
            {
                "organization_id": actor.organization_id,
                "country": country,
                "code": record.code,
            },
        )
    )
    await session.commit()
    return tax_snapshot(record)


def tax_snapshot(item: BillingTaxRate) -> dict[str, Any]:
    return {
        "id": item.id,
        "code": item.code,
        "country_code": item.country_code,
        "region_code": item.region_code,
        "percentage": item.percentage_basis_points / 100,
        "inclusive": item.inclusive,
        "active": item.active,
    }


async def issue_license(
    session: AsyncSession,
    actor: UserRecord,
    organization_id: str,
    *,
    seats: int,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    account = await ensure_billing_account(session, organization_id, lock=True)
    if seats < 1 or seats > 1_000_000:
        raise HTTPException(status_code=422, detail="License seats are invalid")
    raw = f"AIONEX-{secrets.token_urlsafe(32)}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    license_record = BillingLicense(
        organization_id=organization_id,
        plan_id=account.plan_id,
        key_prefix=raw[:16],
        key_hash=digest,
        seats=seats,
        expires_at=expires_at,
        issued_at=now(),
    )
    session.add(license_record)
    account.licensed_seats = max(account.licensed_seats, seats)
    session.add(
        _audit(
            actor,
            "billing.license.issued",
            "billing_license",
            license_record.id,
            {"organization_id": organization_id, "seats": seats},
        )
    )
    await session.commit()
    return {**license_snapshot(license_record), "license_key": raw}


def license_snapshot(item: BillingLicense) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "key_prefix": item.key_prefix,
        "status": item.status,
        "seats": item.seats,
        "issued_at": _as_utc(item.issued_at).isoformat(),
        "expires_at": _as_utc(item.expires_at).isoformat() if item.expires_at else None,
        "revoked_at": _as_utc(item.revoked_at).isoformat() if item.revoked_at else None,
    }


async def revoke_license(
    session: AsyncSession, actor: UserRecord, license_id: str
) -> dict[str, Any]:
    record = await session.scalar(
        select(BillingLicense).where(BillingLicense.id == license_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="License not found")
    record.status = "revoked"
    record.revoked_at = now()
    session.add(
        _audit(
            actor,
            "billing.license.revoked",
            "billing_license",
            record.id,
            {"organization_id": record.organization_id},
        )
    )
    await session.commit()
    return license_snapshot(record)


async def owner_settle_transaction(
    session: AsyncSession,
    actor: UserRecord,
    transaction_id: str,
    *,
    succeeded: bool,
    external_reference: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    transaction = await session.scalar(
        select(BillingTransaction)
        .where(BillingTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.provider not in {"manual", "bank_transfer", "internal"}:
        raise HTTPException(
            status_code=409,
            detail="Only offline transactions can be settled manually",
        )
    if transaction.status not in {"pending", "failed"}:
        if (succeeded and transaction.status == "succeeded") or (
            not succeeded and transaction.status == "failed"
        ):
            return transaction_snapshot(transaction)
        raise HTTPException(status_code=409, detail="Transaction is already finalized")

    invoice = (
        await session.get(BillingInvoice, transaction.invoice_id)
        if transaction.invoice_id
        else None
    )
    checkout_id = str((transaction.transaction_metadata or {}).get("checkout_id") or "")
    checkout = (
        await session.get(BillingCheckoutSession, checkout_id) if checkout_id else None
    )
    reference = (
        (external_reference or "").strip()[:255]
        or transaction.external_reference
        or f"manual-{secrets.token_hex(8)}"
    )

    if succeeded:
        transaction.status = "succeeded"
        transaction.external_reference = reference
        transaction.completed_at = now()
        if invoice is not None:
            invoice.status = "paid"
            invoice.amount_paid_minor = invoice.total_minor
            invoice.paid_at = now()
            invoice.external_reference = reference
        if checkout is not None:
            checkout.status = "completed"
            checkout.completed_at = now()
            checkout.external_reference = reference
            price = await session.get(BillingPrice, checkout.price_id)
            subscription = await session.scalar(
                select(BillingSubscription)
                .where(
                    BillingSubscription.organization_id == checkout.organization_id,
                    BillingSubscription.subscription_metadata["checkout_id"].as_string()
                    == checkout.id,
                )
                .limit(1)
            )
            if subscription is None:
                subscription = BillingSubscription(
                    organization_id=checkout.organization_id,
                    plan_id=checkout.plan_id,
                    price_id=checkout.price_id,
                    provider=checkout.provider,
                    external_reference=reference,
                    status="active",
                    current_period_start=now(),
                    current_period_end=now()
                    + timedelta(days=30 * max(1, price.months if price else 1)),
                    subscription_metadata={"checkout_id": checkout.id},
                )
                session.add(subscription)
                await session.flush()
            account = await ensure_billing_account(
                session, checkout.organization_id, lock=True
            )
            plan = await session.get(BillingPlan, checkout.plan_id)
            account.plan_id = checkout.plan_id
            account.status = "active"
            account.suspended_at = None
            account.limits = dict(plan.limits or {}) if plan else {}
            account.entitlements = list(plan.entitlements or []) if plan else []
            account.current_period_end = subscription.current_period_end
            organization = await session.get(Organization, checkout.organization_id)
            if organization is not None and plan is not None:
                organization.plan = plan.code
                organization.status = "active"
    else:
        transaction.status = "failed"
        transaction.completed_at = now()
        if invoice is not None:
            invoice.status = "void"
        if checkout is not None:
            checkout.status = "failed"
            await _release_coupon_reservation(session, checkout.id)

    transaction.transaction_metadata = {
        **dict(transaction.transaction_metadata or {}),
        "owner_settlement_note": (note or "").strip()[:500],
        "owner_settlement_actor": actor.id,
    }
    session.add(
        _audit(
            actor,
            (
                "billing.transaction.settled"
                if succeeded
                else "billing.transaction.failed"
            ),
            "billing_transaction",
            transaction.id,
            {
                "organization_id": transaction.organization_id,
                "provider": transaction.provider,
                "amount_minor": transaction.amount_minor,
                "currency": transaction.currency,
            },
        )
    )
    await _notify_owner_and_org(
        session,
        transaction.organization_id,
        title=("Payment settled" if succeeded else "Payment marked failed"),
        message=(
            "An offline payment was settled and access was reconciled."
            if succeeded
            else "An offline payment was marked failed and no access was granted."
        ),
        event_type=(
            "billing.payment.settled" if succeeded else "billing.payment.failed"
        ),
        severity="info" if succeeded else "warning",
    )
    await session.commit()
    return transaction_snapshot(transaction)


async def owner_refund(
    session: AsyncSession,
    actor: UserRecord,
    transaction_id: str,
    *,
    amount_minor: int,
    reason: str,
    idempotency_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    existing = await session.scalar(
        select(BillingRefund).where(BillingRefund.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return {
            "id": existing.id,
            "status": existing.status,
            "amount_minor": existing.amount_minor,
            "currency": existing.currency,
        }
    transaction = await session.scalar(
        select(BillingTransaction)
        .where(BillingTransaction.id == transaction_id)
        .with_for_update()
    )
    if transaction is None or transaction.status not in {
        "succeeded",
        "partially_refunded",
    }:
        raise HTTPException(
            status_code=409, detail="Only successful transactions can be refunded"
        )
    refunded = int(
        await session.scalar(
            select(func.coalesce(func.sum(BillingRefund.amount_minor), 0)).where(
                BillingRefund.transaction_id == transaction.id,
                BillingRefund.status.in_(("pending", "succeeded")),
            )
        )
        or 0
    )
    if amount_minor <= 0 or refunded + amount_minor > transaction.amount_minor:
        raise HTTPException(
            status_code=422, detail="Refund amount exceeds the refundable balance"
        )
    refund = BillingRefund(
        organization_id=transaction.organization_id,
        transaction_id=transaction.id,
        invoice_id=transaction.invoice_id,
        provider=transaction.provider,
        amount_minor=amount_minor,
        currency=transaction.currency,
        reason=reason.strip()[:240] or "Owner-approved refund",
        idempotency_key=idempotency_key,
    )
    session.add(refund)
    await session.flush()
    provider = transaction.provider
    external_ref: str | None = None
    if provider == "stripe":
        if not settings.STRIPE_SECRET_KEY or not transaction.external_reference:
            raise HTTPException(
                status_code=503, detail="Stripe refund is not configured"
            )
        async with httpx.AsyncClient(
            base_url=settings.STRIPE_API_BASE, timeout=30, transport=transport
        ) as client:
            response = await client.post(
                "/v1/refunds",
                headers={
                    "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
                    "Idempotency-Key": idempotency_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=urlencode(
                    {
                        "payment_intent": transaction.external_reference,
                        "amount": amount_minor,
                        "reason": "requested_by_customer",
                    }
                ),
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Stripe refund failed")
        external_ref = str(response.json()["id"])
    elif provider == "paypal":
        if not transaction.external_reference:
            raise HTTPException(
                status_code=409, detail="PayPal capture reference is missing"
            )
        oauth_value = await _paypal_token(transport)
        async with httpx.AsyncClient(
            base_url=settings.PAYPAL_API_BASE, timeout=30, transport=transport
        ) as client:
            response = await client.post(
                f"/v2/payments/captures/{transaction.external_reference}/refund",
                headers={
                    "Authorization": f"Bearer {oauth_value}",
                    "PayPal-Request-Id": idempotency_key,
                },
                json={
                    "amount": {
                        "value": f"{Decimal(amount_minor) / Decimal(100):.2f}",
                        "currency_code": transaction.currency,
                    }
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="PayPal refund failed")
        external_ref = str(response.json()["id"])
    elif provider == "paddle":
        if not settings.PADDLE_API_KEY or not transaction.external_reference:
            raise HTTPException(
                status_code=503, detail="Paddle refund is not configured"
            )
        async with httpx.AsyncClient(
            base_url=settings.PADDLE_API_BASE, timeout=30, transport=transport
        ) as client:
            response = await client.post(
                "/adjustments",
                headers={
                    "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
                    "Idempotency-Key": idempotency_key,
                },
                json={
                    "action": "refund",
                    "transaction_id": transaction.external_reference,
                    "items": [],
                    "reason": refund.reason,
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Paddle refund failed")
        external_ref = str(response.json()["data"]["id"])
    elif provider in {"manual", "bank_transfer", "internal"}:
        external_ref = f"manual-{secrets.token_hex(8)}"
    else:
        raise HTTPException(
            status_code=409, detail="Refund adapter is not available for this provider"
        )
    refund.external_reference = external_ref
    refund.status = "succeeded"
    refund.completed_at = now()
    total_refunded = refunded + amount_minor
    transaction.status = (
        "refunded"
        if total_refunded == transaction.amount_minor
        else "partially_refunded"
    )
    if transaction.invoice_id:
        invoice = await session.get(BillingInvoice, transaction.invoice_id)
        if invoice is not None:
            invoice.amount_refunded_minor += amount_minor
            if invoice.amount_refunded_minor >= invoice.amount_paid_minor:
                invoice.status = "refunded"
    await post_wallet_entry(
        session,
        transaction.organization_id,
        amount_minor=amount_minor,
        idempotency_key=f"refund-credit:{idempotency_key}",
        entry_type="credit",
        description="Refund credit",
        reference_type="billing_refund",
        reference_id=refund.id,
    )
    session.add(
        _audit(
            actor,
            "billing.refund.completed",
            "billing_refund",
            refund.id,
            {
                "organization_id": transaction.organization_id,
                "amount_minor": amount_minor,
                "currency": transaction.currency,
                "provider": provider,
            },
        )
    )
    await _notify_owner_and_org(
        session,
        transaction.organization_id,
        title="Refund completed",
        message="An owner-approved refund was completed and recorded in the billing ledger.",
        event_type="billing.refund.completed",
    )
    await session.commit()
    return {
        "id": refund.id,
        "status": refund.status,
        "amount_minor": refund.amount_minor,
        "currency": refund.currency,
    }


async def reconcile(
    session: AsyncSession,
    actor: UserRecord,
    provider: str,
) -> dict[str, Any]:
    provider_info = _provider(provider)
    run = BillingReconciliationRun(
        provider=provider_info["id"],
        requested_by_id=actor.id,
        status="running",
    )
    session.add(run)
    await session.flush()

    stale_items = list(
        (
            await session.scalars(
                select(BillingCheckoutSession)
                .where(
                    BillingCheckoutSession.provider == provider_info["id"],
                    BillingCheckoutSession.status.in_(("pending", "created")),
                    (
                        (BillingCheckoutSession.expires_at.is_not(None))
                        & (BillingCheckoutSession.expires_at < now())
                    )
                    | (BillingCheckoutSession.created_at < now() - timedelta(hours=24)),
                )
                .with_for_update()
            )
        ).all()
    )
    released_coupon_reservations = 0
    for checkout in stale_items:
        checkout.status = "expired"
        if await _release_coupon_reservation(session, checkout.id):
            released_coupon_reservations += 1
        transaction = await session.scalar(
            select(BillingTransaction).where(
                BillingTransaction.transaction_metadata["checkout_id"].as_string()
                == checkout.id
            )
        )
        if transaction is not None and transaction.status == "pending":
            transaction.status = "failed"
            if transaction.invoice_id:
                invoice = await session.get(BillingInvoice, transaction.invoice_id)
                if invoice is not None and invoice.status == "open":
                    invoice.status = "void"

    failed_webhooks = int(
        await session.scalar(
            select(func.count(BillingWebhookEvent.id)).where(
                BillingWebhookEvent.provider == provider_info["id"],
                BillingWebhookEvent.status == "failed",
            )
        )
        or 0
    )
    mismatched_accounts = 0
    rows = (
        await session.execute(
            select(BillingAccount, Organization, BillingPlan)
            .join(Organization, Organization.id == BillingAccount.organization_id)
            .outerjoin(BillingPlan, BillingPlan.id == BillingAccount.plan_id)
        )
    ).all()
    for account, organization, plan in rows:
        if plan and organization.plan != plan.code:
            mismatched_accounts += 1
            organization.plan = plan.code
        if plan and account.plan_id == plan.id:
            account.limits = dict(plan.limits or {})
            account.entitlements = list(plan.entitlements or [])

    run.status = "completed"
    run.summary = {
        "provider_ready": provider_info["configured"],
        "expired_checkouts": len(stale_items),
        "released_coupon_reservations": released_coupon_reservations,
        "failed_webhooks": failed_webhooks,
        "accounts_reconciled": mismatched_accounts,
    }
    run.completed_at = now()
    session.add(
        _audit(
            actor,
            "billing.reconciliation.completed",
            "billing_reconciliation",
            run.id,
            {"organization_id": actor.organization_id, **run.summary},
        )
    )
    await session.commit()
    return {
        "id": run.id,
        "provider": run.provider,
        "status": run.status,
        "summary": run.summary,
        "completed_at": _as_utc(run.completed_at).isoformat(),
    }


async def create_billing_portal_session(
    session: AsyncSession,
    actor: UserRecord,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, str]:
    account = await ensure_billing_account(session, actor.organization_id)
    customer = str((account.provider_customers or {}).get("stripe") or "")
    if not customer or not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=409,
            detail="Stripe billing portal is not available for this account",
        )
    async with httpx.AsyncClient(
        base_url=settings.STRIPE_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.post(
            "/v1/billing_portal/sessions",
            headers={
                "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=urlencode(
                {
                    "customer": customer,
                    "return_url": settings.PAYMENTS_SUCCESS_URL.split("?", 1)[0],
                }
            ),
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail="Billing portal session creation failed"
        )
    url = str(response.json().get("url") or "")
    if not url.startswith("https://"):
        raise HTTPException(status_code=502, detail="Billing portal URL is invalid")
    return {"url": url}
