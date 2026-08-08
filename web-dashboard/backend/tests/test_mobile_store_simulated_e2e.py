from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    BillingAccount,
    BillingPlan,
    BillingPrice,
    BillingSubscription,
    MobileStoreEvent,
    MobileStoreProduct,
    Organization,
    Role,
    User,
)
from app.services import mobile_store_billing as store


def _actor(user: User, organization: Organization) -> UserRecord:
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


async def _fixture(prefix: str):
    suffix=uuid4().hex[:10]
    async with SessionLocal() as session:
        org=Organization(name=f"Store Sim {suffix}", slug=f"store-sim-{suffix}", plan="free", status="active")
        session.add(org); await session.flush()
        role=Role(organization_id=org.id,name=f"Store Sim Owner {suffix}",status="active")
        session.add(role); await session.flush()
        user=User(organization_id=org.id,role_id=role.id,email=f"store-sim-{suffix}@example.com",name="Store Simulator",password_hash=pwd_context.hash("StoreSim!12345"),status="active")
        session.add(user)
        basic=BillingPlan(code=f"{prefix}-basic-{suffix}",name="Basic",status="active",default_currency="USD",limits={"projects":10},entitlements=["projects.core"],metering={},source_version=1,source_hash="a"*64)
        pro=BillingPlan(code=f"{prefix}-pro-{suffix}",name="Pro",status="active",default_currency="USD",limits={"projects":100},entitlements=["projects.core","studio.pro"],metering={},source_version=1,source_hash="b"*64)
        session.add_all([basic,pro]); await session.flush()
        basic_price=BillingPrice(plan_id=basic.id,period_code="monthly",months=1,amount_minor=990,currency="USD",enabled=True,provider="none")
        pro_price=BillingPrice(plan_id=pro.id,period_code="monthly",months=1,amount_minor=1990,currency="USD",enabled=True,provider="none")
        session.add_all([basic_price,pro_price]); await session.flush()
        apple_basic=MobileStoreProduct(plan_id=basic.id,price_id=basic_price.id,store="app_store",product_id=f"net.vipe.aionex.{suffix}.basic",status="active")
        apple_pro=MobileStoreProduct(plan_id=pro.id,price_id=pro_price.id,store="app_store",product_id=f"net.vipe.aionex.{suffix}.pro",status="active")
        google_basic=MobileStoreProduct(plan_id=basic.id,price_id=basic_price.id,store="google_play",product_id=f"aionex_{suffix}_basic",base_plan_id="monthly",status="active")
        google_pro=MobileStoreProduct(plan_id=pro.id,price_id=pro_price.id,store="google_play",product_id=f"aionex_{suffix}_pro",base_plan_id="monthly",status="active")
        session.add_all([apple_basic,apple_pro,google_basic,google_pro]); await session.commit()
        return org,user,basic,pro,apple_basic,apple_pro,google_basic,google_pro


async def _cleanup(org_id: str, plan_ids: list[str]):
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id==org_id))
        for plan_id in plan_ids:
            plan=await session.get(BillingPlan,plan_id)
            if plan: await session.delete(plan)
        await session.commit()


def _google_payload(product_id: str, state: str, expiry: datetime, *, auto=True, order="GPA.SIM.1"):
    return {
        "subscriptionState": state,
        "startTime": (datetime.now(UTC)-timedelta(days=1)).isoformat().replace("+00:00","Z"),
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "lineItems": [{
            "productId": product_id,
            "expiryTime": expiry.isoformat().replace("+00:00","Z"),
            "latestSuccessfulOrderId": order,
            "autoRenewingPlan": {"autoRenewEnabled": auto},
            "offerDetails": {"basePlanId":"monthly"},
        }],
    }


def _rtdn(message_id: str, token: str, notification_type: int=2):
    payload={"version":"1.0","packageName":"net.vipe.aionex","subscriptionNotification":{"version":"1.0","notificationType":notification_type,"purchaseToken":token}}
    return {"message":{"messageId":message_id,"data":base64.b64encode(json.dumps(payload).encode()).decode()}}


