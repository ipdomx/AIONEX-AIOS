"""Stripe subscription lifecycle: checkout links, webhooks, plan changes, entitlements.

P5.3 (owner decision 2026-11-06: no live money until the pre-launch window).

Rules this module enforces:

* Stripe objects are the source of truth. Subscription status, plan (price),
  period bounds, trial end and cancellation flags are copied from the Stripe
  object carried by the verified event, never inferred from arrival order.
* Out-of-order safety: each local Stripe subscription remembers the ``created``
  time of the last event applied to it. Older events are recorded as
  ``stale`` and change nothing; a ``canceled`` subscription is terminal.
* Entitlements are recomputed from every subscription the organization holds
  (any provider) after each change. The account always carries the plan of
  the authoritative entitled subscription, or the free plan when none is
  entitled. The account itself stays usable, so free features keep working,
  past reports stay readable, and every paid check (Security Lab top plan,
  Ads, 3D, the AIONEX AI plan signal) fails closed at once.
* Every Stripe write carries an ``Idempotency-Key``.
* Receipts and billing notices go through ``communications.create_notification``
  so the communication worker delivers the email copies.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    BillingAccount,
    BillingCheckoutSession,
    BillingInvoice,
    BillingPlan,
    BillingPrice,
    BillingRefund,
    BillingSubscription,
    BillingTransaction,
    Organization,
    User,
)
from app.services import billing as core

logger = get_logger(__name__)

PROVIDER = "stripe"
PORTAL_LOCALES = ("ar", "en", "de", "es", "fr", "tr")
DEFAULT_PORTAL_LOCALE = "en"
# Statuses that grant the subscribed plan (``grace_period`` is the mobile-store
# equivalent and is honoured so the two reconcilers agree).
ENTITLED_STATUSES = ("active", "trialing", "grace_period")
# Stripe subscriptions that still exist on Stripe's side and block a second
# checkout for the same organization.
LIVE_STRIPE_STATUSES = ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")
CHANGEABLE_STATUSES = ("active", "trialing")
FREE_PLAN_CODE = "free"
FREE_BASE_ENTITLEMENTS = ("account.profile", "projects.core", "support.requests")
PROTECTED_ORGANIZATIONS = frozenset({"aionex-org"})
HANDLED_EVENTS = (
    "checkout.session.completed",
    "checkout.session.expired",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "customer.subscription.trial_will_end",
    "invoice.paid",
    "invoice.payment_failed",
    "charge.refunded",
)
SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
)
# Same-second tie-break: a later lifecycle stage wins over an earlier one.
STATUS_RANK = {
    "incomplete": 0,
    "incomplete_expired": 1,
    "trialing": 2,
    "active": 3,
    "past_due": 3,
    "paused": 3,
    "unpaid": 4,
    "canceled": 5,
}


# --------------------------------------------------------------------------- utils


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _ref(value: Any) -> str | None:
    """A Stripe reference that may be an id string or an expanded object."""

    if isinstance(value, Mapping):
        value = value.get("id")
    text = str(value or "").strip()
    return text[:255] or None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ts(value: Any) -> datetime | None:
    number = _int(value, 0)
    if number <= 0:
        return None
    return datetime.fromtimestamp(number, UTC)


def _iso_ts(value: Any) -> str | None:
    moment = _ts(value)
    return moment.isoformat() if moment is not None else None


def _first_item(obj: Mapping[str, Any]) -> dict[str, Any]:
    items = _mapping(obj.get("items")).get("data") or []
    return _mapping(items[0]) if isinstance(items, list) and items else {}


def subscription_period(obj: Mapping[str, Any]) -> tuple[datetime | None, datetime | None]:
    """Period bounds from the subscription, or from its first item (API 2025-03-31+)."""

    item = _first_item(obj)
    start = obj.get("current_period_start") or item.get("current_period_start")
    end = obj.get("current_period_end") or item.get("current_period_end")
    return _ts(start), _ts(end)


def subscription_price_ref(obj: Mapping[str, Any]) -> str | None:
    item = _first_item(obj)
    return _ref(item.get("price")) or _ref(_mapping(obj.get("plan")).get("id"))


def invoice_subscription_ref(obj: Mapping[str, Any]) -> str | None:
    direct = _ref(obj.get("subscription"))
    if direct:
        return direct
    details = _mapping(_mapping(obj.get("parent")).get("subscription_details"))
    return _ref(details.get("subscription"))


def invoice_metadata(obj: Mapping[str, Any]) -> dict[str, Any]:
    details = _mapping(_mapping(obj.get("parent")).get("subscription_details"))
    legacy = _mapping(obj.get("subscription_details"))
    return {
        **_mapping(legacy.get("metadata")),
        **_mapping(details.get("metadata")),
        **_mapping(obj.get("metadata")),
    }


def invoice_payment_refs(obj: Mapping[str, Any]) -> tuple[str | None, str | None]:
    payment_intent = _ref(obj.get("payment_intent"))
    charge = _ref(obj.get("charge"))
    payments = _mapping(obj.get("payments")).get("data") or []
    if isinstance(payments, list):
        for row in payments:
            payment = _mapping(_mapping(row).get("payment"))
            payment_intent = payment_intent or _ref(payment.get("payment_intent"))
            charge = charge or _ref(payment.get("charge"))
    return payment_intent, charge


def _amount_sum(rows: Any) -> int:
    if not isinstance(rows, list):
        return 0
    return sum(_int(_mapping(row).get("amount")) for row in rows)


def invoice_tax(obj: Mapping[str, Any]) -> int:
    if obj.get("tax") is not None:
        return _int(obj.get("tax"))
    return _amount_sum(obj.get("total_taxes")) or _amount_sum(obj.get("total_tax_amounts"))


def invoice_lines(obj: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _mapping(obj.get("lines")).get("data") or []
    lines: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return lines
    for raw in rows[:50]:
        row = _mapping(raw)
        period = _mapping(row.get("period"))
        pricing = _mapping(_mapping(row.get("pricing")).get("price_details"))
        lines.append(
            {
                "description": str(row.get("description") or "")[:240],
                "amount_minor": _int(row.get("amount")),
                "quantity": _int(row.get("quantity"), 1),
                "price": _ref(row.get("price")) or _ref(pricing.get("price")),
                "proration": bool(row.get("proration")),
                "period_start": _iso_ts(period.get("start")),
                "period_end": _iso_ts(period.get("end")),
            }
        )
    return lines


def portal_locale(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized if normalized in PORTAL_LOCALES else DEFAULT_PORTAL_LOCALE


def portal_billing_url(locale: str | None, query: Sequence[tuple[str, str]] = ()) -> str:
    """``https://ai.vip-e.net/<locale>/billing?...``; placeholders are kept verbatim."""

    base = str(settings.PAYMENTS_PORTAL_BASE_URL or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise HTTPException(status_code=503, detail="Portal return URL is not configured")
    url = f"{base}/{portal_locale(locale)}/billing"
    if query:
        url += "?" + "&".join(f"{key}={value}" for key, value in query)
    return url


def checkout_return_urls(locale: str | None) -> tuple[str, str]:
    success = portal_billing_url(
        locale, (("checkout", "success"), ("session_id", "{CHECKOUT_SESSION_ID}"))
    )
    cancel = portal_billing_url(locale, (("checkout", "cancelled"),))
    return success, cancel


def stripe_tax_rate_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in str(settings.STRIPE_TAX_RATES or "").split(","):
        if "=" not in part:
            continue
        code, reference = part.split("=", 1)
        if code.strip() and reference.strip().startswith("txr_"):
            mapping[code.strip().upper()] = reference.strip()
    return mapping


def coupon_stripe_discount(coupon_metadata: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """The Stripe discount a local coupon maps to: a promotion code or a coupon."""

    metadata = _mapping(coupon_metadata)
    promotion = str(metadata.get("stripe_promotion_code") or "").strip()
    if promotion.startswith("promo_"):
        return "promotion_code", promotion
    coupon = str(metadata.get("stripe_coupon") or "").strip()
    if coupon:
        return "coupon", coupon[:255]
    return None


def monthly_equivalent(price: BillingPrice | None) -> float:
    if price is None or price.amount_minor is None or price.amount_minor <= 0:
        return 0.0
    return float(price.amount_minor) / float(max(int(price.months or 1), 1))


def new_idempotency_key(operation: str, reference: str) -> str:
    return f"aionex-{operation}-{reference}-{secrets.token_hex(8)}"[:160]


def _idempotency(value: str | None, operation: str, reference: str) -> str:
    key = (value or "").strip()
    if key:
        if len(key) < 12 or len(key) > 160:
            raise HTTPException(
                status_code=422, detail="Idempotency-Key must be 12 to 160 characters"
            )
        return key
    return new_idempotency_key(operation, reference)


async def stripe_request(
    method: str,
    path: str,
    *,
    data: Sequence[tuple[str, str]] | None = None,
    idempotency_key: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    failure: str = "Stripe request failed",
) -> dict[str, Any]:
    """One Stripe API call. Every non-GET call must carry an idempotency key."""

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
    if method.upper() != "GET":
        if not idempotency_key:
            raise ValueError("Stripe writes require an idempotency key")
        headers["Idempotency-Key"] = idempotency_key
    content: str | None = None
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        content = urlencode(list(data))
    async with httpx.AsyncClient(
        base_url=settings.STRIPE_API_BASE, timeout=30, transport=transport
    ) as client:
        response = await client.request(method.upper(), path, headers=headers, content=content)
    if response.status_code >= 400:
        error = _mapping(_safe_json(response).get("error"))
        raise HTTPException(
            status_code=502,
            detail={
                "code": "STRIPE_REQUEST_FAILED",
                "message": failure,
                "stripe_code": str(error.get("code") or error.get("type") or "")[:80] or None,
            },
        )
    return _safe_json(response)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


# ------------------------------------------------------------------ entitlements


async def free_plan(session: AsyncSession) -> BillingPlan:
    plan = await session.scalar(select(BillingPlan).where(BillingPlan.code == FREE_PLAN_CODE))
    if plan is not None:
        if "*" in list(plan.entitlements or []):
            # An internal placeholder must never grant the wildcard to the
            # free tier; keep only explicit entitlements.
            plan.entitlements = sorted(
                {item for item in plan.entitlements if item != "*"}
                | set(FREE_BASE_ENTITLEMENTS)
            )
        return plan
    # Never fall back to the internal ``*`` wildcard plan on subscription loss.
    plan = BillingPlan(
        code=FREE_PLAN_CODE,
        name="Free",
        description="Free tier applied when no paid subscription is active.",
        status="internal",
        default_currency=core._currency(None),
        limits={},
        entitlements=list(FREE_BASE_ENTITLEMENTS),
        metering={},
        source_version=0,
        source_hash=core._catalog_hash({"internal": FREE_PLAN_CODE}),
    )
    session.add(plan)
    await session.flush()
    return plan


def _rank(item: BillingSubscription) -> tuple[datetime, str, str]:
    end = core._as_utc(item.current_period_end) or datetime.max.replace(tzinfo=UTC)
    return end, item.provider, item.id


def _period_open(item: BillingSubscription, moment: datetime) -> bool:
    end = core._as_utc(item.current_period_end)
    return end is None or end > moment


async def _lock_account(session: AsyncSession, organization_id: str) -> BillingAccount:
    account = await session.scalar(
        select(BillingAccount)
        .where(BillingAccount.organization_id == organization_id)
        .with_for_update()
    )
    if account is None:
        account = await core.ensure_billing_account(session, organization_id, lock=True)
    return account


async def reconcile_account_entitlements(
    session: AsyncSession, organization_id: str
) -> dict[str, Any]:
    """Point the account at the plan of its authoritative entitled subscription.

    Owner suspension (``status == "suspended"``) is preserved; only the plan,
    limits and entitlements follow the subscriptions.
    """

    account = await _lock_account(session, organization_id)
    moment = core.now()
    rows = list(
        (
            await session.scalars(
                select(BillingSubscription).where(
                    BillingSubscription.organization_id == organization_id,
                    BillingSubscription.status.in_(ENTITLED_STATUSES),
                )
            )
        ).all()
    )
    live = [item for item in rows if _period_open(item, moment)]
    organization = await session.get(Organization, organization_id)
    previous_plan_id = account.plan_id
    if live:
        authoritative = max(live, key=_rank)
        plan = await session.get(BillingPlan, authoritative.plan_id)
        if plan is None:
            raise ValueError("authoritative subscription plan is missing")
        account.current_period_end = authoritative.current_period_end
        source = authoritative.provider
    elif organization_id in PROTECTED_ORGANIZATIONS:
        return {"organization_id": organization_id, "plan": None, "changed": False}
    else:
        plan = await free_plan(session)
        account.current_period_end = None
        source = "free"
    account.plan_id = plan.id
    account.limits = dict(plan.limits or {})
    account.entitlements = list(plan.entitlements or [])
    if account.status != "suspended":
        account.status = "active"
        account.suspended_at = None
    if organization is not None:
        organization.plan = plan.code
    await session.flush()
    return {
        "organization_id": organization_id,
        "plan": plan.code,
        "source": source,
        "changed": previous_plan_id != plan.id,
    }


# ------------------------------------------------------------------ notifications


async def notify_billing_event(
    session: AsyncSession,
    organization_id: str,
    *,
    event_key: str,
    title: str,
    message: str,
    dedupe: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> int:
    """Queue in-app and email notices for the organization and the owner.

    Delivery is durable: ``NotificationDelivery`` rows are picked up by the
    communication worker. A notification failure never fails the payment
    event; it is logged and audited instead.
    """

    from app.services import communications

    recipients = (
        await session.scalars(
            select(User).where(
                User.deleted_at.is_(None),
                User.status.in_(("active", "online")),
                (User.organization_id == organization_id) | (User.id == "owner-1"),
            )
        )
    ).all()
    created = 0
    for recipient in sorted(recipients, key=lambda item: item.id):
        channels = ["in_app", "email"] if recipient.organization_id == organization_id else ["in_app"]
        try:
            async with session.begin_nested():
                await communications.create_notification(
                    session,
                    recipient,
                    event_key=event_key,
                    category="billing",
                    title=title,
                    message=message,
                    severity=severity,
                    channels=channels,
                    source_type="billing",
                    source_id=organization_id,
                    dedupe_key=f"{dedupe}:{recipient.id}"[:200],
                    payload=dict(payload or {}),
                )
            created += 1
        except Exception as exc:  # noqa: BLE001 - notices must not fail payments
            logger.warning(
                "Billing notification could not be queued",
                event_key=event_key,
                error_type=type(exc).__name__,
            )
            session.add(
                core._audit(
                    None,
                    "billing.notification.failed",
                    "notification",
                    None,
                    {
                        "organization_id": organization_id,
                        "event_key": event_key,
                        "error_type": type(exc).__name__,
                    },
                )
            )
    return created


def _money(amount_minor: int, currency: str) -> str:
    return f"{amount_minor / 100:.2f} {currency.upper()}"


# ------------------------------------------------------------------ lookups


async def _subscription_by_ref(session: AsyncSession, reference: str | None) -> BillingSubscription | None:
    if not reference:
        return None
    return await session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.provider == PROVIDER,
            BillingSubscription.external_reference == reference,
        )
        .with_for_update()
    )


async def _organization_for(
    session: AsyncSession,
    *,
    metadata: Mapping[str, Any],
    customer: str | None,
    subscription_ref: str | None = None,
) -> str | None:
    subscription = await _subscription_by_ref(session, subscription_ref)
    if subscription is not None:
        return subscription.organization_id
    claimed = str(metadata.get("organization_id") or "").strip()
    if claimed and await session.get(Organization, claimed) is not None:
        return claimed
    checkout_id = str(metadata.get("checkout_id") or "").strip()
    if checkout_id:
        checkout = await session.get(BillingCheckoutSession, checkout_id)
        if checkout is not None:
            return checkout.organization_id
    if customer:
        account = await session.scalar(
            select(BillingAccount).where(
                BillingAccount.provider_customers["stripe"].as_string() == customer
            )
        )
        if account is not None:
            return account.organization_id
    return None


async def _price_for_ref(session: AsyncSession, reference: str | None) -> BillingPrice | None:
    if not reference:
        return None
    return await session.scalar(
        select(BillingPrice)
        .where(
            BillingPrice.provider == PROVIDER,
            BillingPrice.provider_reference == reference,
        )
        .order_by(BillingPrice.enabled.desc(), BillingPrice.created_at.desc())
        .limit(1)
    )


async def _remember_customer(session: AsyncSession, organization_id: str, customer: str | None) -> None:
    if not customer:
        return
    account = await _lock_account(session, organization_id)
    current = dict(account.provider_customers or {})
    if current.get("stripe") != customer:
        account.provider_customers = {**current, "stripe": customer}


def _is_newer(local: BillingSubscription, event_created: int, obj: Mapping[str, Any]) -> bool:
    metadata = dict(local.subscription_metadata or {})
    incoming = str(obj.get("status") or "")
    if local.status == "canceled" and incoming != "canceled" and not metadata.get("provisional"):
        return False
    last = _int(metadata.get("stripe_event_created"))
    if event_created > last:
        return True
    if event_created < last:
        return False
    incoming_end = subscription_period(obj)[1]
    current_end = core._as_utc(local.current_period_end)
    if incoming_end and current_end and incoming_end != current_end:
        return incoming_end > current_end
    return STATUS_RANK.get(incoming, 0) >= STATUS_RANK.get(local.status, 0)


# ------------------------------------------------------------------ event handlers


async def apply_subscription_object(
    session: AsyncSession,
    obj: Mapping[str, Any],
    *,
    event_id: str,
    event_type: str,
    event_created: int,
) -> dict[str, Any]:
    reference = _ref(obj.get("id"))
    if not reference:
        raise ValueError("Stripe subscription id is missing")
    metadata = _mapping(obj.get("metadata"))
    customer = _ref(obj.get("customer"))
    local = await _subscription_by_ref(session, reference)
    organization_id = (
        local.organization_id
        if local is not None
        else await _organization_for(session, metadata=metadata, customer=customer)
    )
    if not organization_id:
        raise ValueError("Stripe subscription is not mapped to an organization")
    if local is not None and not _is_newer(local, event_created, obj):
        return {"status": "stale", "organization_id": organization_id}

    price_ref = subscription_price_ref(obj)
    price = await _price_for_ref(session, price_ref)
    plan_id = price.plan_id if price is not None else (local.plan_id if local else None)
    if plan_id is None and metadata.get("plan_code"):
        plan = await session.scalar(
            select(BillingPlan).where(BillingPlan.code == str(metadata["plan_code"]))
        )
        plan_id = plan.id if plan is not None else None
    if plan_id is None:
        raise ValueError("Stripe price is not mapped to a billing plan")

    status = str(obj.get("status") or "incomplete")[:32]
    previous = {
        "status": local.status if local else None,
        "plan_id": local.plan_id if local else None,
        "cancel_at_period_end": bool(local.cancel_at_period_end) if local else False,
    }
    if local is None:
        local = BillingSubscription(
            organization_id=organization_id,
            plan_id=plan_id,
            price_id=price.id if price else None,
            provider=PROVIDER,
            external_reference=reference,
            status=status,
            subscription_metadata={},
        )
        session.add(local)
    start, end = subscription_period(obj)
    local.plan_id = plan_id
    if price is not None:
        local.price_id = price.id
    local.status = status
    local.cancel_at_period_end = status != "canceled" and bool(
        obj.get("cancel_at_period_end") or obj.get("cancel_at")
    )
    if start is not None:
        local.current_period_start = start
    if end is not None:
        local.current_period_end = end
    local.trial_end = _ts(obj.get("trial_end"))
    if status == "canceled":
        local.canceled_at = _ts(obj.get("ended_at")) or _ts(obj.get("canceled_at")) or core.now()
    else:
        local.canceled_at = None
    stored = dict(local.subscription_metadata or {})
    stored.update(
        {
            "stripe_event_created": max(event_created, _int(stored.get("stripe_event_created"))),
            "stripe_status": status,
            "stripe_customer": customer,
            "stripe_price": price_ref,
            "stripe_item": _ref(_first_item(obj).get("id")) or stored.get("stripe_item"),
            "last_event_type": event_type,
            "provisional": False,
        }
    )
    if metadata.get("checkout_id"):
        stored["checkout_id"] = str(metadata["checkout_id"])[:36]
    if status in ENTITLED_STATUSES and stored.get("pending_change"):
        pending = _mapping(stored.get("pending_change"))
        if pending.get("price_id") == local.price_id:
            stored.pop("pending_change", None)
    local.subscription_metadata = stored
    await session.flush()
    await _remember_customer(session, organization_id, customer)
    entitlement = await reconcile_account_entitlements(session, organization_id)

    await _notify_subscription_transition(
        session,
        local,
        previous=previous,
        event_id=event_id,
        event_type=event_type,
    )
    return {
        "status": "processed",
        "organization_id": organization_id,
        "subscription_status": status,
        "plan": entitlement.get("plan"),
    }


async def _notify_subscription_transition(
    session: AsyncSession,
    local: BillingSubscription,
    *,
    previous: Mapping[str, Any],
    event_id: str,
    event_type: str,
) -> None:
    status = local.status
    before = previous.get("status")
    plan = await session.get(BillingPlan, local.plan_id)
    plan_name = plan.name if plan is not None else "your plan"
    notice: tuple[str, str, str, str] | None = None
    if status == "past_due" and before != "past_due":
        notice = (
            "billing.subscription.past_due",
            "Payment overdue",
            "Your last payment failed. Paid features are paused until the invoice is paid; "
            "free features and past reports stay available.",
            "warning",
        )
    elif status in {"canceled", "unpaid", "incomplete_expired"} and before not in {
        "canceled",
        "unpaid",
        "incomplete_expired",
    }:
        notice = (
            "billing.subscription.ended",
            "Subscription ended",
            f"The {plan_name} subscription has ended. Paid features are no longer available; "
            "past reports stay readable.",
            "warning",
        )
    elif status in {"active", "trialing"} and before == "past_due":
        notice = (
            "billing.subscription.recovered",
            "Payment received, access restored",
            f"The {plan_name} subscription is active again.",
            "success",
        )
    elif previous.get("plan_id") and previous.get("plan_id") != local.plan_id:
        notice = (
            "billing.subscription.plan_changed",
            "Plan changed",
            f"The subscription now uses the {plan_name} plan.",
            "info",
        )
    elif local.cancel_at_period_end and not previous.get("cancel_at_period_end"):
        notice = (
            "billing.subscription.cancel_scheduled",
            "Cancellation scheduled",
            "The subscription stays active until the end of the current billing period.",
            "warning",
        )
    elif not local.cancel_at_period_end and previous.get("cancel_at_period_end") and status in {
        "active",
        "trialing",
    }:
        notice = (
            "billing.subscription.resumed",
            "Subscription resumed",
            "The scheduled cancellation was removed; the subscription will renew.",
            "success",
        )
    if notice is None:
        return
    event_key, title, message, severity = notice
    await notify_billing_event(
        session,
        local.organization_id,
        event_key=event_key,
        title=title,
        message=message,
        severity=severity,
        dedupe=f"stripe:{event_id}:{event_key}",
        payload={"subscription_id": local.id, "status": status},
    )


async def handle_checkout_completed(
    session: AsyncSession, obj: Mapping[str, Any], *, event_id: str
) -> dict[str, Any]:
    metadata = _mapping(obj.get("metadata"))
    checkout_id = str(metadata.get("checkout_id") or obj.get("client_reference_id") or "")
    checkout = (
        await session.get(BillingCheckoutSession, checkout_id) if checkout_id else None
    )
    if checkout is None or checkout.provider != PROVIDER:
        return {"status": "ignored", "reason": "checkout-not-found"}
    organization_id = checkout.organization_id
    payment_status = obj.get("payment_status")
    paid = payment_status in (None, "paid", "no_payment_required")
    checkout.status = "completed" if paid else "awaiting_payment"
    checkout.completed_at = checkout.completed_at or core.now()
    account = await _lock_account(session, organization_id)
    await core._sync_verified_payment_method(session, account, PROVIDER, obj)
    stripe_invoice = _ref(obj.get("invoice"))

    subscription_ref = _ref(obj.get("subscription"))
    subscription = await _subscription_by_ref(session, subscription_ref)
    if subscription_ref and subscription is None:
        price = await session.get(BillingPrice, checkout.price_id)
        subscription = BillingSubscription(
            organization_id=organization_id,
            plan_id=checkout.plan_id,
            price_id=checkout.price_id,
            provider=PROVIDER,
            external_reference=subscription_ref,
            status="active" if paid else "incomplete",
            current_period_start=core.now(),
            current_period_end=core.now()
            + timedelta(days=30 * max(1, price.months if price else 1)),
            # Provisional until the first customer.subscription.* event lands.
            subscription_metadata={
                "checkout_id": checkout.id,
                "provisional": True,
                "stripe_event_created": 0,
                "stripe_customer": _ref(obj.get("customer")),
            },
        )
        session.add(subscription)
        await session.flush()
    elif subscription is not None:
        subscription.subscription_metadata = {
            **dict(subscription.subscription_metadata or {}),
            "checkout_id": checkout.id,
        }

    transaction = await session.scalar(
        select(BillingTransaction)
        .where(
            BillingTransaction.transaction_metadata["checkout_id"].as_string() == checkout.id
        )
        .order_by(BillingTransaction.created_at.desc())
        .limit(1)
    )
    if transaction is not None and paid:
        if transaction.status in {"pending", "failed"}:
            transaction.status = "succeeded"
            transaction.completed_at = core.now()
        transaction.external_reference = (
            transaction.external_reference
            or _ref(obj.get("payment_intent"))
            or _ref(obj.get("id"))
        )
        transaction.transaction_metadata = {
            **dict(transaction.transaction_metadata or {}),
            "stripe_checkout": _ref(obj.get("id")),
            "stripe_invoice": stripe_invoice,
            "stripe_subscription": subscription_ref,
        }
        invoice = (
            await session.get(BillingInvoice, transaction.invoice_id)
            if transaction.invoice_id
            else None
        )
        if invoice is not None:
            if invoice.status in {"open", "draft", "past_due"}:
                invoice.status = "paid"
                invoice.amount_paid_minor = invoice.total_minor
                invoice.paid_at = core.now()
            if subscription is not None:
                invoice.subscription_id = subscription.id
            if stripe_invoice and not invoice.external_reference:
                clash = await session.scalar(
                    select(BillingInvoice.id).where(
                        BillingInvoice.provider == PROVIDER,
                        BillingInvoice.external_reference == stripe_invoice,
                    )
                )
                if clash is None:
                    invoice.external_reference = stripe_invoice
    await session.flush()
    await reconcile_account_entitlements(session, organization_id)
    plan = await session.get(BillingPlan, checkout.plan_id)
    if paid:
        await notify_billing_event(
            session,
            organization_id,
            event_key="billing.subscription.activated",
            title="Subscription activated",
            message=(
                f"The {plan.name if plan else 'new'} subscription was activated from a "
                "verified Stripe payment."
            ),
            severity="success",
            dedupe=f"stripe:{event_id}:activated",
            payload={"checkout_id": checkout.id},
        )
    return {"status": "processed", "organization_id": organization_id}


async def handle_checkout_expired(
    session: AsyncSession, obj: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = _mapping(obj.get("metadata"))
    checkout_id = str(metadata.get("checkout_id") or obj.get("client_reference_id") or "")
    checkout = (
        await session.get(BillingCheckoutSession, checkout_id) if checkout_id else None
    )
    if checkout is None or checkout.status == "completed":
        return {"status": "ignored", "reason": "checkout-not-open"}
    checkout.status = "expired"
    await core._release_coupon_reservation(session, checkout.id)
    transaction = await session.scalar(
        select(BillingTransaction).where(
            BillingTransaction.transaction_metadata["checkout_id"].as_string() == checkout.id
        )
    )
    if transaction is not None and transaction.status == "pending":
        transaction.status = "failed"
        transaction.transaction_metadata = {
            **dict(transaction.transaction_metadata or {}),
            "failure": "checkout_expired",
        }
        invoice = (
            await session.get(BillingInvoice, transaction.invoice_id)
            if transaction.invoice_id
            else None
        )
        if invoice is not None and invoice.status == "open":
            invoice.status = "void"
    return {"status": "processed", "organization_id": checkout.organization_id}


async def _checkout_records_for_invoice(
    session: AsyncSession,
    obj: Mapping[str, Any],
    subscription: BillingSubscription | None,
) -> tuple[BillingTransaction | None, BillingInvoice | None]:
    """The local checkout transaction/invoice the first Stripe invoice should adopt."""

    if str(obj.get("billing_reason") or "") not in {"subscription_create", ""}:
        return None, None
    checkout_id = str(
        (dict(subscription.subscription_metadata or {}) if subscription else {}).get(
            "checkout_id"
        )
        or invoice_metadata(obj).get("checkout_id")
        or ""
    )
    if not checkout_id:
        return None, None
    transaction = await session.scalar(
        select(BillingTransaction)
        .where(BillingTransaction.transaction_metadata["checkout_id"].as_string() == checkout_id)
        .order_by(BillingTransaction.created_at.desc())
        .limit(1)
    )
    if transaction is None:
        return None, None
    invoice = (
        await session.get(BillingInvoice, transaction.invoice_id)
        if transaction.invoice_id
        else None
    )
    if invoice is not None and invoice.external_reference not in (None, _ref(obj.get("id"))):
        invoice = None
    return transaction, invoice


async def _transaction_reference_free(
    session: AsyncSession, reference: str | None, own_id: str | None
) -> bool:
    if not reference:
        return False
    holder = await session.scalar(
        select(BillingTransaction.id).where(
            BillingTransaction.provider == PROVIDER,
            BillingTransaction.external_reference == reference,
        )
    )
    return holder is None or holder == own_id


async def handle_invoice(
    session: AsyncSession, obj: Mapping[str, Any], *, event_id: str, paid: bool
) -> dict[str, Any]:
    reference = _ref(obj.get("id"))
    if not reference:
        raise ValueError("Stripe invoice id is missing")
    subscription_ref = invoice_subscription_ref(obj)
    subscription = await _subscription_by_ref(session, subscription_ref)
    organization_id = (
        subscription.organization_id
        if subscription is not None
        else await _organization_for(
            session,
            metadata=invoice_metadata(obj),
            customer=_ref(obj.get("customer")),
        )
    )
    if not organization_id:
        if subscription_ref:
            # The subscription event may still be in flight: let Stripe retry.
            raise ValueError("Stripe invoice is not mapped to an organization yet")
        return {"status": "ignored", "reason": "invoice-not-mapped"}

    currency = str(obj.get("currency") or settings.PAYMENTS_DEFAULT_CURRENCY).upper()[:3]
    invoice = await session.scalar(
        select(BillingInvoice).where(
            BillingInvoice.provider == PROVIDER,
            BillingInvoice.external_reference == reference,
        )
    )
    transaction: BillingTransaction | None = None
    if invoice is None:
        transaction, invoice = await _checkout_records_for_invoice(session, obj, subscription)
    if invoice is None:
        number = f"STRIPE-{obj.get('number') or reference}"[:80]
        clash = await session.scalar(select(BillingInvoice.id).where(BillingInvoice.number == number))
        invoice = BillingInvoice(
            organization_id=organization_id,
            provider=PROVIDER,
            number=number if clash is None else f"STRIPE-{reference}"[:80],
            status="open",
            currency=currency,
            line_items=[],
            invoice_metadata={},
        )
        session.add(invoice)
    subtotal = _int(obj.get("subtotal"))
    total = _int(obj.get("total"))
    tax = invoice_tax(obj)
    invoice.external_reference = reference
    invoice.organization_id = organization_id
    invoice.subscription_id = subscription.id if subscription is not None else invoice.subscription_id
    invoice.currency = currency
    invoice.subtotal_minor = subtotal
    invoice.tax_minor = tax
    invoice.total_minor = total
    invoice.discount_minor = _amount_sum(obj.get("total_discount_amounts")) or max(
        0, subtotal + tax - total
    )
    lines = invoice_lines(obj)
    if lines:
        invoice.line_items = lines
    invoice.due_at = _ts(obj.get("due_date")) or invoice.due_at
    invoice.invoice_metadata = {
        **dict(invoice.invoice_metadata or {}),
        "stripe_number": str(obj.get("number") or "")[:80] or None,
        "billing_reason": str(obj.get("billing_reason") or "")[:80] or None,
        "hosted_invoice_url": str(obj.get("hosted_invoice_url") or "")[:1000] or None,
        "invoice_pdf": str(obj.get("invoice_pdf") or "")[:1000] or None,
        "attempt_count": _int(obj.get("attempt_count")),
        "stripe_subscription": subscription_ref,
    }
    payment_intent, charge = invoice_payment_refs(obj)
    amount_paid = _int(obj.get("amount_paid"))
    if paid:
        invoice.status = "paid" if invoice.status not in {"refunded"} else invoice.status
        invoice.amount_paid_minor = amount_paid
        invoice.paid_at = (
            _ts(_mapping(obj.get("status_transitions")).get("paid_at"))
            or invoice.paid_at
            or core.now()
        )
    elif invoice.status not in {"paid", "refunded", "void"}:
        invoice.status = "past_due"
    await session.flush()

    idempotency_key = (
        f"stripe-invoice:{reference}"
        if paid
        else f"stripe-invoice-failed:{reference}:{_int(obj.get('attempt_count'))}"
    )[:160]
    if transaction is None:
        transaction = await session.scalar(
            select(BillingTransaction).where(BillingTransaction.idempotency_key == idempotency_key)
        )
    if transaction is None and paid:
        transaction = await session.scalar(
            select(BillingTransaction).where(
                BillingTransaction.provider == PROVIDER,
                BillingTransaction.transaction_metadata["stripe_invoice"].as_string() == reference,
                BillingTransaction.idempotency_key.notlike("stripe-invoice-failed:%"),
            )
            .limit(1)
        )
    amount = amount_paid if paid else _int(obj.get("amount_due"))
    if transaction is None and amount > 0:
        transaction = BillingTransaction(
            organization_id=organization_id,
            invoice_id=invoice.id,
            provider=PROVIDER,
            transaction_type="payment",
            status="succeeded" if paid else "failed",
            amount_minor=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            transaction_metadata={},
            completed_at=core.now(),
        )
        session.add(transaction)
    if transaction is not None:
        transaction.invoice_id = invoice.id
        if paid and transaction.status in {"pending", "failed"}:
            transaction.status = "succeeded"
            transaction.completed_at = core.now()
            transaction.amount_minor = amount_paid or transaction.amount_minor
        candidate = payment_intent or charge
        if (
            paid
            and candidate
            and (not transaction.external_reference or transaction.external_reference.startswith("cs_"))
            and await _transaction_reference_free(session, candidate, transaction.id)
        ):
            transaction.external_reference = candidate
        transaction.transaction_metadata = {
            **dict(transaction.transaction_metadata or {}),
            "stripe_invoice": reference,
            "stripe_payment_intent": payment_intent,
            "stripe_charge": charge,
            "stripe_subscription": subscription_ref,
            "attempt_count": _int(obj.get("attempt_count")),
        }
    await session.flush()

    links = {
        "invoice_id": invoice.id,
        "number": invoice.number,
        "amount_minor": amount,
        "currency": currency,
        "hosted_invoice_url": invoice.invoice_metadata.get("hosted_invoice_url"),
        "invoice_pdf": invoice.invoice_metadata.get("invoice_pdf"),
    }
    if paid and amount_paid > 0:
        url = links["hosted_invoice_url"]
        await notify_billing_event(
            session,
            organization_id,
            event_key="billing.payment.receipt",
            title="Payment receipt",
            message=(
                f"We received {_money(amount_paid, currency)} for invoice {invoice.number}."
                + (f" Receipt: {url}" if url else "")
            ),
            severity="success",
            dedupe=f"stripe-receipt:{reference}",
            payload=links,
        )
    elif not paid:
        url = links["hosted_invoice_url"]
        await notify_billing_event(
            session,
            organization_id,
            event_key="billing.payment.failed",
            title="Payment failed",
            message=(
                f"A payment of {_money(amount, currency)} failed. Update the payment method "
                "from the billing page to keep paid features."
                + (f" Invoice: {url}" if url else "")
            ),
            severity="warning",
            dedupe=f"stripe-payment-failed:{reference}:{_int(obj.get('attempt_count'))}",
            payload=links,
        )
    return {"status": "processed", "organization_id": organization_id}


async def handle_charge_refunded(
    session: AsyncSession, obj: Mapping[str, Any], *, event_id: str
) -> dict[str, Any]:
    charge = _ref(obj.get("id"))
    payment_intent = _ref(obj.get("payment_intent"))
    candidates = [item for item in (payment_intent, charge) if item]
    transaction: BillingTransaction | None = None
    if candidates:
        transaction = await session.scalar(
            select(BillingTransaction)
            .where(
                BillingTransaction.provider == PROVIDER,
                BillingTransaction.external_reference.in_(candidates),
            )
            .with_for_update()
            .limit(1)
        )
    if transaction is None and charge:
        transaction = await session.scalar(
            select(BillingTransaction)
            .where(
                BillingTransaction.provider == PROVIDER,
                BillingTransaction.transaction_metadata["stripe_charge"].as_string() == charge,
            )
            .limit(1)
        )
    if transaction is None and payment_intent:
        transaction = await session.scalar(
            select(BillingTransaction)
            .where(
                BillingTransaction.provider == PROVIDER,
                BillingTransaction.transaction_metadata["stripe_payment_intent"].as_string()
                == payment_intent,
            )
            .limit(1)
        )
    if transaction is None:
        return {"status": "ignored", "reason": "transaction-not-found"}

    refunded_total = _int(obj.get("amount_refunded"))
    currency = str(obj.get("currency") or transaction.currency).upper()[:3]
    recorded = list(
        (
            await session.scalars(
                select(BillingRefund).where(BillingRefund.transaction_id == transaction.id)
            )
        ).all()
    )
    known = {item.external_reference for item in recorded if item.external_reference}
    rows = _mapping(obj.get("refunds")).get("data") or []
    if isinstance(rows, list) and rows:
        for raw in rows:
            row = _mapping(raw)
            refund_ref = _ref(row.get("id"))
            if not refund_ref or refund_ref in known or row.get("status") not in (None, "succeeded"):
                continue
            session.add(
                BillingRefund(
                    organization_id=transaction.organization_id,
                    transaction_id=transaction.id,
                    invoice_id=transaction.invoice_id,
                    provider=PROVIDER,
                    external_reference=refund_ref,
                    amount_minor=_int(row.get("amount")),
                    currency=currency,
                    reason=str(row.get("reason") or "Stripe refund")[:240],
                    status="succeeded",
                    idempotency_key=f"stripe-refund:{refund_ref}"[:160],
                    completed_at=_ts(row.get("created")) or core.now(),
                    refund_metadata={"source": "stripe_webhook", "charge": charge},
                )
            )
            known.add(refund_ref)
    else:
        already = sum(item.amount_minor for item in recorded if item.status == "succeeded")
        delta = refunded_total - already
        if delta > 0:
            session.add(
                BillingRefund(
                    organization_id=transaction.organization_id,
                    transaction_id=transaction.id,
                    invoice_id=transaction.invoice_id,
                    provider=PROVIDER,
                    amount_minor=delta,
                    currency=currency,
                    reason="Stripe refund",
                    status="succeeded",
                    idempotency_key=f"stripe-charge-refund:{charge}:{refunded_total}"[:160],
                    completed_at=core.now(),
                    refund_metadata={"source": "stripe_webhook", "charge": charge},
                )
            )
    transaction.status = (
        "refunded"
        if refunded_total >= transaction.amount_minor or obj.get("refunded")
        else "partially_refunded"
    )
    if transaction.invoice_id:
        invoice = await session.get(BillingInvoice, transaction.invoice_id)
        if invoice is not None:
            invoice.amount_refunded_minor = max(invoice.amount_refunded_minor, refunded_total)
            if invoice.amount_paid_minor and invoice.amount_refunded_minor >= invoice.amount_paid_minor:
                invoice.status = "refunded"
    await session.flush()
    await notify_billing_event(
        session,
        transaction.organization_id,
        event_key="billing.refund.completed",
        title="Refund issued",
        message=f"A refund of {_money(refunded_total, currency)} was issued to the original payment method.",
        severity="info",
        dedupe=f"stripe-refund:{charge}:{refunded_total}",
        payload={"transaction_id": transaction.id, "amount_refunded_minor": refunded_total},
    )
    return {"status": "processed", "organization_id": transaction.organization_id}


async def handle_trial_will_end(
    session: AsyncSession, obj: Mapping[str, Any], *, event_id: str
) -> dict[str, Any]:
    reference = _ref(obj.get("id"))
    local = await _subscription_by_ref(session, reference)
    organization_id = (
        local.organization_id
        if local is not None
        else await _organization_for(
            session, metadata=_mapping(obj.get("metadata")), customer=_ref(obj.get("customer"))
        )
    )
    if not organization_id:
        return {"status": "ignored", "reason": "subscription-not-mapped"}
    trial_end = _ts(obj.get("trial_end"))
    if local is not None and trial_end is not None:
        local.trial_end = trial_end
    await notify_billing_event(
        session,
        organization_id,
        event_key="billing.subscription.trial_ending",
        title="Trial ending soon",
        message=(
            "Your free trial ends on "
            f"{trial_end.date().isoformat() if trial_end else 'the scheduled date'}. "
            "Add or confirm a payment method to keep paid features."
        ),
        severity="info",
        dedupe=f"stripe-trial:{reference}:{int(trial_end.timestamp()) if trial_end else 0}",
        payload={"trial_end": trial_end.isoformat() if trial_end else None},
    )
    return {"status": "processed", "organization_id": organization_id}


async def process_stripe_event(
    session: AsyncSession, payload: Mapping[str, Any], *, event_id: str, event_type: str
) -> dict[str, Any]:
    """Dispatch one verified Stripe event. Returns ``status`` and ``organization_id``."""

    obj = _mapping(_mapping(payload.get("data")).get("object"))
    event_created = _int(payload.get("created"))
    if event_type == "checkout.session.completed":
        return await handle_checkout_completed(session, obj, event_id=event_id)
    if event_type == "checkout.session.expired":
        return await handle_checkout_expired(session, obj)
    if event_type in SUBSCRIPTION_EVENTS:
        return await apply_subscription_object(
            session,
            obj,
            event_id=event_id,
            event_type=event_type,
            event_created=event_created,
        )
    if event_type == "customer.subscription.trial_will_end":
        return await handle_trial_will_end(session, obj, event_id=event_id)
    if event_type == "invoice.paid":
        return await handle_invoice(session, obj, event_id=event_id, paid=True)
    if event_type == "invoice.payment_failed":
        return await handle_invoice(session, obj, event_id=event_id, paid=False)
    if event_type == "charge.refunded":
        return await handle_charge_refunded(session, obj, event_id=event_id)
    return {"status": "ignored", "reason": "event-not-subscribed"}


# ------------------------------------------------------------------ lifecycle API


async def _latest_stripe_subscription(
    session: AsyncSession, organization_id: str, statuses: Sequence[str]
) -> BillingSubscription | None:
    return await session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.organization_id == organization_id,
            BillingSubscription.provider == PROVIDER,
            BillingSubscription.status.in_(tuple(statuses)),
        )
        .order_by(BillingSubscription.created_at.desc())
        .with_for_update()
        .limit(1)
    )


