"""Authoritative native App Store and Google Play subscription lifecycle."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    BillingAccount,
    BillingPlan,
    BillingPrice,
    BillingSubscription,
    MobileStoreEvent,
    MobileStoreProduct,
    MobileStorePurchase,
)

StoreName = Literal["app_store", "google_play"]
ACTIVE_PURCHASE_STATES = {"active", "grace_period"}
GOOGLE_ACTIVE_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE": "active",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
    "SUBSCRIPTION_STATE_ON_HOLD": "on_hold",
    "SUBSCRIPTION_STATE_PAUSED": "paused",
    "SUBSCRIPTION_STATE_CANCELED": "canceled",
    "SUBSCRIPTION_STATE_EXPIRED": "expired",
    "SUBSCRIPTION_STATE_PENDING": "pending",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc) if value else None


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    return Fernet(
        base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    )


def _encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored Google Play token cannot be decrypted") from exc


def _enum_value(v: Any) -> Any:
    return getattr(v, "value", v)


def store_readiness() -> dict[str, Any]:
    apple_roots = Path(settings.APP_STORE_ROOT_CERTIFICATES_DIR or "")
    return {
        "app_store": {
            "configured": bool(
                settings.APP_STORE_BUNDLE_ID
                and settings.APP_STORE_ISSUER_ID
                and settings.APP_STORE_KEY_ID
                and settings.APP_STORE_PRIVATE_KEY
                and settings.APP_STORE_ROOT_CERTIFICATES_DIR
                and apple_roots.is_dir()
            ),
            "bundle_id": settings.APP_STORE_BUNDLE_ID,
            "environment": settings.APP_STORE_ENVIRONMENT,
            "server_verification": "active",
            "notifications_v2": "active",
        },
        "google_play": {
            "configured": bool(
                settings.GOOGLE_PLAY_PACKAGE_NAME
                and settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON
            ),
            "package_name": settings.GOOGLE_PLAY_PACKAGE_NAME,
            "server_verification": "active",
            "rtdn": "active"
            if settings.GOOGLE_PLAY_PUBSUB_AUDIENCE
            and settings.GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT_EMAIL
            else "needs_pubsub_identity_config",
        },
    }


async def catalogue(session: AsyncSession, store: StoreName) -> list[dict[str, Any]]:
    items = (
        await session.scalars(
            select(MobileStoreProduct)
            .where(
                MobileStoreProduct.store == store, MobileStoreProduct.status == "active"
            )
            .order_by(MobileStoreProduct.created_at.asc())
        )
    ).all()
    result = []
    for x in items:
        plan = await session.get(BillingPlan, x.plan_id)
        from app.db.models import BillingPrice

        price = await session.get(BillingPrice, x.price_id)
        result.append(
            {
                "id": x.id,
                "store": x.store,
                "product_id": x.product_id,
                "base_plan_id": x.base_plan_id,
                "offer_id": x.offer_id,
                "plan_id": x.plan_id,
                "price_id": x.price_id,
                "plan_code": plan.code if plan else "",
                "period_code": price.period_code if price else "",
                "active": x.status == "active",
            }
        )
    return result


def _apple_verifier():
    try:
        from appstoreserverlibrary.models.Environment import Environment
        from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    except ImportError as exc:
        raise RuntimeError("App Store Server Library is not installed") from exc
    env = (
        Environment.PRODUCTION
        if settings.APP_STORE_ENVIRONMENT.lower() == "production"
        else Environment.SANDBOX
    )
    roots_dir = Path(settings.APP_STORE_ROOT_CERTIFICATES_DIR or "")
    roots = [p.read_bytes() for p in sorted(roots_dir.glob("*.cer"))] + [
        p.read_bytes() for p in sorted(roots_dir.glob("*.der"))
    ]
    if not roots:
        raise RuntimeError("Apple root certificates are not configured")
    return SignedDataVerifier(
        roots, True, env, settings.APP_STORE_BUNDLE_ID, settings.APP_STORE_APPLE_ID
    )


async def _google_access_token() -> str:
    try:
        creds = json.loads(settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid Google Play service account JSON") from exc
    now = int(_now().timestamp())
    assertion = jwt.encode(
        {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/androidpublisher",
            "aud": creds.get("token_uri", "https://oauth2.googleapis.com/token"),
            "iat": now,
            "exp": now + 3600,
        },
        creds["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            creds.get("token_uri", "https://oauth2.googleapis.com/token"),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def _google_get_subscription(token: str) -> dict[str, Any]:
    access = await _google_access_token()
    package = quote(settings.GOOGLE_PLAY_PACKAGE_NAME or "", safe="")
    tok = quote(token, safe="")
    url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package}/purchases/subscriptionsv2/tokens/{tok}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {access}", "Accept": "application/json"},
        )
        if r.status_code in {404, 410}:
            raise HTTPException(
                400, "Google Play purchase token is invalid or no longer available"
            )
        r.raise_for_status()
        return r.json()


async def _google_acknowledge(token: str, product_id: str) -> bool:
    access = await _google_access_token()
    package = quote(settings.GOOGLE_PLAY_PACKAGE_NAME or "", safe="")
    product = quote(product_id, safe="")
    tok = quote(token, safe="")
    url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package}/purchases/subscriptions/{product}/tokens/{tok}:acknowledge"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json",
            },
            json={},
        )
        if r.status_code in {200, 204, 409}:
            return True
        r.raise_for_status()
        return True


def _normalize_google(data: dict[str, Any]) -> dict[str, Any]:
    lines: list[dict[str, Any]] = [
        item for item in (data.get("lineItems") or []) if isinstance(item, dict)
    ]
    line: dict[str, Any] = max(
        lines, key=lambda item: str(item.get("expiryTime", "")), default={}
    )
    raw_state = str(data.get("subscriptionState") or "")
    status_ = GOOGLE_ACTIVE_STATES.get(raw_state, "unknown")
    expiry = _iso(str(line.get("expiryTime") or "") or None)
    # Google CANCELED means auto-renew is off; access remains valid through expiry.
    if status_ == "canceled" and expiry and expiry > _now():
        status_ = "active"
    return {
        "status": status_,
        "external_transaction_id": line.get("latestSuccessfulOrderId")
        or data.get("latestOrderId"),
        "original_transaction_id": None,
        "product_id": line.get("productId"),
        "purchased_at": _iso(data.get("startTime")),
        "expires_at": expiry,
        "auto_renewing": bool(
            (line.get("autoRenewingPlan") or {}).get("autoRenewEnabled")
        ),
        "revoked_at": None,
        "metadata": {
            "subscription_state": raw_state,
            "acknowledgement_state": data.get("acknowledgementState"),
            "region_code": data.get("regionCode"),
            "linked_purchase_token_hash": _token_hash(data["linkedPurchaseToken"])
            if data.get("linkedPurchaseToken")
            else None,
            "base_plan_id": ((line.get("offerDetails") or {}).get("basePlanId")),
            "offer_id": ((line.get("offerDetails") or {}).get("offerId")),
        },
    }


def _normalize_apple(
    tx: Any, renewal: Any | None = None, event_type: str | None = None
) -> dict[str, Any]:
    revoked = _ms(getattr(tx, "revocationDate", None))
    expiry = _ms(getattr(tx, "expiresDate", None))
    status_ = (
        "revoked"
        if revoked
        else ("expired" if expiry and expiry <= _now() else "active")
    )
    if (
        event_type in {"SUBSCRIBED", "DID_RENEW", "OFFER_REDEEMED", "REFUND_REVERSED"}
        and not revoked
    ):
        status_ = "active" if not expiry or expiry > _now() else "expired"
    if event_type in {"EXPIRED", "GRACE_PERIOD_EXPIRED"}:
        status_ = "expired"
    if event_type in {"REFUND", "REVOKE"}:
        status_ = "revoked"
    if event_type == "DID_FAIL_TO_RENEW":
        grace_expiry = (
            _ms(getattr(renewal, "gracePeriodExpiresDate", None))
            if renewal is not None
            else None
        )
        status_ = (
            "grace_period"
            if grace_expiry is not None and grace_expiry > _now()
            else "billing_retry"
        )
    auto = True
    if renewal is not None and getattr(renewal, "rawAutoRenewStatus", None) is not None:
        auto = getattr(renewal, "rawAutoRenewStatus", None) == 1
    return {
        "status": status_,
        "external_transaction_id": getattr(tx, "transactionId", None),
        "original_transaction_id": getattr(tx, "originalTransactionId", None),
        "product_id": getattr(tx, "productId", None),
        "purchased_at": _ms(getattr(tx, "purchaseDate", None)),
        "expires_at": expiry,
        "auto_renewing": auto,
        "revoked_at": revoked,
        "metadata": {
            "environment": _enum_value(getattr(tx, "environment", None)),
            "transaction_reason": getattr(tx, "rawTransactionReason", None),
            "web_order_line_item_id": getattr(tx, "webOrderLineItemId", None),
        },
    }


async def _find_product(
    session: AsyncSession,
    store: str,
    product_id: str,
    requested: MobileStoreProduct | None = None,
) -> MobileStoreProduct:
    if (
        requested is not None
        and requested.product_id == product_id
        and requested.store == store
        and requested.status == "active"
    ):
        return requested
    item = await session.scalar(
        select(MobileStoreProduct)
        .where(
            MobileStoreProduct.store == store,
            MobileStoreProduct.product_id == product_id,
            MobileStoreProduct.status == "active",
        )
        .limit(1)
    )
    if item is None:
        raise HTTPException(400, "Store product is not mapped to an active AIONEX plan")
    return item


async def _upsert_purchase(
    session: AsyncSession,
    *,
    actor: Any | None,
    product: MobileStoreProduct,
    store: str,
    normalized: dict[str, Any],
    token_hash: str | None = None,
    raw_token: str | None = None,
) -> MobileStorePurchase:
    purchase = None
    ext = normalized.get("external_transaction_id")
    if ext:
        purchase = await session.scalar(
            select(MobileStorePurchase).where(
                MobileStorePurchase.store == store,
                MobileStorePurchase.external_transaction_id == ext,
            )
        )
    if purchase is None and token_hash:
        purchase = await session.scalar(
            select(MobileStorePurchase)
            .where(
                MobileStorePurchase.store == store,
                MobileStorePurchase.purchase_token_hash == token_hash,
            )
            .order_by(MobileStorePurchase.created_at.desc())
            .limit(1)
        )
    if purchase is None:
        if actor is None:
            raise LookupError("No existing purchase identity for store notification")
        purchase = MobileStorePurchase(
            organization_id=actor.organization_id,
            user_id=actor.id,
            product_id=product.id,
            store=store,
        )
        session.add(purchase)
    elif actor is not None and (
        purchase.organization_id != actor.organization_id
        or purchase.user_id != actor.id
    ):
        raise HTTPException(
            status_code=409,
            detail="Store transaction is already bound to another AIONEX account",
        )
    purchase.product_id = product.id
    purchase.external_transaction_id = ext or purchase.external_transaction_id
    purchase.original_transaction_id = (
        normalized.get("original_transaction_id") or purchase.original_transaction_id
    )
    purchase.purchase_token_hash = token_hash or purchase.purchase_token_hash
    if raw_token:
        purchase.purchase_token_ciphertext = _encrypt_token(raw_token)
    purchase.status = normalized["status"]
    purchase.verified = True
    purchase.auto_renewing = normalized.get("auto_renewing", False)
    purchase.purchased_at = normalized.get("purchased_at")
    purchase.expires_at = normalized.get("expires_at")
    purchase.revoked_at = normalized.get("revoked_at")
    purchase.verification_metadata = {
        **(purchase.verification_metadata or {}),
        **normalized.get("metadata", {}),
        "verified_at": _now().isoformat(),
        "server_verification_required": True,
    }
    await session.flush()
    await _sync_entitlements(session, purchase, product)
    return purchase


async def _sync_entitlements(
    session: AsyncSession, purchase: MobileStorePurchase, product: MobileStoreProduct
) -> None:
    """Recompute one durable account grant from all provider subscriptions.

    Multiple providers may represent the same customer, but entitlements are granted once
    at account level. A verified active subscription with the furthest period end wins;
    this preserves a valid Stripe/web subscription while mobile-store state changes.
    """
    ref = (
        purchase.original_transaction_id
        or purchase.purchase_token_hash
        or purchase.external_transaction_id
    )
    sub = await session.scalar(
        select(BillingSubscription).where(
            BillingSubscription.provider == purchase.store,
            BillingSubscription.external_reference == ref,
        )
    )
    if sub is None:
        sub = BillingSubscription(
            organization_id=purchase.organization_id,
            plan_id=product.plan_id,
            price_id=product.price_id,
            provider=purchase.store,
            external_reference=ref,
        )
        session.add(sub)
    sub.plan_id = product.plan_id
    sub.price_id = product.price_id
    sub.status = (
        "active" if purchase.status in ACTIVE_PURCHASE_STATES else purchase.status
    )
    sub.cancel_at_period_end = not purchase.auto_renewing
    sub.current_period_start = purchase.purchased_at
    sub.current_period_end = purchase.expires_at
    sub.canceled_at = (
        _now() if purchase.status in {"canceled", "expired", "revoked"} else None
    )
    sub.subscription_metadata = {
        **(sub.subscription_metadata or {}),
        "source": "mobile_store",
        "purchase_id": purchase.id,
    }
    await session.flush()

    account = await session.scalar(
        select(BillingAccount).where(
            BillingAccount.organization_id == purchase.organization_id
        )
    )
    active = (
        await session.scalars(
            select(BillingSubscription).where(
                BillingSubscription.organization_id == purchase.organization_id,
                BillingSubscription.status.in_(["active", "trialing", "grace_period"]),
            )
        )
    ).all()
    if active:
        # Prefer the subscription with the latest known period end; stable provider/id tie-breakers
        # make reconciliation deterministic and prevent duplicate entitlement grants.
        def rank(item: BillingSubscription):
            end = item.current_period_end or datetime.max.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return (end, item.provider, item.id)

        authoritative = max(active, key=rank)
        plan = await session.get(BillingPlan, authoritative.plan_id)
        if account is None:
            account = BillingAccount(organization_id=purchase.organization_id)
            session.add(account)
        account.plan_id = authoritative.plan_id
        account.status = "active"
        account.entitlements = list(plan.entitlements if plan else [])
        account.limits = dict(plan.limits if plan else {})
        account.current_period_end = authoritative.current_period_end
        account.provider_customers = {
            **(account.provider_customers or {}),
            "entitlement_source": authoritative.provider,
            "entitlement_subscription_id": authoritative.id,
        }
    elif account is not None:
        account.plan_id = None
        account.status = "inactive"
        account.entitlements = []
        account.limits = {}
        account.current_period_end = purchase.expires_at
        account.provider_customers = {
            k: v
            for k, v in (account.provider_customers or {}).items()
            if k not in {"entitlement_source", "entitlement_subscription_id"}
        }
    await session.flush()


async def submit_purchase_for_verification(
    session: AsyncSession,
    *,
    actor: Any,
    store: StoreName,
    product_record_id: str,
    signed_transaction: str | None = None,
    purchase_token: str | None = None,
) -> dict[str, Any]:
    product = await session.get(MobileStoreProduct, product_record_id)
    if product is None or product.store != store or product.status != "active":
        raise HTTPException(404, "Mobile store product not found")
    try:
        if store == "app_store":
            if not signed_transaction:
                raise HTTPException(400, "Signed App Store transaction is required")
            tx = _apple_verifier().verify_and_decode_signed_transaction(
                signed_transaction
            )
            normalized = _normalize_apple(tx)
            if normalized["product_id"] != product.product_id:
                raise HTTPException(
                    400, "App Store product does not match AIONEX mapping"
                )
            purchase = await _upsert_purchase(
                session,
                actor=actor,
                product=product,
                store=store,
                normalized=normalized,
            )
        else:
            if not purchase_token:
                raise HTTPException(400, "Google Play purchase token is required")
            data = await _google_get_subscription(purchase_token)
            normalized = _normalize_google(data)
            if normalized["product_id"] != product.product_id:
                raise HTTPException(
                    400, "Google Play product does not match AIONEX mapping"
                )
            purchase = await _upsert_purchase(
                session,
                actor=actor,
                product=product,
                store=store,
                normalized=normalized,
                token_hash=_token_hash(purchase_token),
                raw_token=purchase_token,
            )
            if data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING":
                await _google_acknowledge(purchase_token, product.product_id)
                purchase.verification_metadata = {
                    **purchase.verification_metadata,
                    "acknowledged_by_server": True,
                }
        await session.commit()
        return {
            "id": purchase.id,
            "store": store,
            "status": purchase.status,
            "verified": True,
            "auto_renewing": purchase.auto_renewing,
            "expires_at": purchase.expires_at,
            "server_acknowledged": bool(
                (purchase.verification_metadata or {}).get("acknowledged_by_server")
            ),
        }
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Store verification is temporarily unavailable",
        ) from exc


async def process_app_store_notification(
    session: AsyncSession, signed_payload: str
) -> dict[str, Any]:
    verifier = _apple_verifier()
    notification = verifier.verify_and_decode_notification(signed_payload)
    event_id = (
        notification.notificationUUID
        or hashlib.sha256(signed_payload.encode()).hexdigest()
    )
    event_type = notification.rawNotificationType or "UNKNOWN"
    existing = await session.scalar(
        select(MobileStoreEvent).where(
            MobileStoreEvent.store == "app_store",
            MobileStoreEvent.external_event_id == event_id,
        )
    )
    if existing and existing.status == "processed":
        return {"status": "duplicate", "event_id": event_id}
    event = existing or MobileStoreEvent(
        store="app_store",
        external_event_id=event_id,
        event_type=event_type,
        payload_hash=hashlib.sha256(signed_payload.encode()).hexdigest(),
        event_payload={
            "notification_type": event_type,
            "subtype": notification.rawSubtype,
        },
    )
    if existing:
        event.status = "received"
        event.error = None
    else:
        session.add(event)
    try:
        if notification.data and notification.data.signedTransactionInfo:
            tx = verifier.verify_and_decode_signed_transaction(
                notification.data.signedTransactionInfo
            )
            renewal = (
                verifier.verify_and_decode_renewal_info(
                    notification.data.signedRenewalInfo
                )
                if notification.data.signedRenewalInfo
                else None
            )
            normalized = _normalize_apple(tx, renewal, event_type)
            product = await _find_product(
                session, "app_store", normalized["product_id"]
            )
            purchase = await session.scalar(
                select(MobileStorePurchase)
                .where(
                    MobileStorePurchase.store == "app_store",
                    MobileStorePurchase.original_transaction_id
                    == normalized["original_transaction_id"],
                )
                .order_by(MobileStorePurchase.created_at.desc())
                .limit(1)
            )
            if purchase:
                actor = type(
                    "BoundActor",
                    (),
                    {
                        "organization_id": purchase.organization_id,
                        "id": purchase.user_id,
                    },
                )()
                await _upsert_purchase(
                    session,
                    actor=actor,
                    product=product,
                    store="app_store",
                    normalized=normalized,
                )
        event.status = "processed"
        event.processed_at = _now()
        await session.commit()
        return {"status": "processed", "event_id": event_id}
    except Exception as exc:
        event.status = "failed"
        event.error = type(exc).__name__
        await session.commit()
        raise


async def verify_google_pubsub_token(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Google Pub/Sub identity token")
    audience = settings.GOOGLE_PLAY_PUBSUB_AUDIENCE
    expected = settings.GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT_EMAIL
    if not audience or not expected:
        raise HTTPException(
            503, "Google Pub/Sub identity verification is not configured"
        )
    try:
        key = (
            jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")
            .get_signing_key_from_jwt(authorization[7:])
            .key
        )
        claims = jwt.decode(
            authorization[7:],
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
        if claims.get("email") != expected or claims.get("email_verified") is not True:
            raise ValueError("unexpected Pub/Sub service account")
    except Exception as exc:
        raise HTTPException(401, "Invalid Google Pub/Sub identity token") from exc


async def process_google_notification(
    session: AsyncSession, envelope: dict[str, Any]
) -> dict[str, Any]:
    message = envelope.get("message") or {}
    event_id = message.get("messageId") or message.get("message_id")
    if not event_id:
        raise HTTPException(400, "Pub/Sub messageId is required")
    existing = await session.scalar(
        select(MobileStoreEvent).where(
            MobileStoreEvent.store == "google_play",
            MobileStoreEvent.external_event_id == event_id,
        )
    )
    if existing and existing.status == "processed":
        return {"status": "duplicate", "event_id": event_id}
    try:
        payload = json.loads(base64.b64decode(message["data"]).decode())
    except Exception as exc:
        raise HTTPException(400, "Invalid Google Play RTDN payload") from exc
    sub = payload.get("subscriptionNotification") or {}
    token = sub.get("purchaseToken")
    ntype = sub.get("notificationType")
    event = existing or MobileStoreEvent(
        store="google_play",
        external_event_id=event_id,
        event_type=f"subscription:{ntype}",
        payload_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest(),
        event_payload={"version": payload.get("version"), "notification_type": ntype},
    )
    if existing:
        event.status = "received"
        event.error = None
    else:
        session.add(event)
    try:
        if token:
            normalized = _normalize_google(await _google_get_subscription(token))
            product = await _find_product(
                session, "google_play", normalized["product_id"]
            )
            th = _token_hash(token)
            purchase = await session.scalar(
                select(MobileStorePurchase)
                .where(
                    MobileStorePurchase.store == "google_play",
                    MobileStorePurchase.purchase_token_hash == th,
                )
                .order_by(MobileStorePurchase.created_at.desc())
                .limit(1)
            )
            if purchase:
                actor = type(
                    "BoundActor",
                    (),
                    {
                        "organization_id": purchase.organization_id,
                        "id": purchase.user_id,
                    },
                )()
                await _upsert_purchase(
                    session,
                    actor=actor,
                    product=product,
                    store="google_play",
                    normalized=normalized,
                    token_hash=th,
                    raw_token=token,
                )
        event.status = "processed"
        event.processed_at = _now()
        await session.commit()
        return {"status": "processed", "event_id": event_id}
    except Exception as exc:
        event.status = "failed"
        event.error = type(exc).__name__
        await session.commit()
        raise


async def _apple_api_client():
    from appstoreserverlibrary.api_client import AsyncAppStoreServerAPIClient
    from appstoreserverlibrary.models.Environment import Environment

    env = (
        Environment.PRODUCTION
        if settings.APP_STORE_ENVIRONMENT.lower() == "production"
        else Environment.SANDBOX
    )
    return AsyncAppStoreServerAPIClient(
        (settings.APP_STORE_PRIVATE_KEY or "").replace("\\n", "\n").encode(),
        settings.APP_STORE_KEY_ID or "",
        settings.APP_STORE_ISSUER_ID or "",
        settings.APP_STORE_BUNDLE_ID or "",
        env,
    )


async def reconcile_user_store(
    session: AsyncSession, *, actor: Any, store: StoreName
) -> dict[str, Any]:
    purchases = (
        await session.scalars(
            select(MobileStorePurchase)
            .where(
                MobileStorePurchase.organization_id == actor.organization_id,
                MobileStorePurchase.user_id == actor.id,
                MobileStorePurchase.store == store,
                MobileStorePurchase.verified.is_(True),
            )
            .order_by(MobileStorePurchase.updated_at.desc())
            .limit(100)
        )
    ).all()
    checked = updated = failed = 0
    if store == "google_play":
        for purchase in purchases:
            if not purchase.purchase_token_ciphertext:
                continue
            checked += 1
            try:
                token = _decrypt_token(purchase.purchase_token_ciphertext)
                normalized = _normalize_google(await _google_get_subscription(token))
                product = await _find_product(
                    session, "google_play", normalized["product_id"]
                )
                await _upsert_purchase(
                    session,
                    actor=actor,
                    product=product,
                    store="google_play",
                    normalized=normalized,
                    token_hash=_token_hash(token),
                    raw_token=token,
                )
                updated += 1
            except Exception:
                failed += 1
    else:
        verifier = _apple_verifier()
        client = await _apple_api_client()
        seen = set()
        try:
            for purchase in purchases:
                oid = purchase.original_transaction_id
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                checked += 1
                try:
                    response = await client.get_all_subscription_statuses(oid)
                    for group in response.data or []:
                        for item in group.lastTransactions or []:
                            if not item.signedTransactionInfo:
                                continue
                            tx = verifier.verify_and_decode_signed_transaction(
                                item.signedTransactionInfo
                            )
                            renewal = (
                                verifier.verify_and_decode_renewal_info(
                                    item.signedRenewalInfo
                                )
                                if item.signedRenewalInfo
                                else None
                            )
                            normalized = _normalize_apple(tx, renewal)
                            product = await _find_product(
                                session, "app_store", normalized["product_id"]
                            )
                            await _upsert_purchase(
                                session,
                                actor=actor,
                                product=product,
                                store="app_store",
                                normalized=normalized,
                            )
                            updated += 1
                except Exception:
                    failed += 1
        finally:
            await client.async_close()
    await session.commit()
    return {
        "store": store,
        "checked": checked,
        "updated": updated,
        "failed": failed,
        "authoritative": True,
    }


async def subscription_status(session: AsyncSession, *, actor: Any) -> dict[str, Any]:
    items = (
        await session.scalars(
            select(MobileStorePurchase)
            .where(
                MobileStorePurchase.organization_id == actor.organization_id,
                MobileStorePurchase.user_id == actor.id,
            )
            .order_by(MobileStorePurchase.created_at.desc())
            .limit(50)
        )
    ).all()
    return {
        "purchases": [
            {
                "id": x.id,
                "store": x.store,
                "status": x.status,
                "verified": x.verified,
                "auto_renewing": x.auto_renewing,
                "expires_at": x.expires_at,
                "revoked_at": x.revoked_at,
            }
            for x in items
        ]
    }


def _store_management_url(store: str) -> str | None:
    if store == "app_store":
        return "https://apps.apple.com/account/subscriptions"
    if store == "google_play":
        package = quote(settings.GOOGLE_PLAY_PACKAGE_NAME or "net.vipe.aionex", safe="")
        return f"https://play.google.com/store/account/subscriptions?package={package}"
    return None


def store_source_label(store: str) -> str:
    return {
        "app_store": "Apple App Store",
        "google_play": "Google Play",
        "stripe": "Stripe",
    }.get(store, store.replace("_", " ").title())


async def owner_store_overview(session: AsyncSession) -> dict[str, Any]:
    mappings = (
        await session.scalars(
            select(MobileStoreProduct).order_by(
                MobileStoreProduct.store, MobileStoreProduct.created_at
            )
        )
    ).all()
    rows = []
    mapped_pairs: dict[str, set[tuple[str, str]]] = {
        "app_store": set(),
        "google_play": set(),
    }
    for item in mappings:
        mapping_plan = await session.get(BillingPlan, item.plan_id)
        mapping_price = await session.get(BillingPrice, item.price_id)
        if item.status == "active" and mapping_plan and mapping_price:
            mapped_pairs.setdefault(item.store, set()).add(
                (mapping_plan.code, mapping_price.period_code)
            )
        rows.append(
            {
                "id": item.id,
                "store": item.store,
                "product_id": item.product_id,
                "base_plan_id": item.base_plan_id,
                "offer_id": item.offer_id,
                "status": item.status,
                "plan_id": item.plan_id,
                "plan_code": mapping_plan.code if mapping_plan else None,
                "price_id": item.price_id,
                "period_code": mapping_price.period_code if mapping_price else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        )
    prices = (
        await session.execute(
            select(BillingPrice, BillingPlan)
            .join(BillingPlan, BillingPlan.id == BillingPrice.plan_id)
            .where(BillingPrice.enabled.is_(True), BillingPlan.status == "active")
            .order_by(BillingPlan.code, BillingPrice.period_code)
        )
    ).all()
    readiness = store_readiness()
    diagnostics = []
    for store in ("app_store", "google_play"):
        if not readiness[store]["configured"]:
            diagnostics.append(
                {
                    "severity": "error",
                    "store": store,
                    "code": "provider_not_configured",
                    "message": f"{store_source_label(store)} server credentials are incomplete.",
                }
            )
        if store == "google_play" and readiness[store]["rtdn"] != "active":
            diagnostics.append(
                {
                    "severity": "warning",
                    "store": store,
                    "code": "rtdn_identity_missing",
                    "message": "Google Play RTDN Pub/Sub identity is not fully configured.",
                }
            )
        for catalog_price, catalog_plan in prices:
            if (catalog_plan.code, catalog_price.period_code) not in mapped_pairs.get(store, set()):
                diagnostics.append(
                    {
                        "severity": "warning",
                        "store": store,
                        "code": "unmapped_price",
                        "plan_code": catalog_plan.code,
                        "period_code": catalog_price.period_code,
                        "message": f"{catalog_plan.code}/{catalog_price.period_code} has no active {store_source_label(store)} mapping.",
                    }
                )
    return {
        "readiness": readiness,
        "mappings": rows,
        "diagnostics": diagnostics,
        "catalog_options": [
            {
                "plan_id": catalog_plan.id,
                "plan_code": catalog_plan.code,
                "price_id": catalog_price.id,
                "period_code": catalog_price.period_code,
                "currency": catalog_price.currency,
                "amount_minor": catalog_price.amount_minor,
            }
            for catalog_price, catalog_plan in prices
        ],
    }


async def owner_upsert_store_mapping(
    session: AsyncSession,
    *,
    store: StoreName,
    plan_code: str,
    period_code: str,
    product_id: str,
    base_plan_id: str | None = None,
    offer_id: str | None = None,
    mapping_id: str | None = None,
    active: bool = True,
) -> dict[str, Any]:
    plan = await session.scalar(
        select(BillingPlan).where(BillingPlan.code == plan_code)
    )
    if plan is None:
        raise HTTPException(404, "Billing plan not found")
    price = await session.scalar(
        select(BillingPrice).where(
            BillingPrice.plan_id == plan.id, BillingPrice.period_code == period_code
        )
    )
    if price is None:
        raise HTTPException(404, "Billing price period not found")
    product_id = product_id.strip()
    if not product_id:
        raise HTTPException(422, "Store product ID is required")
    item = await session.get(MobileStoreProduct, mapping_id) if mapping_id else None
    if mapping_id and item is None:
        raise HTTPException(404, "Mobile store mapping not found")
    if item is None:
        item = MobileStoreProduct(
            plan_id=plan.id, price_id=price.id, store=store, product_id=product_id
        )
        session.add(item)
    elif item.store != store:
        raise HTTPException(409, "Mapping belongs to a different store")
    item.plan_id = plan.id
    item.price_id = price.id
    item.product_id = product_id
    item.base_plan_id = base_plan_id.strip() if base_plan_id else None
    item.offer_id = offer_id.strip() if offer_id else None
    item.status = "active" if active else "inactive"
    item.store_metadata = {
        **(item.store_metadata or {}),
        "managed_by": "owner_control",
        "updated_at": _now().isoformat(),
    }
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            409, "Store mapping conflicts with an existing mapping"
        ) from exc
    return {
        "id": item.id,
        "store": item.store,
        "product_id": item.product_id,
        "base_plan_id": item.base_plan_id,
        "offer_id": item.offer_id,
        "status": item.status,
        "plan_code": plan.code,
        "period_code": price.period_code,
    }


async def owner_set_store_mapping_status(
    session: AsyncSession, *, mapping_id: str, active: bool
) -> dict[str, Any]:
    item = await session.get(MobileStoreProduct, mapping_id)
    if item is None:
        raise HTTPException(404, "Mobile store mapping not found")
    item.status = "active" if active else "inactive"
    item.store_metadata = {
        **(item.store_metadata or {}),
        "managed_by": "owner_control",
        "updated_at": _now().isoformat(),
    }
    await session.commit()
    return {"id": item.id, "store": item.store, "status": item.status}
