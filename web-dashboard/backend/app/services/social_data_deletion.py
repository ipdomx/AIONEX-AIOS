"""Meta deauthorize and data-deletion callbacks (App Review, roadmap 3.8).

Both callbacks carry a verified ``signed_request`` whose ``user_id`` is the
app-scoped Meta user id stored as ``SocialConnection.external_user_id``.

* deauthorize: the person removed the app. Every grant of that Meta user (in
  any organization) is revoked locally: the user token and every Page token
  derived from it are deleted and the accounts are marked revoked. Meta has
  already invalidated the tokens, so no Graph call is made.
* data deletion: the same revocation, plus every stored inbox conversation
  and message of those accounts is deleted and the Meta profile name and
  picture are removed from the connection.

Each callback is recorded with a random confirmation code; only a digest of
the Meta user id is kept. ``status`` answers the public status page.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    SocialConnection,
    SocialDataDeletionRequest,
)
from app.services import social_connectors as framework
from app.services import social_inbox as inbox
from app.services.social_connections import _clear_account
from app.services.social_connectors import SocialConnectorError

KINDS = ("deauthorize", "deletion")
STATUS_PAGE_PATH = "legal/data-deletion/"
DELETED_NAME = "Deleted Meta user"


def _now() -> datetime:
    return datetime.now(UTC)


def new_confirmation_code() -> str:
    return secrets.token_hex(8).upper()


def status_url(code: str, *, locale: str = "en") -> str:
    base = str(settings.SOCIAL_PORTAL_URL or "").rstrip("/")
    return f"{base}/{locale}/{STATUS_PAGE_PATH}?{urlencode({'code': code})}"


@dataclass(frozen=True)
class CallbackOutcome:
    confirmation_code: str
    url: str
    connections_revoked: int
    accounts_cleared: int
    conversations_deleted: int


async def handle_callback(
    session: AsyncSession, *, kind: str, meta_user_id: str
) -> CallbackOutcome:
    if kind not in KINDS:
        raise SocialConnectorError("callback-kind-invalid", status_code=400)
    now = _now()
    connections = (
        await session.scalars(
            select(SocialConnection)
            .where(
                SocialConnection.provider == "meta",
                SocialConnection.external_user_id == meta_user_id,
            )
            .with_for_update()
        )
    ).all()
    accounts_cleared = 0
    conversations_deleted = 0
    for connection in connections:
        accounts = (
            await session.scalars(
                select(GrowthSocialAccount)
                .where(GrowthSocialAccount.connection_id == connection.id)
                .with_for_update()
            )
        ).all()
        if kind == "deletion":
            conversations_deleted += await inbox.delete_account_inbox(
                session, [account.id for account in accounts]
            )
        for account in accounts:
            if account.token_ciphertext or account.status != "revoked":
                accounts_cleared += 1
            _clear_account(account)
            if kind == "deletion":
                account.avatar_url = None
        connection.token_ciphertext = None
        connection.token_expires_at = None
        connection.status = "revoked"
        connection.health_state = "revoked"
        connection.health_reasons = [
            "meta-data-deletion" if kind == "deletion" else "meta-deauthorized"
        ]
        connection.revoked_at = now
        connection.version += 1
        if kind == "deletion":
            connection.display_name = DELETED_NAME
            connection.avatar_url = None
            connection.granted_scopes = []
        session.add(
            AuditEvent(
                organization_id=connection.organization_id,
                user_id=connection.user_id,
                action=(
                    "social.meta.data_deleted" if kind == "deletion" else "social.meta.deauthorized"
                ),
                resource_type="social_connection",
                resource_id=connection.id,
                details={
                    "connector_framework": "p3",
                    "tokens_deleted": True,
                    "accounts_cleared": len(accounts),
                },
            )
        )
    code = new_confirmation_code()
    session.add(
        SocialDataDeletionRequest(
            provider="meta",
            kind=kind,
            confirmation_code=code,
            external_user_digest=framework.digest(f"meta:{meta_user_id}"),
            status="completed",
            connections_revoked=len(connections),
            accounts_cleared=accounts_cleared,
            conversations_deleted=conversations_deleted,
            requested_at=now,
            completed_at=_now(),
        )
    )
    await session.flush()
    return CallbackOutcome(
        confirmation_code=code,
        url=status_url(code),
        connections_revoked=len(connections),
        accounts_cleared=accounts_cleared,
        conversations_deleted=conversations_deleted,
    )


async def status(session: AsyncSession, code: str) -> dict[str, Any]:
    normalized = (code or "").strip().upper()
    if not (8 <= len(normalized) <= 32) or not normalized.isalnum():
        raise SocialConnectorError("confirmation-code-invalid", status_code=404)
    row = await session.scalar(
        select(SocialDataDeletionRequest).where(
            SocialDataDeletionRequest.confirmation_code == normalized
        )
    )
    if row is None:
        raise SocialConnectorError("confirmation-code-not-found", status_code=404)
    return {
        "confirmation_code": row.confirmation_code,
        "kind": row.kind,
        "status": row.status,
        "requested_at": row.requested_at,
        "completed_at": row.completed_at,
        "connections_revoked": row.connections_revoked,
        "accounts_cleared": row.accounts_cleared,
        "conversations_deleted": row.conversations_deleted,
    }
