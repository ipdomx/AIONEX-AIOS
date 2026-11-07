"""P6 synthetic load-test accounts: create, export, count and clean up.

Gate 6.1 needs thousands of authenticated users.  They are created through the
application's own ``auth_service.register`` path (organization, owner role,
permissions, Argon2 hash) and then flagged twice so they can never be confused
with customers:

* the e-mail is ``p6-<run>-<index>@synthetic.loadtest.invalid``; ``.invalid``
  is reserved by RFC 2606, so no message can ever be delivered to it; and
* an ``OwnerControlRecord`` in the ``synthetic_load_account`` domain records
  the run id, organization and creation time.

Each account gets one workspace and ``--projects-per-user`` projects created
with the same fields and owner membership as ``POST /projects`` but WITHOUT the
platform-owner "project started" notification, so seeding never spams the
owner's Telegram/e-mail channels.

Cleanup touches only rows that carry BOTH flags for the requested run: users
are soft-deleted with their auth version bumped (every token is revoked),
organizations are suspended and projects/workspaces are marked deleted.

Run inside the backend container, e.g.::

    python -m app.services.synthetic_load_accounts seed \
        --run-id p6-20261120t0900z --count 5000 --password-file /run/p6/password \
        --export /var/lib/aionex/backups/p6-accounts.jsonl
    python -m app.services.synthetic_load_accounts cleanup --run-id p6-20261120t0900z \
        --confirm-run-id p6-20261120t0900z

Without ``--execute`` both commands only report what they would do.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYNTHETIC_DOMAIN = "synthetic_load_account"
SYNTHETIC_EMAIL_SUFFIX = "@synthetic.loadtest.invalid"
RUN_ID_PATTERN = re.compile(r"p6-[0-9]{8}t[0-9]{4,6}z(?:-[a-z0-9]{1,12})?\Z")
MAX_ACCOUNTS = 6000
MAX_PROJECTS_PER_USER = 5
BATCH_SIZE = 50


class SyntheticAccountError(ValueError):
    """Raised when a request could touch anything that is not synthetic."""


def validate_run_id(run_id: str) -> str:
    value = run_id.strip().lower()
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise SyntheticAccountError(
            "run id must look like p6-YYYYMMDDtHHMMz (optional -suffix)"
        )
    return value


def synthetic_email(run_id: str, index: int) -> str:
    if not 0 <= index < MAX_ACCOUNTS:
        raise SyntheticAccountError("account index out of range")
    return f"{validate_run_id(run_id)}-{index:05d}{SYNTHETIC_EMAIL_SUFFIX}"


def is_synthetic_email(email: str, run_id: str) -> bool:
    run = validate_run_id(run_id)
    pattern = re.compile(re.escape(run) + r"-[0-9]{5}" + re.escape(SYNTHETIC_EMAIL_SUFFIX) + r"\Z")
    return pattern.fullmatch(email.strip().lower()) is not None


def read_private_password(path: str) -> str:
    """Read the shared synthetic password from an owner-only file."""
    target = Path(path)
    try:
        metadata = target.lstat()
    except OSError as exc:
        raise SyntheticAccountError("password file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SyntheticAccountError("password file must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SyntheticAccountError("password file must not be group/other readable")
    value = target.read_text(encoding="utf-8").strip()
    if len(value) < 16:
        raise SyntheticAccountError("synthetic password must be at least 16 characters")
    return value


@dataclass(frozen=True)
class SeedPlan:
    run_id: str
    count: int
    projects_per_user: int
    start_index: int = 0

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        if not 1 <= self.count <= MAX_ACCOUNTS:
            raise SyntheticAccountError(f"count must be between 1 and {MAX_ACCOUNTS}")
        if not 0 <= self.projects_per_user <= MAX_PROJECTS_PER_USER:
            raise SyntheticAccountError("projects per user out of range")
        if self.start_index < 0 or self.start_index + self.count > MAX_ACCOUNTS:
            raise SyntheticAccountError("index range out of bounds")

    def emails(self) -> list[str]:
        return [
            synthetic_email(self.run_id, index)
            for index in range(self.start_index, self.start_index + self.count)
        ]

    def describe(self) -> dict[str, Any]:
        emails = self.emails()
        return {
            "run_id": self.run_id,
            "accounts": self.count,
            "projects_per_user": self.projects_per_user,
            "projects_total": self.count * self.projects_per_user,
            "first_email": emails[0],
            "last_email": emails[-1],
            "marker_domain": SYNTHETIC_DOMAIN,
            "owner_notifications": False,
        }


def _now() -> datetime:
    return datetime.now(UTC)


async def _seed_one(session: Any, *, run_id: str, email: str, password: str, projects: int) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.auth import auth_service
    from app.db.models import OwnerControlRecord, Project, User, Workspace
    from app.services import work_management

    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        marker = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == SYNTHETIC_DOMAIN,
                OwnerControlRecord.resource_id == existing.id,
            )
        )
        if marker is None:
            raise SyntheticAccountError("an unflagged account already uses a synthetic address")
        return {"email": email, "user_id": existing.id, "run_id": run_id, "created": False}

    record = await auth_service.register(
        session,
        email,
        password,
        f"P6 Synthetic {email.split('@', 1)[0][-5:]}",
        organization_name=f"P6 Synthetic {run_id}",
    )
    workspace = Workspace(
        organization_id=record.organization_id,
        name="P6 Synthetic Workspace",
        slug="p6-synthetic",
        description="Synthetic load-test workspace (gate 6.1).",
        status="active",
    )
    session.add(workspace)
    await session.flush()
    for number in range(projects):
        project = Project(
            organization_id=record.organization_id,
            workspace_id=workspace.id,
            owner_id=record.id,
            name=f"P6 Synthetic Project {number + 1}",
            slug=f"p6-synthetic-project-{number + 1}",
            description="Synthetic load-test project (gate 6.1).",
            status="planning",
            priority="medium",
            risk="normal",
            progress=0,
            review_status="not_requested",
            version=1,
            tags=["p6-synthetic"],
        )
        session.add(project)
        await session.flush()
        await work_management.ensure_project_owner_membership(session, project)
    session.add(
        OwnerControlRecord(
            domain=SYNTHETIC_DOMAIN,
            resource_id=record.id,
            status="active",
            enabled=True,
            payload={
                "run_id": run_id,
                "organization_id": record.organization_id,
                "workspace_id": workspace.id,
                "projects": projects,
                "created_at": _now().isoformat(),
                "purpose": "p6-launch-gate-6.1-load-test",
            },
            version=1,
        )
    )
    await session.commit()
    return {"email": email, "user_id": record.id, "run_id": run_id, "created": True}


async def seed(plan: SeedPlan, password: str, export: Path | None) -> dict[str, Any]:
    from app.db.base import SessionLocal

    rows: list[dict[str, Any]] = []
    emails = plan.emails()
    for start in range(0, len(emails), BATCH_SIZE):
        async with SessionLocal() as session:
            for email in emails[start:start + BATCH_SIZE]:
                rows.append(
                    await _seed_one(
                        session,
                        run_id=plan.run_id,
                        email=email,
                        password=password,
                        projects=plan.projects_per_user,
                    )
                )
    if export is not None:
        write_export(export, rows)
    return {
        **plan.describe(),
        "created": sum(1 for row in rows if row["created"]),
        "already_present": sum(1 for row in rows if not row["created"]),
        "export": str(export) if export else None,
    }


def write_export(path: Path, rows: list[dict[str, Any]]) -> None:
    """Create-only, owner-only JSONL with e-mail + user id (never a password)."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps({"email": row["email"], "user_id": row["user_id"], "run_id": row["run_id"]}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


