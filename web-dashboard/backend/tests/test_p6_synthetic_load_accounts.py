"""P6 gate 6.1: synthetic load-test accounts are created, flagged and cleaned safely."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import auth_service, hash_password
from app.db.base import SessionLocal
from app.db.models import Organization, OwnerControlRecord, Project, Role, User
from app.db.seed import seed
from app.services import synthetic_load_accounts as synthetic


def test_run_id_and_email_contract() -> None:
    run = synthetic.validate_run_id("P6-20261120t0900z")
    assert run == "p6-20261120t0900z"
    assert synthetic.synthetic_email(run, 7) == "p6-20261120t0900z-00007@synthetic.loadtest.invalid"
    assert synthetic.is_synthetic_email("p6-20261120t0900z-00007@synthetic.loadtest.invalid", run)
    assert not synthetic.is_synthetic_email("p6-20261120t0900z-00007@gmail.com", run)
    assert not synthetic.is_synthetic_email("p6-20261121t0900z-00007@synthetic.loadtest.invalid", run)
    for bad in ("prod", "p6-2026", "p6-20261120t0900z-UPPER_"):
        with pytest.raises(synthetic.SyntheticAccountError):
            synthetic.validate_run_id(bad)


def test_seed_plan_bounds() -> None:
    plan = synthetic.SeedPlan("p6-20261120t0900z", 5000, 3)
    assert plan.describe()["projects_total"] == 15000
    assert plan.describe()["owner_notifications"] is False
    with pytest.raises(synthetic.SyntheticAccountError):
        synthetic.SeedPlan("p6-20261120t0900z", 7000, 3)
    with pytest.raises(synthetic.SyntheticAccountError):
        synthetic.SeedPlan("p6-20261120t0900z", 10, 9)


def test_password_file_must_be_private(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("synthetic-password-0123456789")
    secret.chmod(0o644)
    with pytest.raises(synthetic.SyntheticAccountError):
        synthetic.read_private_password(str(secret))
    secret.chmod(0o600)
    assert synthetic.read_private_password(str(secret)) == "synthetic-password-0123456789"


def test_dry_run_and_cleanup_confirmation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    secret = tmp_path / "pw"
    secret.write_text("synthetic-password-0123456789")
    secret.chmod(0o600)
    assert synthetic.main(["seed", "--run-id", "p6-20261120t0900z", "--count", "3",
                           "--password-file", str(secret)]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert synthetic.main(["cleanup", "--run-id", "p6-20261120t0900z",
                           "--confirm-run-id", "p6-20261121t0900z"]) == 2


@pytest.mark.asyncio
async def test_seed_count_cleanup_cycle_only_touches_flagged_synthetic_users(tmp_path: Path) -> None:
    await seed()
    run_id = f"p6-20261120t0900z-{uuid4().hex[:8]}"
    password = "synthetic-password-0123456789"
    export = tmp_path / "accounts.jsonl"
    result = await synthetic.seed(synthetic.SeedPlan(run_id, 2, 2), password, export)
    assert result["created"] == 2
    rows = [json.loads(line) for line in export.read_text().splitlines()]
    assert [row["email"] for row in rows] == [synthetic.synthetic_email(run_id, 0), synthetic.synthetic_email(run_id, 1)]
    assert all("password" not in row for row in rows)

    again = await synthetic.seed(synthetic.SeedPlan(run_id, 2, 2), password, None)
    assert again["created"] == 0 and again["already_present"] == 2

    # A marker that points at a NON-synthetic user must never be acted upon.
    decoy_email = f"p6-decoy-{uuid4().hex[:8]}@example.com"
    async with SessionLocal() as session:
        organization = await session.scalar(select(Organization).order_by(Organization.created_at))
        role = await session.scalar(select(Role).where(Role.name != "Super Owner").order_by(Role.created_at))
        assert organization is not None and role is not None
        decoy = User(organization_id=organization.id, role_id=role.id, email=decoy_email, name="Decoy",
                     password_hash=await hash_password(password), status="active")
        session.add(decoy)
        await session.flush()
        session.add(OwnerControlRecord(domain=synthetic.SYNTHETIC_DOMAIN, resource_id=decoy.id, status="active",
                                       enabled=True, payload={"run_id": run_id}, version=1))
        await session.commit()
        user = await auth_service.authenticate(session, rows[0]["email"], password)
        projects = (await session.scalars(select(Project).where(Project.organization_id == user.organization_id))).all()
        assert len(projects) == 2

    counted = await synthetic.count(run_id)
    assert counted == {"run_id": run_id, "flagged_accounts": 2, "active": 2, "cleaned": 0}
    assert (await synthetic.cleanup(run_id, execute=False))["cleaned"] == 0
    cleaned = await synthetic.cleanup(run_id, execute=True)
    assert cleaned["cleaned"] == 2

    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as denied:
            await auth_service.authenticate(session, rows[0]["email"], password)
        assert denied.value.status_code == 401
        survivor = await session.scalar(select(User).where(User.email == decoy_email))
        assert survivor is not None and survivor.deleted_at is None
        organization_status = await session.scalar(
            select(Organization.status).where(Organization.id == user.organization_id)
        )
        assert organization_status == "suspended"
    assert (await synthetic.count(run_id))["active"] == 0
