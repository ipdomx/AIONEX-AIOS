"""FR09 authenticated read path: preserve live permissions with fewer SQL trips."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services import conversation_governance as governance
from fastapi import HTTPException

from app.core.auth import UserRecord, auth_service
from app.db.models import Organization, Role, User


class _OneIdentityRow:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _LiveIdentitySession:
    def __init__(self, *, user, role, organization, permissions=("projects:read",)):
        self.user = user
        self.role = role
        self.organization = organization
        self.permissions = tuple(permissions)
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if len(self.statements) == 1:
            if self.user is None:
                return _OneIdentityRow(None)
            return _OneIdentityRow(
                (self.user, self.role, self.organization, list(self.permissions))
            )
        raise AssertionError("A live auth request issued excess SQL queries")

    async def get(self, _model, _key):
        raise AssertionError("Joined auth code must not requery live role or org")


def identity(**attrs):
    user = User(
        id="fr09-local-user",
        organization_id="fr09-local-org",
        role_id="fr09-local-role",
        name="Synthetic User",
        email="fr09-local-user@example.invalid",
        password_hash="non-production-synthetic-hash",
        status="active",
        auth_version=4,
    )
    role = Role(
        id="fr09-local-role",
        organization_id="fr09-local-org",
        name="Manager",
        status="active",
    )
    org = Organization(
        id="fr09-local-org",
        name="FR09 Isolated Organization",
        slug="fr09-local",
        plan="enterprise",
        status="active",
    )
    for key, value in attrs.items():
        target, field = key.split("__", 1)
        setattr({"user": user, "role": role, "org": org}[target], field, value)
    return user, role, org


class FastAuthenticatedReadPathTests(unittest.TestCase):
    def test_live_user_role_org_only_two_sql_roundtrips(self):
        u, r, o = identity()
        session = _LiveIdentitySession(
            user=u,
            role=r,
            organization=o,
            permissions=("projects:read", "projects:write"),
        )
        actor = asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertIsInstance(actor, UserRecord)
        self.assertEqual(actor.role, "Manager")
        self.assertEqual(actor.organization_plan, "enterprise")
        self.assertEqual(actor.auth_version, 4)
        self.assertEqual(actor.permissions, ["projects:read", "projects:write"])
        self.assertEqual(len(session.statements), 1)
        joined = session.statements[0].upper()
        self.assertIn("ARRAY_AGG", joined)
        self.assertIn("ROLE_PERMISSIONS.ROLE_ID = USERS.ROLE_ID", joined)
        self.assertNotIn("LEFT OUTER JOIN ROLE_PERMISSIONS", joined)
        self.assertIn("LEFT OUTER JOIN ROLES", joined)
        self.assertIn("LEFT OUTER JOIN ORGANIZATIONS", joined)
        self.assertIn("USERS.DELETED_AT IS NULL", joined)
        self.assertIn("ROLE_PERMISSIONS", session.statements[0].upper())
        self.assertIn("PERMISSIONS", session.statements[0].upper())

    def test_missing_identity_not_cached_or_accepted(self):
        session = _LiveIdentitySession(user=None, role=None, organization=None)
        with self.assertRaises(HTTPException) as result:
            asyncio.run(auth_service.get_user_by_id(session, "not-present"))
        self.assertEqual(result.exception.status_code, 404)
        self.assertEqual(len(session.statements), 1)

    def test_account_revocation_fails_closed_before_permissions(self):
        u, r, o = identity(user__status="suspended")
        session = _LiveIdentitySession(user=u, role=r, organization=o)
        with self.assertRaises(HTTPException) as result:
            asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(result.exception.status_code, 403)
        self.assertEqual(len(session.statements), 1)

    def test_disabled_role_fails_closed_before_permission_fetch(self):
        u, r, o = identity(role__status="suspended")
        session = _LiveIdentitySession(user=u, role=r, organization=o)
        with self.assertRaises(HTTPException) as result:
            asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(result.exception.status_code, 403)
        self.assertEqual(len(session.statements), 1)

    def test_disabled_organization_is_denied_with_no_role_expansion(self):
        u, r, o = identity(org__status="suspended")
        session = _LiveIdentitySession(user=u, role=r, organization=o)
        with self.assertRaises(HTTPException) as result:
            asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(result.exception.status_code, 403)
        self.assertEqual(len(session.statements), 1)

    def test_missing_organization_still_reports_invariant_breach(self):
        u, r, _ = identity()
        session = _LiveIdentitySession(user=u, role=r, organization=None)
        with self.assertRaises(HTTPException) as result:
            asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(result.exception.status_code, 500)

    def test_live_permissions_are_unique_single_identity_row(self):
        u, r, o = identity()
        permissions = ("projects:read", "projects:write", "security:view")
        session = _LiveIdentitySession(
            user=u, role=r, organization=o, permissions=permissions
        )
        actor = asyncio.run(auth_service.get_user_by_id(session, u.id, refresh_cached=True))
        self.assertEqual(actor.permissions, list(permissions))
        self.assertEqual(len(session.statements), 1)


    def test_empty_governed_thread_read_does_not_issue_a_clock_query(self):
        u, _, _ = identity()

        class EmptyResult:
            def all(self):
                return []

        class EmptySession:
            def __init__(self):
                self.statements = []

            async def execute(self, statement):
                self.statements.append(str(statement))
                return EmptyResult()

            async def scalar(self, statement):
                raise AssertionError("An empty inbox needs no extra clock query")

        async def actor_once(session, user):
            return user

        async def policy_once(session, user):
            return {"values": {"enabled": True}}

        session = EmptySession()
        with patch.object(governance, "current_actor", actor_once), patch.object(
            governance, "effective_policy", policy_once
        ):
            result = asyncio.run(governance.list_threads(
                session, UserRecord(
                    id=u.id, organization_id=u.organization_id, email=u.email,
                    name=u.name, password_hash="", role="Manager",
                    permissions=["projects:write"], organization_name="Synthetic Org",
                    organization_plan="enterprise",
                )
            ))
        self.assertEqual(result, [])
        self.assertEqual(len(session.statements), 1)
        self.assertIn("clock_timestamp()", session.statements[0])

    def test_unassigned_role_never_receives_permission(self):
        u, _, o = identity()
        u.role_id = None
        session = _LiveIdentitySession(user=u, role=None, organization=o)
        actor = asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(actor.role, "Unassigned")
        self.assertEqual(actor.permissions, [])
        self.assertEqual(len(session.statements), 1)

    def test_missing_role_reference_still_yields_unassigned(self):
        u, _, o = identity()
        session = _LiveIdentitySession(user=u, role=None, organization=o)
        actor = asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(actor.role, "Unassigned")
        self.assertEqual(actor.permissions, [])
        self.assertEqual(len(session.statements), 1)

    def test_organization_trial_status_and_online_user_remain_supported(self):
        u, r, o = identity(
            user__status="online", org__status="trial", org__plan="trial"
        )
        session = _LiveIdentitySession(user=u, role=r, organization=o)
        actor = asyncio.run(auth_service.get_user_by_id(session, u.id))
        self.assertEqual(actor.status, "online")
        self.assertEqual(actor.organization_plan, "trial")
        self.assertEqual(len(session.statements), 1)


if __name__ == "__main__":
    unittest.main()
