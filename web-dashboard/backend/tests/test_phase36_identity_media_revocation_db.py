"""Real PostgreSQL regression for revocation across independent sessions.

The global backend conftest refuses production databases. Each case owns a unique
synthetic tenant and removes only that tenant plus its exact Owner control row.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import BillingAccount, Organization, OwnerControlRecord, User
from app.services import identity_media_access


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected_reason", [
    ("owner-revoke", "owner-deny"),
    ("owner-scope", "owner-grant-scope-mismatch"),
    ("user-suspend", "user-unavailable"),
    ("organization-suspend", "organization-inactive"),
    ("billing-suspend", "account-suspended"),
])
async def test_current_authority_overrides_cached_grant_across_sessions(monkeypatch, change, expected_reason):
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id, user_id, account_id, control_id = (str(uuid4()) for _ in range(4))
    grant = {
        "allowed": True,
        "identity_bases": ["self"],
        "subject_scope": "exact",
        "subject_reference": "synthetic-self-subject",
    }
    row = SimpleNamespace(
        id=str(uuid4()), organization_id=organization_id,
        requested_by_id=user_id, operation="voice_clone", identity_basis="self",
        subject_reference="synthetic-self-subject", project_id=None,
    )
    # Runtime checks must never mutate billing catalogs while a provider pull
    # waits on another request. Admission remains free to use billing_context.
    forbidden_billing = AsyncMock(side_effect=AssertionError("Runtime authorization must remain read-only"))
    monkeypatch.setattr(identity_media_access.billing, "billing_context", forbidden_billing)
    try:
        async with sessions() as setup:
            setup.add(Organization(
                id=organization_id, name="Identity revocation test",
                slug=f"identity-revoke-{organization_id}", plan="free", status="active",
            ))
            await setup.flush()
            setup.add(User(
                id=user_id, organization_id=organization_id,
                email=f"{user_id}@example.invalid", name="Synthetic test user",
                password_hash="test-only-not-a-login-hash", status="active",
            ))
            setup.add(BillingAccount(id=account_id, organization_id=organization_id, status="active"))
            setup.add(OwnerControlRecord(
                id=control_id, domain=identity_media_access.ACCESS_DOMAIN,
                resource_id=f"user:{user_id}:voice_clone", status="active",
                enabled=True, payload=grant, version=1,
            ))
            await setup.commit()

        async with sessions() as reader:
            # Retain strong references so the SQLAlchemy identity map really
            # contains the old authority when the second transaction commits.
            cached = [
                await reader.get(User, user_id),
                await reader.get(Organization, organization_id),
                await reader.get(BillingAccount, account_id),
                await reader.get(OwnerControlRecord, control_id),
            ]
            assert all(value is not None for value in cached)
            initial = await identity_media_access.execution_access(reader, row)
            assert initial.allowed is True
            assert initial.reason == "owner-grant"
            assert not reader.new and not reader.dirty and not reader.deleted

            async with sessions() as writer:
                if change == "owner-revoke":
                    await writer.execute(update(OwnerControlRecord).where(
                        OwnerControlRecord.id == control_id
                    ).values(payload={**grant, "allowed": False}, version=2))
                elif change == "owner-scope":
                    await writer.execute(update(OwnerControlRecord).where(
                        OwnerControlRecord.id == control_id
                    ).values(payload={**grant, "subject_reference": "another-subject"}, version=2))
                elif change == "user-suspend":
                    await writer.execute(update(User).where(User.id == user_id).values(status="suspended"))
                elif change == "organization-suspend":
                    await writer.execute(update(Organization).where(
                        Organization.id == organization_id
                    ).values(status="suspended"))
                else:
                    await writer.execute(update(BillingAccount).where(
                        BillingAccount.id == account_id
                    ).values(status="suspended"))
                await writer.commit()

            result = await identity_media_access.execution_access(reader, row)
            assert result.allowed is False
            assert result.reason == expected_reason
            assert not reader.new and not reader.dirty and not reader.deleted
            forbidden_billing.assert_not_awaited()
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(OwnerControlRecord).where(OwnerControlRecord.id == control_id))
            await cleanup.execute(delete(Organization).where(Organization.id == organization_id))
            await cleanup.commit()
        await engine.dispose()
