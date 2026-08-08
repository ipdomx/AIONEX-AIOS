"""Native mobile subscription API and authenticated store-server callbacks."""
from __future__ import annotations
from typing import Any, Literal
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import UserRecord, require_permissions, require_super_owner
from app.db.base import get_db
from app.services import mobile_store_billing

router=APIRouter(); StoreName=Literal["app_store","google_play"]
class VerifyPurchaseRequest(BaseModel):
    store:StoreName
    product_record_id:str=Field(min_length=1,max_length=36)
    signed_transaction:str|None=Field(default=None,min_length=1)
    purchase_token:str|None=Field(default=None,min_length=1)
class AppStoreNotificationRequest(BaseModel): signedPayload:str=Field(min_length=20,max_length=262144)
class OwnerStoreMappingRequest(BaseModel):
    store: StoreName
    plan_code: str = Field(min_length=1, max_length=80)
    period_code: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=255)
    base_plan_id: str | None = Field(default=None, max_length=255)
    offer_id: str | None = Field(default=None, max_length=255)
    mapping_id: str | None = Field(default=None, max_length=36)
    active: bool = True
class OwnerStoreMappingStatusRequest(BaseModel):
    active: bool

@router.post("/notifications/app-store", include_in_schema=False)
async def app_store_notification(data:AppStoreNotificationRequest,session:AsyncSession=Depends(get_db)):
    return await mobile_store_billing.process_app_store_notification(session,data.signedPayload)

@router.post("/notifications/google-play", include_in_schema=False)
async def google_play_notification(request:Request,authorization:str|None=Header(default=None),session:AsyncSession=Depends(get_db)):
    await mobile_store_billing.verify_google_pubsub_token(authorization)
    envelope:dict[str,Any]=await request.json()
    return await mobile_store_billing.process_google_notification(session,envelope)

@router.get("/readiness")
async def readiness(actor:UserRecord=Depends(require_permissions("billing:read"))): return mobile_store_billing.store_readiness()
@router.get("/catalog/{store}")
async def catalogue(store:StoreName,actor:UserRecord=Depends(require_permissions("billing:read")),session:AsyncSession=Depends(get_db)): return await mobile_store_billing.catalogue(session,store)
@router.post("/verify")
async def verify_purchase(data:VerifyPurchaseRequest,actor:UserRecord=Depends(require_permissions("billing:write")),session:AsyncSession=Depends(get_db)):
    return await mobile_store_billing.submit_purchase_for_verification(session,actor=actor,store=data.store,product_record_id=data.product_record_id,signed_transaction=data.signed_transaction,purchase_token=data.purchase_token)
@router.post("/restore/{store}")
async def restore(store:StoreName,actor:UserRecord=Depends(require_permissions("billing:write"))): return {"store":store,"mode":"native_restore_then_server_verify","server_verification_required":True}
@router.post("/reconcile/{store}")
async def reconcile(store:StoreName,actor:UserRecord=Depends(require_permissions("billing:write")),session:AsyncSession=Depends(get_db)): return await mobile_store_billing.reconcile_user_store(session,actor=actor,store=store)
@router.get("/subscription")
async def subscription(actor:UserRecord=Depends(require_permissions("billing:read")),session:AsyncSession=Depends(get_db)): return await mobile_store_billing.subscription_status(session,actor=actor)


@router.get("/owner/overview")
async def owner_store_overview(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    return await mobile_store_billing.owner_store_overview(session)

@router.post("/owner/mappings")
async def owner_store_mapping_save(
    data: OwnerStoreMappingRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    return await mobile_store_billing.owner_upsert_store_mapping(
        session, store=data.store, plan_code=data.plan_code, period_code=data.period_code,
        product_id=data.product_id, base_plan_id=data.base_plan_id, offer_id=data.offer_id,
        mapping_id=data.mapping_id, active=data.active,
    )

@router.patch("/owner/mappings/{mapping_id}")
async def owner_store_mapping_status(
    mapping_id: str, data: OwnerStoreMappingStatusRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    return await mobile_store_billing.owner_set_store_mapping_status(
        session, mapping_id=mapping_id, active=data.active
    )
