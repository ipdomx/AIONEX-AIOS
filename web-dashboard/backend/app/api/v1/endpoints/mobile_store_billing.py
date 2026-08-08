"""Authenticated mobile-store subscription API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.services import mobile_store_billing

router = APIRouter()
StoreName = Literal["app_store", "google_play"]


class VerifyPurchaseRequest(BaseModel):
    store: StoreName
    product_record_id: str = Field(min_length=1, max_length=36)
    signed_transaction: str | None = Field(default=None, min_length=1)
    purchase_token: str | None = Field(default=None, min_length=1)


@router.get("/readiness")
async def readiness(
    actor: UserRecord = Depends(require_permissions("billing:read")),
):
    return mobile_store_billing.store_readiness()


@router.get("/catalog/{store}")
async def catalogue(
    store: StoreName,
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    return await mobile_store_billing.catalogue(session, store)


@router.post("/verify")
async def verify_purchase(
    data: VerifyPurchaseRequest,
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
):
    return await mobile_store_billing.submit_purchase_for_verification(
        session,
        actor=actor,
        store=data.store,
        product_record_id=data.product_record_id,
        signed_transaction=data.signed_transaction,
        purchase_token=data.purchase_token,
    )


@router.post("/restore/{store}")
async def restore(
    store: StoreName,
    actor: UserRecord = Depends(require_permissions("billing:write")),
):
    # Native clients restore/query store purchases, then submit each item to /verify.
    return {
        "store": store,
        "mode": "native_restore_then_server_verify",
        "server_verification_required": True,
    }


@router.get("/subscription")
async def subscription(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    return await mobile_store_billing.subscription_status(session, actor=actor)
