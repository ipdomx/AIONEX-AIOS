"""Self-service account deletion (App Store 5.1.1(v), Google Play account deletion).

The person proves who they are again (password, plus an MFA code when MFA is
on). Their sign-in data is removed and their personal details are anonymised
at once, every session ends, and an account that was alone in its
organization takes the organization down with it. A web subscription is
cancelled at the provider first; a store subscription can only be cancelled
by the person in the store, so the answer says it is still running.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, hash_password, verify_password
from app.db.models import (
    AuditEvent,
    BillingSubscription,
    CommunicationEndpoint,
    ExternalIdentity,
    Organization,
    PasskeyCredential,
    Project,
    RefreshSession,
    User,
    UserMFA,
    Workspace,
)
from app.services import account_security, billing

STORE_PROVIDERS = frozenset({"app_store", "google_play"})
LIVE_SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due")
SUPER_OWNER_ROLES = frozenset({"super owner", "super_owner"})


def _now() -> datetime:
    return datetime.now(UTC)


async def delete_own_account(
    session: AsyncSession,
    actor: UserRecord,
    *,
    password: str,
    mfa_code: str | None,
) -> dict[str, Any]:
    user = await session.scalar(select(User).where(User.id == actor.id).with_for_update())
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    if actor.role.strip().lower() in SUPER_OWNER_ROLES:
        raise HTTPException(status_code=422, detail="Super Owner accounts cannot be deleted")
    if not await verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    mfa = await session.get(UserMFA, user.id)
    if mfa is not None and mfa.enabled:
        code = (mfa_code or "").strip()
        if not code or not await account_security._verify_mfa_code(session, user.id, code, consume_backup=True):
            raise HTTPException(status_code=400, detail={"code": "MFA_CODE_REQUIRED", "message": "A valid MFA code is required"})

    others = int(
        await session.scalar(
            select(func.count(User.id)).where(
                User.organization_id == user.organization_id,
                User.id != user.id,
                User.deleted_at.is_(None),
            )
        )
        or 0
    )
    if others and actor.role == "Owner":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACCOUNT_OWNER_HAS_MEMBERS",
                "message": "Transfer ownership or remove the other members before deleting this account",
            },
        )

    sole_member = others == 0
    subscription_cancelled = False
    store_subscription_active = False
    if sole_member:
        subscription = await session.scalar(
            select(BillingSubscription)
            .where(
                BillingSubscription.organization_id == user.organization_id,
                BillingSubscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
            .order_by(BillingSubscription.created_at.desc())
            .limit(1)
        )
        if subscription is not None:
            if subscription.provider in STORE_PROVIDERS:
                store_subscription_active = True
            else:
                # Ends now at the provider; a failure stops the deletion before anything changed.
                await billing.cancel_subscription(session, actor, immediately=True)
                subscription_cancelled = True

    now = _now()
    original_email = user.email
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.name = "Deleted user"
    user.avatar = None
    user.password_hash = await hash_password(secrets.token_urlsafe(48))
    user.status = "inactive"
    user.deleted_at = now
    user.auth_version = int(user.auth_version or 0) + 1

    await session.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.execute(delete(UserMFA).where(UserMFA.user_id == user.id))
    await session.execute(delete(PasskeyCredential).where(PasskeyCredential.user_id == user.id))
    await session.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id == user.id))
    await session.execute(
        update(CommunicationEndpoint)
        .where(CommunicationEndpoint.user_id == user.id)
        .values(status="deleted", address_ciphertext="", address_hash=f"deleted-{secrets.token_hex(16)}")
    )
    if sole_member:
        await session.execute(
            update(Project).where(Project.organization_id == user.organization_id).values(status="deleted")
        )
        await session.execute(
            update(Workspace).where(Workspace.organization_id == user.organization_id).values(status="deleted")
        )
        await session.execute(
            update(Organization).where(Organization.id == user.organization_id).values(status="suspended")
        )
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action="account.self_deleted",
            resource_type="user",
            resource_id=user.id,
            details={
                "sole_member": sole_member,
                "subscription_cancelled": subscription_cancelled,
                "store_subscription_active": store_subscription_active,
                # Keep only the domain: enough for support questions, not personal data.
                "email_domain": original_email.rsplit("@", 1)[-1],
            },
        )
    )
    await session.commit()
    return {
        "deleted": True,
        "subscription_cancelled": subscription_cancelled,
        "store_subscription_active": store_subscription_active,
    }
