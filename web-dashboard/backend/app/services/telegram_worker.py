"""Optional, owner-allowlisted Telegram polling worker for AIOS operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    OwnerControlRecord,
    Project,
    ProjectExecution,
    uuid_str,
)
from sqlalchemy import func, select

logger = get_logger(__name__)
_TOKEN_PATTERN = re.compile(r"^[0-9]{5,16}:[A-Za-z0-9_-]{24,220}$")
_OFFSET_DOMAIN = "telegram-worker"
_OFFSET_RESOURCE = "update-offset"
_MAX_MESSAGE = 3900


class TelegramWorkerError(RuntimeError):
    """Sanitized Telegram worker failure."""


@dataclass(frozen=True, slots=True)
class TelegramInboundMessage:
    update_id: int
    user_id: int
    chat_id: int
    chat_type: str
    text: str


class TelegramBotAPI:
    def __init__(self, token: str, *, timeout_seconds: float = 35.0) -> None:
        if not _TOKEN_PATTERN.fullmatch(token):
            raise ValueError("Telegram bot token format is invalid")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": "AIONEX-AIOS-Telegram/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(f"{self._base_url}/{method}", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramWorkerError(f"Telegram connection failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise TelegramWorkerError(f"Telegram API returned HTTP {response.status_code}")
        try:
            decoded = response.json()
        except ValueError:
            raise TelegramWorkerError("Telegram API returned invalid JSON") from None
        if not isinstance(decoded, dict) or decoded.get("ok") is not True:
            raise TelegramWorkerError("Telegram API rejected the request")
        result = decoded.get("result")
        return {"result": result}

    async def get_updates(self, offset: int, timeout_seconds: int) -> list[dict[str, Any]]:
        response = await self._call(
            "getUpdates",
            {
                "offset": max(0, int(offset)),
                "timeout": int(timeout_seconds),
                "allowed_updates": ["message"],
            },
        )
        result = response["result"]
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._call(
            "sendMessage",
            {
                "chat_id": int(chat_id),
                "text": text[:_MAX_MESSAGE],
                "disable_web_page_preview": True,
            },
        )


class TelegramOperationsWorker:
    def __init__(self, api: TelegramBotAPI) -> None:
        self.api = api
        self.allowed_users = frozenset(int(value) for value in settings.AIOS_TELEGRAM_ALLOWED_USERS)
        self.health_path = Path(settings.AIOS_TELEGRAM_HEALTH_FILE)
        self.stop_event = asyncio.Event()
        self.errors = 0
        self.last_update_id: int | None = None

    async def run(self) -> None:
        offset = await self._load_offset()
        self._write_health("running", offset=offset)
        while not self.stop_event.is_set():
            try:
                updates = await self.api.get_updates(
                    offset,
                    settings.AIOS_TELEGRAM_LONG_POLL_SECONDS,
                )
                for raw in updates:
                    update_id = _safe_int(raw.get("update_id"))
                    if update_id is None:
                        continue
                    message = parse_inbound_message(raw)
                    if message is not None:
                        await self._handle(message)
                        self.last_update_id = message.update_id
                    offset = max(offset, update_id + 1)
                    await self._store_offset(offset)
                self._write_health("running", offset=offset)
            except TelegramWorkerError as exc:
                self.errors += 1
                logger.warning("Telegram polling failure", error=type(exc).__name__)
                self._write_health("degraded", offset=offset)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=5.0)
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
        self._write_health("stopped", offset=offset)

    async def stop(self) -> None:
        self.stop_event.set()

    async def _handle(self, message: TelegramInboundMessage) -> None:
        command = _command_name(message.text)
        if message.chat_type != "private":
            await self.api.send_message(message.chat_id, "استخدم بوت AIONEX داخل محادثة خاصة فقط.")
            await self._audit(message, command, "rejected", "non-private-chat")
            return

        if command == "whoami":
            await self.api.send_message(message.chat_id, f"Telegram user ID: {message.user_id}")
            await self._audit(message, command, "completed", None)
            return

        if message.user_id not in self.allowed_users:
            await self.api.send_message(
                message.chat_id,
                "غير مصرح لك باستخدام أوامر AIOS. استخدم /whoami لمعرفة رقم حسابك.",
            )
            await self._audit(message, command, "rejected", "not-allowlisted")
            return

        try:
            if command in {"start", "help", ""}:
                reply = (
                    "AIONEX AIOS\n"
                    "/status — حالة المشروعات والتنفيذ\n"
                    "/projects — أحدث المشروعات\n"
                    "/executions — أحدث دورات التنفيذ\n"
                    "/whoami — رقم حساب Telegram"
                )
            elif command == "status":
                reply = await self._status()
            elif command == "projects":
                reply = await self._projects()
            elif command == "executions":
                reply = await self._executions()
            else:
                reply = "أمر غير معروف. استخدم /help."
            await self.api.send_message(message.chat_id, reply)
            await self._audit(message, command, "completed", None)
        except Exception as exc:
            logger.exception("Telegram command failed", command=command)
            await self.api.send_message(message.chat_id, "تعذر تنفيذ الأمر بأمان. حاول لاحقًا.")
            await self._audit(message, command, "failed", type(exc).__name__)

    async def _status(self) -> str:
        async with SessionLocal() as session:
            project_total = int(await session.scalar(select(func.count(Project.id))) or 0)
            active_projects = int(
                await session.scalar(
                    select(func.count(Project.id)).where(Project.status.in_({"active", "planning"}))
                )
                or 0
            )
            queued = int(
                await session.scalar(
                    select(func.count(ProjectExecution.id)).where(
                        ProjectExecution.status.in_({"queued", "running"})
                    )
                )
                or 0
            )
            completed = int(
                await session.scalar(
                    select(func.count(ProjectExecution.id)).where(
                        ProjectExecution.status == "completed"
                    )
                )
                or 0
            )
        return (
            "حالة AIOS\n"
            f"المشروعات: {project_total}\n"
            f"النشطة/قيد التخطيط: {active_projects}\n"
            f"التنفيذ الجاري: {queued}\n"
            f"التنفيذ المكتمل: {completed}"
        )

    async def _projects(self) -> str:
        async with SessionLocal() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Project).order_by(Project.created_at.desc()).limit(8)
                    )
                ).all()
            )
        if not rows:
            return "لا توجد مشروعات حتى الآن."
        lines = ["أحدث المشروعات:"]
        lines.extend(
            f"• {item.name} — {item.status} — {item.progress}%" for item in rows
        )
        return "\n".join(lines)

    async def _executions(self) -> str:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(ProjectExecution, Project.name)
                    .join(Project, Project.id == ProjectExecution.project_id)
                    .order_by(ProjectExecution.created_at.desc())
                    .limit(8)
                )
            ).all()
        if not rows:
            return "لا توجد دورات تنفيذ حتى الآن."
        lines = ["أحدث دورات التنفيذ:"]
        for execution, project_name in rows:
            approval = "مقبول" if execution.approved else "يحتاج مراجعة"
            lines.append(
                f"• {project_name} — {execution.status}/{execution.stage} — {execution.progress}% — {approval}"
            )
        return "\n".join(lines)

    async def _load_offset(self) -> int:
        async with SessionLocal() as session:
            record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == _OFFSET_DOMAIN,
                    OwnerControlRecord.resource_id == _OFFSET_RESOURCE,
                )
            )
            return max(0, int((record.payload or {}).get("next_update_id", 0))) if record else 0

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
            if record is None:
                record = OwnerControlRecord(
                    id=uuid_str(),
                    domain=_OFFSET_DOMAIN,
                    resource_id=_OFFSET_RESOURCE,
                    status="active",
                    enabled=True,
                    payload={"next_update_id": int(offset)},
                    version=1,
                )
                session.add(record)
            else:
                record.payload = {"next_update_id": int(offset)}
                record.version += 1
            await session.commit()

    async def _audit(
        self,
        message: TelegramInboundMessage,
        command: str,
        status: str,
        reason: str | None,
    ) -> None:
        async with SessionLocal() as session:
            session.add(
                AuditEvent(
                    organization_id=None,
                    user_id=None,
                    action="telegram.command",
                    resource_type="telegram_update",
                    resource_id=str(message.update_id),
                    details={
                        "telegram_user_id": str(message.user_id),
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
            "allowed_users_configured": len(self.allowed_users),
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)


def load_bot_token(path: str | Path) -> str:
    token_path = Path(path)
    if not token_path.is_absolute() or not token_path.is_file() or token_path.is_symlink():
        raise ValueError("Telegram token file is missing or unsafe")
    file_stat = token_path.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode & 0o077:
        raise ValueError("Telegram token file must not be group/world accessible")
    if file_stat.st_uid not in {0, os.geteuid()}:
        raise ValueError("Telegram token file owner is invalid")
    token = token_path.read_text(encoding="utf-8").strip()
    if not _TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Telegram bot token format is invalid")
    return token


def parse_inbound_message(update: dict[str, Any]) -> TelegramInboundMessage | None:
    update_id = _safe_int(update.get("update_id"))
    message = update.get("message")
    if update_id is None or not isinstance(message, dict):
        return None
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    user_id = _safe_int(sender.get("id"))
    chat_id = _safe_int(chat.get("id"))
    text = message.get("text")
    if user_id is None or chat_id is None or not isinstance(text, str):
        return None
    return TelegramInboundMessage(
        update_id=update_id,
        user_id=user_id,
        chat_id=chat_id,
        chat_type=str(chat.get("type") or ""),
        text=text.strip()[:4096],
    )


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
    token = load_bot_token(settings.AIOS_TELEGRAM_BOT_TOKEN_FILE)
    api = TelegramBotAPI(token)
    worker = TelegramOperationsWorker(api)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop_event.set)
        except NotImplementedError:
            pass
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
        return healthcheck(settings.AIOS_TELEGRAM_HEALTH_FILE)
    setup_logging()
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