async def _flagged(session: Any, run_id: str) -> list[tuple[Any, Any]]:
    from sqlalchemy import select

    from app.db.models import OwnerControlRecord, User

    markers = (
        await session.execute(
            select(OwnerControlRecord).where(OwnerControlRecord.domain == SYNTHETIC_DOMAIN)
        )
    ).scalars().all()
    pairs: list[tuple[Any, Any]] = []
    for marker in markers:
        if not isinstance(marker.payload, dict) or marker.payload.get("run_id") != run_id:
            continue
        user = await session.get(User, marker.resource_id)
        if user is None or not is_synthetic_email(user.email, run_id):
            # Double-flag rule: never act on a marker whose user is not synthetic.
            continue
        pairs.append((marker, user))
    return pairs


async def count(run_id: str) -> dict[str, Any]:
    from app.db.base import SessionLocal

    async with SessionLocal() as session:
        pairs = await _flagged(session, run_id)
    return {
        "run_id": run_id,
        "flagged_accounts": len(pairs),
        "active": sum(1 for marker, user in pairs if user.deleted_at is None),
        "cleaned": sum(1 for marker, user in pairs if marker.status == "cleaned"),
    }


async def cleanup(run_id: str, *, execute: bool) -> dict[str, Any]:
    from sqlalchemy import update

    from app.db.base import SessionLocal
    from app.db.models import Organization, Project, Workspace

    cleaned = 0
    async with SessionLocal() as session:
        pairs = await _flagged(session, run_id)
        if execute:
            now = _now()
            for marker, user in pairs:
                if user.deleted_at is None:
                    user.deleted_at = now
                    user.status = "disabled"
                    user.auth_version = int(user.auth_version or 0) + 1
                organization_id = marker.payload.get("organization_id")
                if organization_id == user.organization_id:
                    await session.execute(
                        update(Project)
                        .where(Project.organization_id == organization_id)
                        .values(status="deleted")
                    )
                    await session.execute(
                        update(Workspace)
                        .where(Workspace.organization_id == organization_id)
                        .values(status="deleted")
                    )
                    await session.execute(
                        update(Organization)
                        .where(Organization.id == organization_id)
                        .values(status="suspended")
                    )
                marker.status = "cleaned"
                marker.enabled = False
                marker.payload = {**marker.payload, "cleaned_at": now.isoformat()}
                cleaned += 1
            await session.commit()
    return {
        "run_id": run_id,
        "flagged_accounts": len(pairs),
        "cleaned": cleaned,
        "executed": execute,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--run-id", required=True)
    seed_cmd.add_argument("--count", type=int, default=5000)
    seed_cmd.add_argument("--start-index", type=int, default=0)
    seed_cmd.add_argument("--projects-per-user", type=int, default=3)
    seed_cmd.add_argument("--password-file", required=True)
    seed_cmd.add_argument("--export", type=Path)
    seed_cmd.add_argument("--execute", action="store_true")
    count_cmd = sub.add_parser("count")
    count_cmd.add_argument("--run-id", required=True)
    clean_cmd = sub.add_parser("cleanup")
    clean_cmd.add_argument("--run-id", required=True)
    clean_cmd.add_argument("--confirm-run-id", required=True)
    clean_cmd.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_id = validate_run_id(args.run_id)
        if args.command == "seed":
            plan = SeedPlan(run_id, args.count, args.projects_per_user, args.start_index)
            password = read_private_password(args.password_file)
            if not args.execute:
                result: dict[str, Any] = {"dry_run": True, **plan.describe()}
            else:
                result = asyncio.run(seed(plan, password, args.export))
        elif args.command == "count":
            result = asyncio.run(count(run_id))
        else:
            if validate_run_id(args.confirm_run_id) != run_id:
                raise SyntheticAccountError("--confirm-run-id must repeat --run-id exactly")
            result = asyncio.run(cleanup(run_id, execute=args.execute))
    except SyntheticAccountError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