async def live_stripe_subscription(
    session: AsyncSession, organization_id: str
) -> BillingSubscription | None:
    return await session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.organization_id == organization_id,
            BillingSubscription.provider == PROVIDER,
            BillingSubscription.status.in_(LIVE_STRIPE_STATUSES),
        )
        .order_by(BillingSubscription.created_at.desc())
        .limit(1)
    )


async def change_subscription_plan(
    session: AsyncSession,
    actor: UserRecord,
    *,
    plan_code: str,
    period_code: str,
    idempotency_key: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Upgrade or downgrade the Stripe subscription with proration.

    Upgrades invoice the prorated difference at once with
    ``payment_behavior=pending_if_incomplete``: Stripe applies the new price
    only after that payment succeeds. Downgrades take effect at once and the
    unused time is credited on the next invoice. Local entitlements change
    when the resulting ``customer.subscription.updated`` webhook arrives.
    """

    subscription = await _latest_stripe_subscription(
        session, actor.organization_id, CHANGEABLE_STATUSES
    )
    if subscription is None or not subscription.external_reference:
        raise HTTPException(status_code=404, detail="Active card subscription not found")
    plan = await session.scalar(
        select(BillingPlan).where(BillingPlan.code == core._normalized_plan_code(plan_code))
    )
    if plan is None or plan.status != "active":
        raise HTTPException(status_code=404, detail="Active billing plan not found")
    current_price = (
        await session.get(BillingPrice, subscription.price_id) if subscription.price_id else None
    )
    candidates = list(
        (
            await session.scalars(
                select(BillingPrice).where(
                    BillingPrice.plan_id == plan.id,
                    BillingPrice.period_code == period_code.strip().lower(),
                    BillingPrice.enabled.is_(True),
                    BillingPrice.provider == PROVIDER,
                )
            )
        ).all()
    )
    if current_price is not None:
        same_currency = [item for item in candidates if item.currency == current_price.currency]
        candidates = same_currency or candidates
    target = next((item for item in candidates if item.provider_reference), None)
    if target is None or not target.amount_minor or target.amount_minor <= 0:
        raise HTTPException(status_code=404, detail="Active card price not found for this plan")
    if subscription.price_id == target.id:
        raise HTTPException(status_code=409, detail="The subscription already uses this plan")
    metadata = dict(subscription.subscription_metadata or {})
    item_id = str(metadata.get("stripe_item") or "")
    if not item_id:
        remote = await stripe_request(
            "GET",
            f"/v1/subscriptions/{subscription.external_reference}",
            transport=transport,
            failure="Stripe subscription lookup failed",
        )
        item_id = _ref(_first_item(remote).get("id")) or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="Stripe subscription item is missing")
    upgrade = monthly_equivalent(target) > monthly_equivalent(current_price)
    data: list[tuple[str, str]] = [
        ("items[0][id]", item_id),
        ("items[0][price]", str(target.provider_reference)),
        ("proration_behavior", "always_invoice" if upgrade else "create_prorations"),
    ]
    if upgrade:
        data.append(("payment_behavior", "pending_if_incomplete"))
    key = _idempotency(idempotency_key, "change", subscription.id)
    response = await stripe_request(
        "POST",
        f"/v1/subscriptions/{subscription.external_reference}",
        data=data,
        idempotency_key=key,
        transport=transport,
        failure="Stripe plan change failed",
    )
    pending_payment = bool(response.get("pending_update"))
    metadata["stripe_item"] = item_id
    metadata["pending_change"] = {
        "plan_code": plan.code,
        "price_id": target.id,
        "direction": "upgrade" if upgrade else "downgrade",
        "requested_at": core.now().isoformat(),
        "requested_by": actor.id,
        "pending_payment": pending_payment,
    }
    subscription.subscription_metadata = metadata
    session.add(
        core._audit(
            actor,
            "billing.subscription.change_requested",
            "billing_subscription",
            subscription.id,
            {
                "organization_id": actor.organization_id,
                "from_price": subscription.price_id,
                "to_price": target.id,
                "direction": "upgrade" if upgrade else "downgrade",
                "pending_payment": pending_payment,
            },
        )
    )
    await session.commit()
    return core.subscription_snapshot(subscription) | {
        "change": {
            "plan_code": plan.code,
            "period_code": target.period_code,
            "direction": "upgrade" if upgrade else "downgrade",
            "proration": "invoiced_now" if upgrade else "credited_next_invoice",
            "pending_payment": pending_payment,
            "applies_after_webhook": True,
        }
    }


async def resume_subscription(
    session: AsyncSession,
    actor: UserRecord,
    *,
    idempotency_key: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Reactivate: remove a scheduled cancel-at-period-end before the period ends.

    A subscription that already ended cannot be resumed on Stripe; the
    customer starts a new checkout instead (``create_checkout`` allows it).
    """

    subscription = await _latest_stripe_subscription(
        session, actor.organization_id, ("active", "trialing", "past_due")
    )
    if subscription is None or not subscription.external_reference:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUBSCRIPTION_NOT_RESUMABLE",
                "message": "No live card subscription to resume; start a new checkout instead",
            },
        )
    if not subscription.cancel_at_period_end:
        return core.subscription_snapshot(subscription)
    key = _idempotency(idempotency_key, "resume", subscription.id)
    await stripe_request(
        "POST",
        f"/v1/subscriptions/{subscription.external_reference}",
        data=[("cancel_at_period_end", "false")],
        idempotency_key=key,
        transport=transport,
        failure="Stripe reactivation failed",
    )
    subscription.cancel_at_period_end = False
    session.add(
        core._audit(
            actor,
            "billing.subscription.resumed",
            "billing_subscription",
            subscription.id,
            {"organization_id": actor.organization_id},
        )
    )
    await session.commit()
    return core.subscription_snapshot(subscription)


