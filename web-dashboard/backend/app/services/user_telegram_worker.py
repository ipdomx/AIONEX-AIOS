"""Public-user Telegram bot with durable AIOS identity and entitlement checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, Notification, OwnerControlRecord, Project
from app.services import user_telegram_auth
from app.services.telegram_worker import (
    TelegramBotAPI,
    TelegramInboundMessage,
    TelegramWorkerError,
    load_bot_token,
    parse_inbound_message,
)

logger = get_logger(__name__)
_OFFSET_DOMAIN = "user-telegram-worker"
_OFFSET_RESOURCE = "update-offset"
_MAX_ITEMS = 5


class UserTelegramWorker:
    def __init__(self, api: TelegramBotAPI) -> None:
        self.api = api
        self.health_path = Path(settings.AIOS_USER_TELEGRAM_HEALTH_FILE)
        self.stop_event = asyncio.Event()
        self.errors = 0
        self.last_update_id: int | None = None

    async def run(self) -> None:
        offset = await self._load_offset()
        await self._record_bot_identity()
        self._write_health("running", offset=offset)
        while not self.stop_event.is_set():
            try:
                updates = await self.api.get_updates(
                    offset,
                    settings.AIOS_USER_TELEGRAM_LONG_POLL_SECONDS,
                )
                for update in updates:
                    update_id = _safe_int(update.get("update_id"))
                    if update_id is None:
                        continue
                    if update_id < offset:
                        continue
                    message = parse_inbound_message(update)
                    if message is not None:
                        await self._handle(message)
                    offset = update_id + 1
                    self.last_update_id = update_id
                    await self._store_offset(offset)
                self.errors = 0
                self._write_health("running", offset=offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                logger.warning(
                    "User Telegram polling iteration failed",
                    error_type=type(exc).__name__,
                    consecutive_errors=self.errors,
                )
                self._write_health("running", offset=offset)
                await asyncio.sleep(min(30, max(1, 2 ** min(self.errors, 5))))

    async def _record_bot_identity(self) -> None:
        result = await self.api._call("getMe", {})
        payload = result.get("result")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise TelegramWorkerError("Telegram getMe returned an invalid identity")
        async with SessionLocal() as session:
            await user_telegram_auth.record_bot_identity(session, payload)
            await session.commit()

    async def _handle(self, message: TelegramInboundMessage) -> None:
        command = _command_name(message.text)
        arguments = _command_arguments(message.text)
        if message.chat_type != "private":
            await self.api.send_message(
                message.chat_id,
                "For account security, AIONEX user commands work only in a private chat.",
            )
            await self._audit(message, command, "rejected", "non-private-chat")
            return

        if command in {"link"} or (command == "start" and arguments):
            code = arguments[0] if arguments else ""
            if len(arguments) != 1:
                await self.api.send_message(
                    message.chat_id,
                    "Generate a fresh Telegram link code from your AIONEX account, then send /link CODE.",
                )
                await self._audit(message, command, "rejected", "invalid-link-format")
                return
            async with SessionLocal() as session:
                try:
                    actor = await user_telegram_auth.consume_link_challenge(
                        session,
                        telegram_user_id=message.user_id,
                        chat_id=message.chat_id,
                        code=code,
                    )
                    await session.commit()
                except user_telegram_auth.UserTelegramAuthError as exc:
                    await session.rollback()
                    await self.api.send_message(
                        message.chat_id,
                        "This link code is invalid, expired, already used, or cannot be linked to this Telegram account.",
                    )
                    await self._audit(message, command, "rejected", exc.code)
                    return
            await self.api.send_message(
                message.chat_id,
                f"Linked securely to AIONEX account: {actor.name}. Use /help to see commands available to your current account.",
            )
            await self._audit(
                message,
                command,
                "completed",
                None,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            return

        try:
            async with SessionLocal() as session:
                actor, context = await user_telegram_auth.resolve_linked_user(
                    session,
                    telegram_user_id=message.user_id,
                    chat_id=message.chat_id,
                )
                if command in {"start", "help", ""}:
                    reply = self._help(actor, context)
                elif command == "me":
                    reply = self._me(actor, context)
                elif command == "plan":
                    self._require_permission(actor.permissions, "billing:read")
                    reply = self._plan(context)
                elif command == "usage":
                    self._require_permission(actor.permissions, "billing:read")
                    reply = self._usage(context)
                elif command == "projects":
                    self._require_permission(actor.permissions, "projects:read")
                    reply = await self._projects(session, actor.organization_id)
                elif command == "notifications":
                    self._require_permission(actor.permissions, "notifications:read")
                    reply = await self._notifications(
                        session, actor.organization_id, actor.id
                    )
                elif command in {"capabilities", "permissions"}:
                    reply = self._capabilities(actor, context)
                elif command in {"unlink", "logout"}:
                    await user_telegram_auth.revoke_link(session, actor)
                    await session.commit()
                    await self.api.send_message(
                        message.chat_id,
                        "Telegram was unlinked from your AIONEX account. Generate a new code in the portal to link again.",
                    )
                    await self._audit(
                        message,
                        command,
                        "completed",
                        None,
                        actor_id=actor.id,
                        organization_id=actor.organization_id,
                    )
                    return
                else:
                    await self.api.send_message(
                        message.chat_id,
                        "Unknown or unavailable command. Use /help to see commands allowed for your current account.",
                    )
                    await self._audit(
                        message,
                        command,
                        "rejected",
                        "unknown-command",
                        actor_id=actor.id,
                        organization_id=actor.organization_id,
                    )
                    return
                await session.commit()
        except user_telegram_auth.UserTelegramAuthError as exc:
            await self.api.send_message(message.chat_id, self._link_error(exc.code))
            await self._audit(message, command, "rejected", exc.code)
            return
        except PermissionError:
            await self.api.send_message(
                message.chat_id,
                "This command is not available for your current role or plan. Your Telegram access follows the same AIOS permissions as the portal.",
            )
            await self._audit(message, command, "rejected", "permission-denied")
            return
        except Exception as exc:
            logger.warning(
                "User Telegram command failed",
                command=command or "message",
                error_type=type(exc).__name__,
            )
            await self.api.send_message(
                message.chat_id,
                "The command could not be completed safely. Please try again later.",
            )
            await self._audit(message, command, "failed", type(exc).__name__)
            return

        await self.api.send_message(message.chat_id, reply)
        await self._audit(
            message,
            command,
            "completed",
            None,
            actor_id=actor.id,
            organization_id=actor.organization_id,
        )

    @staticmethod
    def _require_permission(granted: list[str], required: str) -> None:
        if "*" not in granted and required not in granted:
            raise PermissionError(required)

    @staticmethod
    def _plan_name(context: dict[str, Any]) -> str:
        plan = context.get("plan")
        return str(
            getattr(plan, "name", None) or getattr(plan, "code", None) or "Current plan"
        )

    def _help(self, actor, context: dict[str, Any]) -> str:
        commands = [
            "/me — account, role and plan",
            "/capabilities — commands allowed by your current account",
        ]
        granted = set(actor.permissions)
        if "*" in granted or "billing:read" in granted:
            commands.extend(
                ["/plan — subscription and plan", "/usage — current usage and limits"]
            )
        if "*" in granted or "projects:read" in granted:
            commands.append("/projects — latest projects")
        if "*" in granted or "notifications:read" in granted:
            commands.append("/notifications — latest unread notifications")
        commands.append("/unlink — remove this Telegram link")
        return (
            "AIONEX User Bot\nPlan: "
            + self._plan_name(context)
            + "\n\n"
            + "\n".join(commands)
        )

    def _me(self, actor, context: dict[str, Any]) -> str:
        account = context["account"]
        return (
            f"AIONEX account\nName: {actor.name}\nRole: {actor.role}\n"
            f"Plan: {self._plan_name(context)}\nAccount status: {account.status}"
        )

    def _plan(self, context: dict[str, Any]) -> str:
        account = context["account"]
        subscription = context.get("subscription")
        status = getattr(subscription, "status", None) or account.status
        return f"Plan: {self._plan_name(context)}\nSubscription: {status}\nAccess: {account.status}"

    def _usage(self, context: dict[str, Any]) -> str:
        usage = dict(context.get("usage") or {})
        limits = dict(context.get("limits") or {})
        lines = [f"Usage — {self._plan_name(context)}"]
        for key in ("projects", "workspaces", "seats"):
            used = usage.get(key)
            limit = limits.get(key)
            if used is None:
                continue
            lines.append(
                f"{key}: {used}" + (f" / {limit}" if limit is not None else "")
            )
        return "\n".join(lines)

    async def _projects(self, session, organization_id: str) -> str:
        rows = list(
            (
                await session.scalars(
                    select(Project)
                    .where(
                        Project.organization_id == organization_id,
                        Project.status != "deleted",
                    )
                    .order_by(Project.updated_at.desc())
                    .limit(_MAX_ITEMS)
                )
            ).all()
        )
        if not rows:
            return "No active projects are available to your account."
        return "Latest projects\n" + "\n".join(
            f"• {row.name} — {row.status} — {row.progress}%" for row in rows
        )

    async def _notifications(self, session, organization_id: str, user_id: str) -> str:
        rows = list(
            (
                await session.scalars(
                    select(Notification)
                    .where(
                        Notification.organization_id == organization_id,
                        Notification.recipient_id == user_id,
                        Notification.read_at.is_(None),
                        Notification.archived_at.is_(None),
                    )
                    .order_by(Notification.created_at.desc())
                    .limit(_MAX_ITEMS)
                )
            ).all()
        )
        if not rows:
            return "You have no unread notifications."
        return "Unread notifications\n" + "\n".join(
            f"• {row.title}: {row.message[:240]}" for row in rows
        )

    def _capabilities(self, actor, context: dict[str, Any]) -> str:
        granted = set(actor.permissions)
        available = ["me", "capabilities", "unlink"]
        if "*" in granted or "billing:read" in granted:
            available.extend(["plan", "usage"])
        if "*" in granted or "projects:read" in granted:
            available.append("projects")
        if "*" in granted or "notifications:read" in granted:
            available.append("notifications")
        entitlements = sorted(str(item) for item in (context.get("entitlements") or []))
        entitlement_text = ", ".join(entitlements) if entitlements else "none"
        return (
            f"Plan: {self._plan_name(context)}\nRole: {actor.role}\n"
            f"Plan entitlements: {entitlement_text}\n"
            "Available bot capabilities: " + ", ".join(sorted(available))
        )

    @staticmethod
    def _link_error(code: str) -> str:
        if code in {"relink-required", "account-session-changed"}:
            return "Your AIONEX security state changed. Generate a new Telegram link code from the portal."
        if code == "billing-access-suspended":
            return "Your current AIONEX plan/account is not active. Telegram access is paused until account access is restored."
        if code == "owner-bot-required":
            return "The Super Owner account must use the protected Owner Telegram bot."
        return "This Telegram account is not linked to an active AIONEX user. Generate a link code from your signed-in AIONEX portal."

    async def _load_offset(self) -> int:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == _OFFSET_DOMAIN,
                    OwnerControlRecord.resource_id == _OFFSET_RESOURCE,
                )
            )
            if record is None:
                return 0
            try:
                return max(0, int((record.payload or {}).get("next_update_id") or 0))
            except (TypeError, ValueError):
                return 0

    async def _store_offset(self, offset: int) -> None:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == _OFFSET_DOMAIN,
                    OwnerControlRecord.resource_id == _OFFSET_RESOURCE,
                )
                .with_for_update()
            )
            payload = {
                "next_update_id": int(offset),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            if record is None:
                session.add(
                    OwnerControlRecord(
                        domain=_OFFSET_DOMAIN,
                        resource_id=_OFFSET_RESOURCE,
                        status="active",
                        enabled=True,
                        payload=payload,
                        version=1,
                    )
                )
            else:
                record.status = "active"
                record.enabled = True
                record.payload = payload
                record.version += 1
            await session.commit()

    async def _audit(
        self,
        message: TelegramInboundMessage,
        command: str,
        status: str,
        reason: str | None,
        *,
        actor_id: str | None = None,
        organization_id: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            session.add(
                AuditEvent(
                    organization_id=organization_id,
                    user_id=actor_id,
                    action="telegram.user_command",
                    resource_type="telegram_update",
                    resource_id=str(message.update_id),
                    details={
                        "telegram_user_hash": __import__("hashlib")
                        .sha256(str(message.user_id).encode())
                        .hexdigest(),
                        "command": command or "message",
                        "status": status,
                        "reason": reason,
                    },
                )
            )
            await session.commit()

    def _write_health(self, status: str, *, offset: int) -> None:
        payload = {
            "status": status,
            "checked_at": datetime.now(UTC).isoformat(),
            "checked_at_epoch": time.time(),
            "next_update_id": int(offset),
            "last_update_id": self.last_update_id,
            "errors": self.errors,
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _command_name(text: str) -> str:
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    if not first.startswith("/"):
        return ""
    return first[1:].split("@", 1)[0].lower()


def _command_arguments(text: str) -> tuple[str, ...]:
    parts = text.strip().split()
    return tuple(parts[1:]) if len(parts) > 1 else ()


def healthcheck(path: str | Path, *, maximum_age_seconds: float = 120.0) -> int:
    health_path = Path(path)
    try:
        payload = json.loads(health_path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        healthy = payload.get("status") == "running" and 0 <= age <= maximum_age_seconds
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        healthy = False
    return 0 if healthy else 1


async def async_main() -> int:
    token = load_bot_token(settings.AIOS_USER_TELEGRAM_BOT_TOKEN_FILE)
    api = TelegramBotAPI(token)
    worker = UserTelegramWorker(api)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            continue
    try:
        await worker.run()
    finally:
        await api.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck(settings.AIOS_USER_TELEGRAM_HEALTH_FILE)
    setup_logging()
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
