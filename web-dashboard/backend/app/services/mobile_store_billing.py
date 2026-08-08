"""Provider-neutral mobile store billing foundation.

This batch deliberately does not trust client assertions. Store verification adapters are
introduced in later batches; until then purchase verification fails closed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import MobileStoreProduct, MobileStorePurchase

StoreName = Literal["app_store", "google_play"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def store_readiness() -> dict[str, Any]:
    return {
        "app_store": {
            "configured": bool(
                settings.APP_STORE_BUNDLE_ID
                and settings.APP_STORE_ISSUER_ID
                and settings.APP_STORE_KEY_ID
                and settings.APP_STORE_PRIVATE_KEY
            ),
            "bundle_id": settings.APP_STORE_BUNDLE_ID,
            "verification": "server_required",
        },
        "google_play": {
            "configured": bool(
                settings.GOOGLE_PLAY_PACKAGE_NAME
                and settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON
            ),
            "package_name": settings.GOOGLE_PLAY_PACKAGE_NAME,
            "verification": "server_required",
        },
    }


async def catalogue(session: AsyncSession, store: StoreName) -> list[dict[str, Any]]:
    items = (
        await session.scalars(
            select(MobileStoreProduct)
            .where(MobileStoreProduct.store == store, MobileStoreProduct.status == "active")
            .order_by(MobileStoreProduct.created_at.asc())
        )
    ).all()
    return [
        {
            "id": item.id,
            "store": item.store,
            "product_id": item.product_id,
            "base_plan_id": item.base_plan_id,
            "offer_id": item.offer_id,
            "plan_id": item.plan_id,
            "price_id": item.price_id,
        }
        for item in items
    ]


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
        raise HTTPException(status_code=404, detail="Mobile store product not found")

    if store == "app_store" and not signed_transaction:
        raise HTTPException(status_code=400, detail="Signed App Store transaction is required")
    if store == "google_play" and not purchase_token:
        raise HTTPException(status_code=400, detail="Google Play purchase token is required")

    purchase = MobileStorePurchase(
        organization_id=actor.organization_id,
        user_id=actor.id,
        product_id=product.id,
        store=store,
        status="pending_verification",
        verified=False,
        purchase_token_hash=(
            hashlib.sha256(purchase_token.encode()).hexdigest() if purchase_token else None
        ),
        verification_metadata={
            "submitted_at": _now().isoformat(),
            "server_verification_required": True,
        },
    )
    session.add(purchase)
    await session.flush()

    # Fail closed until store-specific cryptographic/API verification lands in Batch 4.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Mobile store server verification adapter is not active yet",
    )


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
                "id": item.id,
                "store": item.store,
                "status": item.status,
                "verified": item.verified,
                "auto_renewing": item.auto_renewing,
                "expires_at": item.expires_at,
                "revoked_at": item.revoked_at,
            }
            for item in items
        ]
    }
