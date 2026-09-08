from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import identity_media_access


def actor(*, status: str = "active"):
    return SimpleNamespace(
        id="user-identity-1",
        organization_id="org-identity-1",
        status=status,
    )


async def active_billing(*_args, **_kwargs):
    return {"account": SimpleNamespace(status="active"), "entitlements": []}


@pytest.mark.asyncio
async def test_fictional_identity_is_direct_when_runtime_is_ready(monkeypatch):
    monkeypatch.setattr(identity_media_access.billing, "billing_context", active_billing)

    async def no_override(*_args, **_kwargs):
        return None

    monkeypatch.setattr(identity_media_access, "_access_record", no_override)
    decision = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="talking_head",
        identity_basis="fictional_inspired",
        subject_reference="original-persona",
    )
    assert decision.allowed is True
    assert decision.owner_approval_required is False
    assert decision.reason == "fictional-direct"


@pytest.mark.asyncio
async def test_real_person_is_denied_until_owner_grants(monkeypatch):
    monkeypatch.setattr(identity_media_access.billing, "billing_context", active_billing)

    async def no_override(*_args, **_kwargs):
        return None

    monkeypatch.setattr(identity_media_access, "_access_record", no_override)
    decision = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="voice_clone",
        identity_basis="self",
        subject_reference="my-identity",
    )
    assert decision.allowed is False
    assert decision.owner_approval_required is True
    assert decision.reason == "owner-approval-required"


@pytest.mark.asyncio
async def test_owner_grant_is_scoped_to_basis_and_exact_subject(monkeypatch):
    monkeypatch.setattr(identity_media_access.billing, "billing_context", active_billing)

    async def granted(*_args, **_kwargs):
        return SimpleNamespace(
            enabled=True,
            version=7,
            payload={
                "allowed": True,
                "identity_bases": ["consented_person"],
                "subject_scope": "exact",
                "subject_reference": "subject-rights-ref-7",
            },
        )

    monkeypatch.setattr(identity_media_access, "_access_record", granted)
    accepted = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="lip_sync",
        identity_basis="consented_person",
        subject_reference="subject-rights-ref-7",
    )
    mismatched = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="lip_sync",
        identity_basis="consented_person",
        subject_reference="another-subject",
    )
    assert accepted.allowed is True
    assert accepted.reason == "owner-grant"
    assert mismatched.allowed is False
    assert mismatched.reason == "owner-grant-scope-mismatch"


@pytest.mark.asyncio
async def test_owner_deny_overrides_direct_fictional_mode(monkeypatch):
    monkeypatch.setattr(identity_media_access.billing, "billing_context", active_billing)

    async def denied(*_args, **_kwargs):
        return SimpleNamespace(
            enabled=True,
            version=2,
            payload={
                "allowed": False,
                "identity_bases": ["self"],
                "subject_scope": "any",
            },
        )

    monkeypatch.setattr(identity_media_access, "_access_record", denied)
    decision = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="avatar_generation",
        identity_basis="fictional_inspired",
        subject_reference="fictional-persona",
    )
    assert decision.allowed is False
    assert decision.reason == "owner-deny"


@pytest.mark.asyncio
async def test_public_figure_never_becomes_runtime_ready_from_owner_grant(monkeypatch):
    monkeypatch.setattr(identity_media_access.billing, "billing_context", active_billing)

    async def granted(*_args, **_kwargs):
        return SimpleNamespace(
            enabled=True,
            version=3,
            payload={
                "allowed": True,
                "identity_bases": ["licensed_public_figure"],
                "subject_scope": "any",
            },
        )

    monkeypatch.setattr(identity_media_access, "_access_record", granted)
    decision = await identity_media_access.effective_access(
        None,  # type: ignore[arg-type]
        actor(),
        operation="talking_head",
        identity_basis="licensed_public_figure",
        subject_reference="licensed-catalog-subject",
    )
    assert decision.allowed is False
    assert decision.runtime_ready is False
    assert decision.reason == "runtime-pending"
