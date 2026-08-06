"""Tenant-scoped billing, checkout, wallet, license, and webhook APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    UserRecord,
    require_permissions,
    require_super_owner,
)
from app.db.base import get_db
from app.db.models import (
    BillingCoupon,
    BillingInvoice,
    BillingTransaction,
    BillingUsageRecord,
    BillingWalletEntry,
)
from app.services import billing

router = APIRouter()


class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=80)
    period_code: str = Field(min_length=1, max_length=80)
    coupon_code: str | None = Field(default=None, max_length=80)
    billing_country: str | None = Field(default=None, min_length=2, max_length=2)


class CancelSubscriptionRequest(BaseModel):
    immediately: bool = False


class CouponValidationRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    amount_minor: int = Field(gt=0, le=10_000_000_000)
    currency: str = Field(min_length=3, max_length=3)


class AccountUpdateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=80)
    seats: int | None = Field(default=None, ge=1, le=1_000_000)
    action: Literal["suspend", "restore"] | None = None


class CouponCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    discount_type: Literal["percent", "fixed"]
    percent_off: float | None = Field(default=None, gt=0, le=100)
    amount_off_minor: int | None = Field(default=None, gt=0, le=10_000_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    max_redemptions: int | None = Field(default=None, ge=1, le=100_000_000)
    expires_at: datetime | None = None


class TaxRateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    percentage: float = Field(ge=0, le=100)
    inclusive: bool = False


class WalletCreditRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=36)
    amount_minor: int = Field(gt=0, le=10_000_000_000)
    description: str = Field(min_length=1, max_length=500)


class UsageRecordRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=36)
    metric: str = Field(
        min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._:-]*$"
    )
    quantity: int = Field(gt=0, le=1_000_000_000_000)


class RefundRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=36)
    amount_minor: int = Field(gt=0, le=10_000_000_000)
    reason: str = Field(min_length=2, max_length=240)


class TransactionSettlementRequest(BaseModel):
    succeeded: bool
    external_reference: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)


class LicenseIssueRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=36)
    seats: int = Field(ge=1, le=1_000_000)
    expires_at: datetime | None = None


class ReconcileRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)


@router.get("/catalog/public")
async def public_catalog(session: AsyncSession = Depends(get_db)):
    result = await billing.sync_catalog(session)
    await session.commit()
    return result


@router.get("/providers/public")
async def public_provider_readiness():
    return {
        "environment": billing.settings.PAYMENTS_ENVIRONMENT,
        "providers": billing.provider_readiness(),
        "stores_card_data": False,
    }


@router.post("/webhooks/{provider}")
async def provider_webhook(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    payload = await billing.verify_webhook(provider, raw, request.headers)
    return await billing.process_webhook_event(session, provider, payload, raw)


@router.get("")
async def summary(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.billing_summary(session, actor)


@router.get("/invoices")
async def invoices(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    items = (
        await session.scalars(
            select(BillingInvoice)
            .where(BillingInvoice.organization_id == actor.organization_id)
            .order_by(BillingInvoice.created_at.desc())
            .limit(200)
        )
    ).all()
    return [billing.invoice_snapshot(item) for item in items]


@router.get("/transactions")
async def transactions(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    items = (
        await session.scalars(
            select(BillingTransaction)
            .where(BillingTransaction.organization_id == actor.organization_id)
            .order_by(BillingTransaction.created_at.desc())
            .limit(200)
        )
    ).all()
    return [billing.transaction_snapshot(item) for item in items]


@router.get("/usage")
async def usage(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    items = (
        await session.scalars(
            select(BillingUsageRecord)
            .where(BillingUsageRecord.organization_id == actor.organization_id)
            .order_by(BillingUsageRecord.period_start.desc(), BillingUsageRecord.metric)
            .limit(500)
        )
    ).all()
    return [billing.usage_snapshot(item) for item in items]


@router.get("/wallet")
async def wallet(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    record = await billing.ensure_wallet(session, actor.organization_id)
    entries = (
        await session.scalars(
            select(BillingWalletEntry)
            .where(BillingWalletEntry.wallet_id == record.id)
            .order_by(BillingWalletEntry.created_at.desc())
            .limit(200)
        )
    ).all()
    await session.commit()
    return {
        **billing.wallet_snapshot(record),
        "entries": [
            {
                "id": item.id,
                "type": item.entry_type,
                "amount_minor": item.amount_minor,
                "balance_after_minor": item.balance_after_minor,
                "description": item.description,
                "created_at": billing._as_utc(item.created_at).isoformat(),
            }
            for item in entries
        ],
    }


@router.get("/payment-methods")
async def payment_methods(
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.list_payment_methods(session, actor.organization_id)


@router.post("/payment-methods/{method_id}/default")
async def default_payment_method(
    method_id: str,
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.set_default_payment_method(session, actor, method_id)


@router.delete("/payment-methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    method_id: str,
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
):
    await billing.remove_payment_method(session, actor, method_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def checkout(
    data: CheckoutRequest,
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=12, max_length=160
    ),
):
    return await billing.create_checkout(
        session,
        actor,
        plan_code=data.plan_code,
        period_code=data.period_code,
        coupon_code=data.coupon_code,
        billing_country=data.billing_country,
        idempotency_key=idempotency_key,
    )


@router.post("/portal-session")
async def portal_session(
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.create_billing_portal_session(session, actor)


@router.post("/subscription/cancel")
async def cancel_subscription(
    data: CancelSubscriptionRequest,
    actor: UserRecord = Depends(require_permissions("billing:write")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.cancel_subscription(
        session, actor, immediately=data.immediately
    )


@router.post("/coupons/validate")
async def coupon_validation(
    data: CouponValidationRequest,
    actor: UserRecord = Depends(require_permissions("billing:read")),
    session: AsyncSession = Depends(get_db),
):
    return await billing.validate_coupon(
        session, data.code, data.amount_minor, data.currency
    )


@router.get("/owner/overview")
async def owner_billing_overview(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.owner_overview(session)


@router.patch("/owner/accounts/{organization_id}")
async def owner_account_update(
    organization_id: str,
    data: AccountUpdateRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    if data.plan_code is None and data.seats is None and data.action is None:
        raise HTTPException(
            status_code=422, detail="At least one billing account change is required"
        )
    return await billing.owner_update_account(
        session,
        actor,
        organization_id,
        plan_code=data.plan_code,
        seats=data.seats,
        action=data.action,
    )


@router.get("/owner/coupons")
async def owner_coupons(
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    del actor
    items = (
        await session.scalars(
            select(BillingCoupon).order_by(BillingCoupon.created_at.desc())
        )
    ).all()
    return [billing.coupon_snapshot(item) for item in items]


@router.post("/owner/coupons", status_code=status.HTTP_201_CREATED)
async def owner_coupon_create(
    data: CouponCreateRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.owner_create_coupon(
        session,
        actor,
        code=data.code,
        discount_type=data.discount_type,
        percent_off=data.percent_off,
        amount_off_minor=data.amount_off_minor,
        currency=data.currency,
        max_redemptions=data.max_redemptions,
        expires_at=data.expires_at,
    )


@router.post("/owner/taxes")
async def owner_tax_save(
    data: TaxRateRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.owner_upsert_tax(
        session,
        actor,
        code=data.code,
        country_code=data.country_code,
        percentage=data.percentage,
        inclusive=data.inclusive,
    )


@router.post("/owner/wallet/credit")
async def owner_wallet_credit(
    data: WalletCreditRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=12, max_length=160
    ),
):
    entry = await billing.post_wallet_entry(
        session,
        data.organization_id,
        amount_minor=data.amount_minor,
        idempotency_key=f"owner-credit:{idempotency_key}",
        entry_type="credit",
        description=data.description,
        reference_type="owner",
        reference_id=actor.id,
    )
    session.add(
        billing._audit(
            actor,
            "billing.wallet.credited",
            "billing_wallet_entry",
            entry.id,
            {
                "organization_id": data.organization_id,
                "amount_minor": data.amount_minor,
            },
        )
    )
    await session.commit()
    return {
        "entry_id": entry.id,
        "amount_minor": entry.amount_minor,
        "balance_after_minor": entry.balance_after_minor,
    }


@router.post("/owner/usage")
async def owner_usage_record(
    data: UsageRecordRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=12, max_length=160
    ),
):
    result = await billing.record_usage(
        session,
        data.organization_id,
        metric=data.metric,
        quantity=data.quantity,
        idempotency_key=idempotency_key,
    )
    session.add(
        billing._audit(
            actor,
            "billing.usage.recorded",
            "billing_usage",
            result.get("id"),
            {
                "organization_id": data.organization_id,
                "metric": data.metric,
                "quantity": data.quantity,
            },
        )
    )
    await session.commit()
    return result


@router.post("/owner/transactions/{transaction_id}/settle")
async def owner_transaction_settle(
    transaction_id: str,
    data: TransactionSettlementRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.owner_settle_transaction(
        session,
        actor,
        transaction_id,
        succeeded=data.succeeded,
        external_reference=data.external_reference,
        note=data.note,
    )


@router.post("/owner/refunds", status_code=status.HTTP_201_CREATED)
async def owner_refund_create(
    data: RefundRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=12, max_length=160
    ),
):
    return await billing.owner_refund(
        session,
        actor,
        data.transaction_id,
        amount_minor=data.amount_minor,
        reason=data.reason,
        idempotency_key=idempotency_key,
    )


@router.post("/owner/licenses", status_code=status.HTTP_201_CREATED)
async def owner_license_issue(
    data: LicenseIssueRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.issue_license(
        session,
        actor,
        data.organization_id,
        seats=data.seats,
        expires_at=data.expires_at,
    )


@router.post("/owner/licenses/{license_id}/revoke")
async def owner_license_revoke(
    license_id: str,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.revoke_license(session, actor, license_id)


@router.post("/owner/reconcile")
async def owner_reconcile(
    data: ReconcileRequest,
    actor: UserRecord = Depends(require_super_owner),
    session: AsyncSession = Depends(get_db),
):
    return await billing.reconcile(session, actor, data.provider)
