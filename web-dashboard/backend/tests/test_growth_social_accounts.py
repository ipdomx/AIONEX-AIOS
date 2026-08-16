from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    GrowthSocialAccount,
    GrowthSocialProviderCapability,
    Organization,
    Team,
    User,
)
from app.services import growth_social_accounts as social


def test_raw_credentials_are_rejected_and_external_refs_are_accepted() -> None:
    assert "ad_account" in social.ACCOUNT_KINDS
    with pytest.raises(
        social.GrowthSocialAccountError, match="credential-value-rejected"
    ):
        social.validate_credential_ref("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_secret")
    with pytest.raises(
        social.GrowthSocialAccountError, match="credential-value-rejected"
    ):
        social.validate_credential_ref("https://example.com/token")
    assert (
        social.validate_credential_ref(
            "file:/run/operator-secrets/social/facebook-page-1"
        )
        == "file:/run/operator-secrets/social/facebook-page-1"
    )


def test_sensitive_metadata_keys_are_rejected_recursively() -> None:
    with pytest.raises(
        social.GrowthSocialAccountError, match="sensitive-field-rejected"
    ):
        social._assert_no_sensitive_keys({"nested": {"access_token": "never-store-me"}})
    social._assert_no_sensitive_keys(
        {"page_category": "retail", "region": "AE", "nested": {"language": "ar"}}
    )


def test_public_account_shape_never_exposes_credential_reference() -> None:
    row = SimpleNamespace(
        id="account-1",
        provider="facebook",
        account_kind="page",
        external_account_id="page-1",
        display_name="Example",
        public_handle="example",
        workspace_id=None,
        team_id=None,
        status="active",
        health_state="healthy",
        health_reasons=[],
        token_expires_at=None,
        last_health_at=None,
        credential_ref="file:/run/operator-secrets/social/facebook-page-1",
        provider_metadata={},
        settings={},
        version=1,
    )
    payload = social._account_public(row)  # type: ignore[arg-type]
    assert payload["credential_configured"] is True
    assert "credential_ref" not in payload
    assert "operator-secrets" not in repr(payload)


@pytest.mark.parametrize(
    ("status", "has_ref", "days", "expected"),
    [
        ("paused", True, 30, "paused"),
        ("revoked", True, 30, "revoked"),
        ("rate_limited", True, 30, "rate_limited"),
        ("active", False, 30, "unknown"),
        ("active", True, -1, "expired"),
        ("active", True, 3, "expiring"),
        ("active", True, 30, "healthy"),
    ],
)
def test_health_simulator_is_deterministic(
    status: str, has_ref: bool, days: int, expected: str
) -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    state, reasons = social.simulate_health_payload(
        status=status,
        credential_configured=has_ref,
        token_expires_at=now + timedelta(days=days),
        now=now,
    )
    assert state == expected
    assert reasons


@pytest.mark.asyncio
async def test_durable_registry_supports_multiple_accounts_team_transfer_and_simulation(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs03-org-{suffix}"
    user_id = f"gs03-user-{suffix}"
    team_id = f"gs03-team-{suffix}"
    email = f"gs03-{suffix}@example.invalid"

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(social.growth_access, "effective_access", allow)
    actor = UserRecord(
        id=user_id,
        email=email,
        name="GS03 Test User",
        role="User",
        password_hash="not-used",
        organization_id=org_id,
        organization_name="GS03 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )

    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS03 Test",
                    slug=f"gs03-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    name="GS03 Test User",
                    password_hash="not-used",
                    status="active",
                    auth_version=1,
                )
            )
            await session.commit()
            session.add(
                Team(
                    id=team_id,
                    organization_id=org_id,
                    name="Growth Team",
                    slug=f"growth-{suffix}",
                    status="active",
                )
            )
            await session.commit()

            expiry = datetime.now(timezone.utc) + timedelta(days=3)
            first = await social.register_account(
                session,
                actor,
                {
                    "provider": "facebook",
                    "account_kind": "page",
                    "external_account_id": f"page-{suffix}-1",
                    "display_name": "Page One",
                    "credential_ref": "file:/run/operator-secrets/social/facebook-page-1",
                    "token_expires_at": expiry,
                    "provider_metadata": {"region": "AE"},
                },
            )
            second = await social.register_account(
                session,
                actor,
                {
                    "provider": "facebook",
                    "account_kind": "page",
                    "external_account_id": f"page-{suffix}-2",
                    "display_name": "Page Two",
                    "credential_ref": None,
                },
            )
            await session.commit()
            assert first.id != second.id

            accounts = await social.list_accounts(session, actor)
            assert len(accounts) == 2
            assert all("credential_ref" not in item for item in accounts)

            assigned = await social.assign_team(session, actor, first.id, team_id)
            assert assigned["team_id"] == team_id
            health = await social.simulate_health(session, actor, first.id)
            assert health["health_state"] == "expiring"
            assert health["live_provider_call"] is False

            paused = await social.pause_account(session, actor, first.id)
            assert paused["status"] == "paused"
            resumed = await social.resume_account(session, actor, first.id)
            assert resumed["status"] == "active"

            simulated = await social.simulate_capability(
                session, actor, first.id, "content.publish"
            )
            assert simulated["verification_state"] == "simulated"
            assert simulated["live_verified"] is False
            assert simulated["live_provider_call"] is False
            await session.commit()

            matrix_states = set(
                (
                    await session.scalars(
                        select(GrowthSocialProviderCapability.verification_state)
                    )
                ).all()
            )
            assert "verified" not in matrix_states
            assert "simulated" in matrix_states

            disconnected = await social.disconnect_account(session, actor, first.id)
            assert disconnected["status"] == "revoked"
            assert disconnected["credential_configured"] is False
            await session.commit()
            stored = await session.get(GrowthSocialAccount, first.id)
            assert stored is not None
            assert stored.credential_ref is None
        finally:
            await session.rollback()
            await session.execute(delete(GrowthSocialProviderCapability))
            org = await session.get(Organization, org_id)
            if org is not None:
                await session.delete(org)
            await session.commit()