@pytest.mark.asyncio
async def test_simulated_google_play_purchase_renew_cancel_grace_hold_restore_expire_and_upgrade(monkeypatch):
    org,user,basic,pro,_,_,gbasic,gpro=await _fixture("g")
    actor=_actor(user,org); token="SIMULATED-GOOGLE-TOKEN"; now=datetime.now(UTC)
    state={"payload":_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_ACTIVE",now+timedelta(days=30),order="GPA.SIM.INIT")}
    async def fake_get(_token): return state["payload"]
    async def fake_ack(_token,_product): return True
    monkeypatch.setattr(store,"_google_get_subscription",fake_get)
    monkeypatch.setattr(store,"_google_acknowledge",fake_ack)
    try:
        async with SessionLocal() as session:
            result=await store.submit_purchase_for_verification(session,actor=actor,store="google_play",product_record_id=gbasic.id,purchase_token=token)
            assert result["verified"] is True and result["server_acknowledged"] is True
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.plan_id==basic.id and account.entitlements==["projects.core"]

        # Renewal extends access.
        state["payload"]=_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_ACTIVE",now+timedelta(days=60),order="GPA.SIM.RENEW")
        async with SessionLocal() as session:
            assert (await store.process_google_notification(session,_rtdn("g-renew",token,2)))["status"]=="processed"
            # replay protection
            assert (await store.process_google_notification(session,_rtdn("g-renew",token,2)))["status"]=="duplicate"

        # User cancels auto-renew, but paid access remains through future expiry.
        state["payload"]=_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_CANCELED",now+timedelta(days=60),auto=False,order="GPA.SIM.RENEW")
        async with SessionLocal() as session:
            await store.process_google_notification(session,_rtdn("g-cancel",token,3))
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            sub=await session.scalar(select(BillingSubscription).where(BillingSubscription.organization_id==org.id,BillingSubscription.provider=="google_play"))
            assert account.status=="active" and sub.cancel_at_period_end is True

        # Grace period remains entitled.
        state["payload"]=_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_IN_GRACE_PERIOD",now+timedelta(days=5),auto=True,order="GPA.SIM.GRACE")
        async with SessionLocal() as session:
            await store.process_google_notification(session,_rtdn("g-grace",token,6))
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="active" and account.plan_id==basic.id

        # Account hold removes entitlement when no other provider is active.
        state["payload"]=_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_ON_HOLD",now+timedelta(days=5),auto=True,order="GPA.SIM.HOLD")
        async with SessionLocal() as session:
            await store.process_google_notification(session,_rtdn("g-hold",token,5))
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="inactive" and account.entitlements==[]

        # Restore/reconciliation returns verified entitlement.
        state["payload"]=_google_payload(gbasic.product_id,"SUBSCRIPTION_STATE_ACTIVE",now+timedelta(days=30),auto=True,order="GPA.SIM.RESTORE")
        async with SessionLocal() as session:
            restored=await store.reconcile_user_store(session,actor=actor,store="google_play")
            assert restored["updated"]>=1 and restored["failed"]==0
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="active"

        # Upgrade to Pro using the same Play token and a new product mapping.
        state["payload"]=_google_payload(gpro.product_id,"SUBSCRIPTION_STATE_ACTIVE",now+timedelta(days=45),auto=True,order="GPA.SIM.UPGRADE")
        async with SessionLocal() as session:
            upgraded=await store.submit_purchase_for_verification(session,actor=actor,store="google_play",product_record_id=gpro.id,purchase_token=token)
            assert upgraded["verified"] is True
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.plan_id==pro.id and "studio.pro" in account.entitlements

        # Expiry finally removes access.
        state["payload"]=_google_payload(gpro.product_id,"SUBSCRIPTION_STATE_EXPIRED",now-timedelta(minutes=1),auto=False,order="GPA.SIM.UPGRADE")
        async with SessionLocal() as session:
            await store.process_google_notification(session,_rtdn("g-expire",token,13))
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="inactive" and account.entitlements==[]
    finally:
        await _cleanup(org.id,[basic.id,pro.id])


class FakeAppleVerifier:
    def __init__(self, product_basic: str, product_pro: str):
        self.product_basic=product_basic; self.product_pro=product_pro
        self.tx_product=product_basic; self.event="SUBSCRIBED"; self.expiry=datetime.now(UTC)+timedelta(days=30)
    def _tx(self):
        return SimpleNamespace(transactionId=f"A-{self.event}-{uuid4().hex[:6]}",originalTransactionId="A-ORIGINAL-SIM",productId=self.tx_product,purchaseDate=int((datetime.now(UTC)-timedelta(days=1)).timestamp()*1000),expiresDate=int(self.expiry.timestamp()*1000),revocationDate=int(datetime.now(UTC).timestamp()*1000) if self.event in {"REFUND","REVOKE"} else None,environment="Sandbox",rawTransactionReason="PURCHASE",webOrderLineItemId="A-WEB-SIM")
    def verify_and_decode_signed_transaction(self,_signed): return self._tx()
    def verify_and_decode_renewal_info(self,_signed):
        grace=int((datetime.now(UTC)+timedelta(days=2)).timestamp()*1000) if self.event=="DID_FAIL_TO_RENEW" else None
        return SimpleNamespace(rawAutoRenewStatus=0 if self.event in {"EXPIRED","REFUND","REVOKE"} else 1,gracePeriodExpiresDate=grace)
    def verify_and_decode_notification(self,_signed):
        data=SimpleNamespace(signedTransactionInfo="signed-tx",signedRenewalInfo="signed-renew")
        return SimpleNamespace(notificationUUID=f"apple-{self.event.lower()}-{uuid4().hex[:6]}",rawNotificationType=self.event,rawSubtype=None,data=data)


class FakeAppleClient:
    def __init__(self, verifier): self.verifier=verifier
    async def get_all_subscription_statuses(self,_oid):
        item=SimpleNamespace(signedTransactionInfo="signed-tx",signedRenewalInfo="signed-renew")
        return SimpleNamespace(data=[SimpleNamespace(lastTransactions=[item])])
    async def async_close(self): pass


@pytest.mark.asyncio
async def test_simulated_app_store_purchase_renew_retry_refund_restore_upgrade_downgrade_and_replay(monkeypatch):
    org,user,basic,pro,abasic,apro,_,_=await _fixture("a")
    actor=_actor(user,org); verifier=FakeAppleVerifier(abasic.product_id,apro.product_id)
    monkeypatch.setattr(store,"_apple_verifier",lambda: verifier)
    async def fake_client(): return FakeAppleClient(verifier)
    monkeypatch.setattr(store,"_apple_api_client",fake_client)
    try:
        async with SessionLocal() as session:
            result=await store.submit_purchase_for_verification(session,actor=actor,store="app_store",product_record_id=abasic.id,signed_transaction="SIMULATED-JWS")
            assert result["verified"] is True
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.plan_id==basic.id

        # Renewal.
        verifier.event="DID_RENEW"; verifier.expiry=datetime.now(UTC)+timedelta(days=60)
        async with SessionLocal() as session:
            response=await store.process_app_store_notification(session,"SIMULATED-NOTIFICATION-RENEW")
            assert response["status"]=="processed"
            event_id=response["event_id"]
            # Same Apple event id replay: freeze notification UUID for exact retry.
            original=verifier.verify_and_decode_notification
            fixed=original("x"); fixed.notificationUUID=event_id
            monkeypatch.setattr(verifier,"verify_and_decode_notification",lambda _x: fixed)
            assert (await store.process_app_store_notification(session,"SIMULATED-NOTIFICATION-RENEW"))["status"]=="duplicate"
            monkeypatch.setattr(verifier,"verify_and_decode_notification",original)

        # Billing retry with grace retains access.
        verifier.event="DID_FAIL_TO_RENEW"; verifier.expiry=datetime.now(UTC)-timedelta(minutes=1)
        async with SessionLocal() as session:
            await store.process_app_store_notification(session,"SIMULATED-NOTIFICATION-RETRY")
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="active"

        # Restore/reconcile an active renewal.
        verifier.event="DID_RENEW"; verifier.expiry=datetime.now(UTC)+timedelta(days=30)
        async with SessionLocal() as session:
            restored=await store.reconcile_user_store(session,actor=actor,store="app_store")
            assert restored["updated"]>=1 and restored["failed"]==0

        # Upgrade to Pro, then downgrade back to Basic, preserving a single account-level grant.
        verifier.tx_product=apro.product_id; verifier.event="DID_RENEW"; verifier.expiry=datetime.now(UTC)+timedelta(days=45)
        async with SessionLocal() as session:
            await store.submit_purchase_for_verification(session,actor=actor,store="app_store",product_record_id=apro.id,signed_transaction="SIMULATED-UPGRADE-JWS")
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.plan_id==pro.id and "studio.pro" in account.entitlements
        verifier.tx_product=abasic.product_id; verifier.expiry=datetime.now(UTC)+timedelta(days=60)
        async with SessionLocal() as session:
            await store.submit_purchase_for_verification(session,actor=actor,store="app_store",product_record_id=abasic.id,signed_transaction="SIMULATED-DOWNGRADE-JWS")
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.plan_id==basic.id and account.entitlements==["projects.core"]

        # Refund/revocation removes access when this is the last active subscription.
        verifier.event="REFUND"; verifier.tx_product=abasic.product_id; verifier.expiry=datetime.now(UTC)+timedelta(days=20)
        async with SessionLocal() as session:
            await store.process_app_store_notification(session,"SIMULATED-NOTIFICATION-REFUND")
            account=await session.scalar(select(BillingAccount).where(BillingAccount.organization_id==org.id))
            assert account.status=="inactive" and account.entitlements==[]
            events=(await session.scalars(select(MobileStoreEvent).where(MobileStoreEvent.store=="app_store"))).all()
            assert any(e.event_type=="REFUND" and e.status=="processed" for e in events)
    finally:
        await _cleanup(org.id,[basic.id,pro.id])
