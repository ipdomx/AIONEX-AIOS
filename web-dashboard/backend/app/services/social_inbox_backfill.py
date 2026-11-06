"""Periodic poll fallback for the P3 unified inbox (roadmap 3.6).

Webhooks are the primary path. When a delivery is missed (the webhook was not
yet subscribed, Meta gave up retrying, or the API was down), this poll reads
recent Page post comments, Instagram media comments and Messenger/Instagram
conversations for every OAuth-connected account that has the inbox
permissions, and stores them through the same idempotent ``ingest_items``
(unique Meta id per account), so nothing is stored or counted twice.

It runs inside ``social_publish_worker`` every ``SOCIAL_INBOX_POLL_SECONDS``.
A token error marks the account as needing reconnect; any other Graph error
skips the account until the next cycle.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import GrowthSocialAccount
from app.services import social_connectors as framework
from app.services import social_inbox as inbox
from app.services.social_connections import CONNECTED_VIA
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_inbox import InboxItem, MetaInboxClient
from app.services.social_meta_publisher import GraphPublishError

logger = get_logger(__name__)
ACCOUNTS_PER_CYCLE = 50
REQUIRED_TABLES = ("social_inbox_conversations", "social_inbox_messages")


class InboxBackfill:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        client: MetaInboxClient | None = None,
        interval_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_factory = session_factory
        self.client = client or MetaInboxClient()
        self.interval = float(interval_seconds or settings.SOCIAL_INBOX_POLL_SECONDS)
        self.monotonic = monotonic
        self.last_run: float | None = None
        self.polled_accounts = 0
        self.stored = 0
        self.errors = 0

    async def run_if_due(self) -> int:
        now = self.monotonic()
        if self.last_run is not None and now - self.last_run < self.interval:
            return 0
        self.last_run = now
        return await self.run_once()

    async def _accounts(self) -> list[GrowthSocialAccount]:
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(GrowthSocialAccount)
                    .where(
                        GrowthSocialAccount.connected_via == CONNECTED_VIA,
                        GrowthSocialAccount.provider.in_(inbox.PROVIDERS),
                        GrowthSocialAccount.status == "active",
                        GrowthSocialAccount.token_ciphertext.is_not(None),
                    )
                    .order_by(GrowthSocialAccount.id)
                    .limit(ACCOUNTS_PER_CYCLE)
                )
            ).all()
        return [row for row in rows if inbox.account_readiness(row)["state"] == "ready"]

    async def fetch(self, account: GrowthSocialAccount) -> list[InboxItem]:
        token = framework.open_token(account.token_ciphertext)
        if account.provider == "facebook":
            page_id = account.external_account_id
            items = await self.client.page_comments(page_id=page_id, token=token)
        else:
            page_id = str((account.provider_metadata or {}).get("linked_external_id") or "")
            items = await self.client.instagram_comments(
                ig_id=account.external_account_id, token=token
            )
        if page_id:
            items += await self.client.conversations(
                provider=account.provider,
                account_external_id=account.external_account_id,
                page_id=page_id,
                token=token,
            )
        return items

    async def run_once(self) -> int:
        stored_total = 0
        for snapshot in await self._accounts():
            try:
                items = await self.fetch(snapshot)
            except GraphPublishError as exc:
                self.errors += 1
                if exc.token_expired:
                    await self._mark_expired(snapshot.id)
                logger.warning(
                    "Social inbox poll skipped an account",
                    account_id=snapshot.id,
                    code=exc.code,
                )
                continue
            except SocialConnectorError as exc:
                self.errors += 1
                logger.warning(
                    "Social inbox poll skipped an account", account_id=snapshot.id, code=exc.code
                )
                continue
            async with self.session_factory() as session:
                account = await session.scalar(
                    select(GrowthSocialAccount).where(GrowthSocialAccount.id == snapshot.id)
                )
                if account is None or account.status != "active" or not account.token_ciphertext:
                    continue
                _matched, stored = await inbox.ingest_items(
                    session, items, source="poll", account=account
                )
                await session.commit()
            self.polled_accounts += 1
            stored_total += stored
        self.stored += stored_total
        return stored_total

    async def _mark_expired(self, account_id: str) -> None:
        async with self.session_factory() as session:
            account = await session.scalar(
                select(GrowthSocialAccount)
                .where(GrowthSocialAccount.id == account_id)
                .with_for_update()
            )
            if account is not None and account.status == "active":
                account.status = "expired"
                account.health_state = "invalid"
                account.health_reasons = ["account-reconnect-required"]
                account.last_health_at = datetime.now(UTC)
                account.version += 1
                await session.commit()
