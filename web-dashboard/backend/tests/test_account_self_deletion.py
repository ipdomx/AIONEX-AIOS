"""Self-service account deletion (App Store 5.1.1(v) / Google Play)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import auth_service
from app.db.base import SessionLocal
from app.db.models import AuditEvent, Organization, RefreshSession, User, UserMFA
from app.db.seed import seed
from app.services import account_deletion, account_security


async def _register(session, suffix: str, password: str):
    return await auth_service.register(
        session,
        email=f"self-delete-{suffix}@example.com",
        password=password,
        name="Self Delete",
        organization_name=f"Self Delete {suffix}",
    )


@pytest.mark.asyncio
async def test_wrong_password_changes_nothing() -> None:
    await seed()
    suffix = uuid4().hex
    password = f"Correct!{suffix}"
    async with SessionLocal() as session:
        actor = await _register(session, suffix, password)
        with pytest.raises(HTTPException) as refused:
            await account_deletion.delete_own_account(session, actor, password="wrong", mfa_code=None)
        assert refused.value.status_code == 400
        await session.rollback()
        stored = await session.get(User, actor.id)
        assert stored is not None and stored.deleted_at is None
        assert stored.email == f"self-delete-{suffix}@example.com"


@pytest.mark.asyncio
async def test_sole_member_is_anonymised_signed_out_and_takes_the_organization_down() -> None:
    await seed()
    suffix = uuid4().hex
    password = f"Correct!{suffix}"
    async with SessionLocal() as session:
        actor = await _register(session, suffix, password)
        pair = await auth_service.issue_pair(session, actor)
        assert pair["refresh_token"]

        result = await account_deletion.delete_own_account(session, actor, password=password, mfa_code=None)
        assert result == {"deleted": True, "subscription_cancelled": False, "store_subscription_active": False}

        stored = await session.get(User, actor.id)
        await session.refresh(stored)
        assert stored.deleted_at is not None
        assert stored.status == "inactive"
        assert stored.email == f"deleted-{actor.id}@deleted.invalid"
        assert stored.name == "Deleted user"
        assert stored.auth_version == actor.auth_version + 1
        sessions = (await session.scalars(select(RefreshSession).where(RefreshSession.user_id == actor.id))).all()
        assert sessions and all(item.revoked_at is not None for item in sessions)
        organization = await session.get(Organization, actor.organization_id)
        await session.refresh(organization)
        assert organization.status == "suspended"
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.user_id == actor.id, AuditEvent.action == "account.self_deleted")
        )
        assert audit is not None
        assert audit.details["email_domain"] == "example.com"
        assert f"self-delete-{suffix}" not in str(audit.details)

    # The old email can no longer sign in, and can register again.
    async with SessionLocal() as session:
        with pytest.raises(HTTPException):
            await auth_service.authenticate(session, f"self-delete-{suffix}@example.com", password)
        again = await _register(session, f"{suffix}", f"Another!{suffix}")
        assert again.id != actor.id


@pytest.mark.asyncio
async def test_mfa_code_is_required_when_mfa_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    await seed()
    suffix = uuid4().hex
    password = f"Correct!{suffix}"
    async with SessionLocal() as session:
        actor = await _register(session, suffix, password)
        session.add(UserMFA(user_id=actor.id, secret_ciphertext="x", backup_code_hashes=[], enabled=True))
        await session.commit()

        with pytest.raises(HTTPException) as missing:
            await account_deletion.delete_own_account(session, actor, password=password, mfa_code=None)
        assert missing.value.status_code == 400
        await session.rollback()

        async def accept(_session, user_id, code, *, consume_backup):
            return user_id == actor.id and code == "123456"

        monkeypatch.setattr(account_security, "_verify_mfa_code", accept)
        result = await account_deletion.delete_own_account(session, actor, password=password, mfa_code="123456")
        assert result["deleted"] is True
        assert await session.get(UserMFA, actor.id) is None


@pytest.mark.asyncio
async def test_an_owner_with_members_must_hand_over_first() -> None:
    await seed()
    suffix = uuid4().hex
    password = f"Correct!{suffix}"
    async with SessionLocal() as session:
        actor = await _register(session, suffix, password)
        owner = await session.get(User, actor.id)
        session.add(
            User(
                organization_id=owner.organization_id,
                role_id=owner.role_id,
                email=f"member-{suffix}@example.com",
                name="Member",
                password_hash="x",
            )
        )
        await session.commit()
        if actor.role != "Owner":
            pytest.skip("registration does not create an Owner in this seed")
        with pytest.raises(HTTPException) as blocked:
            await account_deletion.delete_own_account(session, actor, password=password, mfa_code=None)
        assert blocked.value.status_code == 409
        await session.rollback()
        stored = await session.get(User, actor.id)
        assert stored.deleted_at is None


def test_gateway_serves_account_deletion_only_on_the_exact_path() -> None:
    import re
    from pathlib import Path

    nginx = (Path(__file__).resolve().parents[2] / "docker" / "nginx.conf").read_text()
    public = nginx.split("# Public user portal origin.", 1)[0]
    marker = 'location ~ "^/api/v1/(?:auth/(?:logout|me|'
    line = public[public.index(marker):].split("\n", 1)[0]
    route = re.compile(line.split('"', 1)[1].rsplit('"', 1)[0])
    assert route.fullmatch("/api/v1/settings/account/delete")
    assert not route.fullmatch("/api/v1/settings/account")
    assert not route.fullmatch("/api/v1/settings/account/delete/now")