# ------------------------------------------------------------------ owner view


async def owner_subscription_view(session: AsyncSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(BillingSubscription, Organization, BillingPlan, BillingPrice)
            .join(Organization, Organization.id == BillingSubscription.organization_id)
            .join(BillingPlan, BillingPlan.id == BillingSubscription.plan_id)
            .outerjoin(BillingPrice, BillingPrice.id == BillingSubscription.price_id)
            .order_by(BillingSubscription.created_at.desc())
            .limit(500)
        )
    ).all()
    moment = core.now()
    mrr: dict[str, int] = {}
    counts = {"active": 0, "trialing": 0, "past_due": 0, "canceling": 0, "canceled": 0}
    items: list[dict[str, Any]] = []
    for subscription, organization, plan, price in rows:
        end = core._as_utc(subscription.current_period_end)
        live = end is None or end > moment
        status = subscription.status
        if status in counts:
            counts[status] += 1
        if status in {"active", "trialing"} and subscription.cancel_at_period_end:
            counts["canceling"] += 1
        monthly = 0
        if status == "active" and live and price is not None and price.amount_minor:
            monthly = int(round(monthly_equivalent(price)))
            mrr[price.currency] = mrr.get(price.currency, 0) + monthly
        items.append(
            core.subscription_snapshot(subscription)
            | {
                "organization_id": organization.id,
                "organization": organization.name,
                "plan": plan.code,
                "plan_name": plan.name,
                "currency": price.currency if price is not None else None,
                "monthly_amount_minor": monthly,
            }
        )
    default_currency = core._currency(None)
    return {
        "subscriptions": items,
        "summary": {
            "mrr_minor": mrr.get(default_currency, 0),
            "mrr_currency": default_currency,
            "mrr_by_currency": mrr,
            "active_subscriptions": counts["active"],
            "trialing_subscriptions": counts["trialing"],
            "past_due_subscriptions": counts["past_due"],
            "canceling_subscriptions": counts["canceling"],
            "canceled_subscriptions": counts["canceled"],
        },
    }


def webhook_contract() -> dict[str, Any]:
    """Public description of the Stripe webhook endpoint for the go-live runbook."""

    return {
        "path": "/api/v1/billing/webhooks/stripe",
        "events": list(HANDLED_EVENTS),
        "signature_header": "Stripe-Signature",
        "tolerance_seconds": settings.PAYMENTS_WEBHOOK_TOLERANCE_SECONDS,
    }

