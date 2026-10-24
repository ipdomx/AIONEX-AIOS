"""Do not weaken role, org, auth-version or per-user lock while cutting SQL."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import conversation_governance as g


def actor(**override):
    payload = {
        "id": "synthetic-owner-000",
        "organization_id": "synthetic-org-000",
        "auth_version": 4,
        "permissions": ["projects:write"],
    }
    payload.update(override)
    return SimpleNamespace(**payload)


class FakeSession:
    def __init__(self, locked_user=None):
        self.queries = []
        self.locked_user = locked_user

    async def scalar(self, statement):
        sql = str(statement)
        self.queries.append(sql)
        if len(self.queries) > 1:
            raise AssertionError("redundant role/org fetch must not happen")
        assert "FOR UPDATE" in sql.upper()
        return self.locked_user


def test_readonly_auth_requires_fresh_record_but_no_redundant_db_trip(monkeypatch):
    real = actor()
    seen = []

    async def fresh(session, user_id, **kwargs):
        seen.append((session, user_id))
        return real

    monkeypatch.setattr(g.auth_service, "get_user_by_id", fresh)
    session = FakeSession()
    result = asyncio.run(g.current_actor(session, real))
    assert result is real
    assert seen == [(session, real.id)]
    assert session.queries == []


def test_locked_admission_still_selects_live_user_for_update(monkeypatch):
    real = actor()
    lock = actor()

    async def fresh(session, user_id, **kwargs):
        return real

    monkeypatch.setattr(g.auth_service, "get_user_by_id", fresh)
    session = FakeSession(locked_user=lock)
    assert asyncio.run(g.current_actor(session, real, lock=True)) is real
    assert len(session.queries) == 1
    assert "FOR UPDATE" in session.queries[0].upper()
    assert "users.deleted_at is null" in session.queries[0].lower()


@pytest.mark.parametrize("field,changed", [
    ("organization_id", "another-tenant"),
    ("auth_version", 5),
])
def test_stale_jwt_organization_or_auth_version_denied(monkeypatch,field,changed):
    supplied = actor()
    actual = actor(**{field: changed})

    async def fresh(session, user_id, **kwargs):
        return actual

    monkeypatch.setattr(g.auth_service, "get_user_by_id", fresh)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(g.current_actor(FakeSession(), supplied))
    assert exc.value.status_code == 403


def test_deleted_user_is_denied_403_without_dependent_sql(monkeypatch):
    real = actor()

    async def missing(session, user_id, **kwargs):
        raise HTTPException(status_code=404, detail="User not found")

    monkeypatch.setattr(g.auth_service, "get_user_by_id", missing)
    session = FakeSession()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(g.current_actor(session, real))
    assert exc.value.status_code == 403
    assert session.queries == []


def test_live_role_revocation_denied_by_fresh_auth(monkeypatch):
    real = actor()

    async def revoked(session, user_id, **kwargs):
        raise HTTPException(status_code=403, detail="Assigned role is suspended")

    monkeypatch.setattr(g.auth_service, "get_user_by_id", revoked)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(g.current_actor(FakeSession(), real))
    assert exc.value.status_code == 403


def test_live_permission_required_and_wildcard_allowed(monkeypatch):
    supplied = actor()
    actual = actor(permissions=[])

    async def fresh(session, user_id, **kwargs):
        return actual

    monkeypatch.setattr(g.auth_service, "get_user_by_id", fresh)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(g.current_actor(FakeSession(), supplied))
    assert exc.value.status_code == 403
    actual.permissions = ["*"]
    assert asyncio.run(g.current_actor(FakeSession(), supplied)) is actual


def test_locked_missing_user_and_changed_auth_version_fail_before_get_user(monkeypatch):
    real = actor()
    calls = []

    async def fresh(session, user_id, **kwargs):
        calls.append(user_id)
        return real

    monkeypatch.setattr(g.auth_service, "get_user_by_id", fresh)
    for bad in (None,actor(auth_version=8),actor(organization_id="other")):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(g.current_actor(FakeSession(locked_user=bad),real,lock=True))
        assert exc.value.status_code == 403
    assert calls == []


def test_fresh_organization_absence_is_not_accepted(monkeypatch):
    real=actor()

    async def missing_org(session,user_id, **kwargs):
        raise HTTPException(status_code=500,detail="User organization is missing")

    monkeypatch.setattr(g.auth_service,"get_user_by_id",missing_org)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(g.current_actor(FakeSession(),real))
    assert exc.value.status_code==500
