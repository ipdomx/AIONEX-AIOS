"""Real PostgreSQL contract for top-plan Security Lab entitlement and usage limits.

Every case runs in a private random schema of an explicitly test-named database
and drives the real router, entitlement queries, billing rows and policy record.
Scan admission maintenance state is opened in-process; no scanner, resolver or
website is contacted (targets are literal public IPs and scans are only queued).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1.endpoints import security_lab
from app.core.auth import UserRecord, current_user
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import (
    AuditEvent,
    BillingAccount,
    BillingPlan,
    BillingPrice,
    BillingSubscription,
    Organization,
    OwnerControlRecord,
    Role,
    SecurityAccessGrant,
    SecurityFinding,
    SecurityScan,
    SecurityTarget,
    User,
)
from app.services import security_fabric, security_scanning
from app.services.free_tier import require_non_free_user

PREFIX = "/api/v1/security-lab"


def _required_tables():
    tables = {
        model.__table__
        for model in (
            AuditEvent, BillingAccount, BillingPlan, BillingPrice, BillingSubscription,
            Organization, OwnerControlRecord, Role, SecurityAccessGrant, SecurityFinding,
            SecurityScan, SecurityTarget, User,
        )
    }
    while True:
        expanded = tables | {key.column.table for table in tables for key in table.foreign_keys}
        if expanded == tables:
            return list(tables)
        tables = expanded


@pytest_asyncio.fixture
async def subscriber_case(monkeypatch):
    url = make_url(settings.DATABASE_URL)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("subscription entitlement contracts require PostgreSQL/asyncpg")
    if re.search(
        r"(?:^|[_-])(test|pytest|ci|smoke|disposable)(?:$|[_-])", (url.database or "").lower()
    ) is None:
        raise RuntimeError("subscription entitlement tests require an isolated test database")
    schema = f"p1_security_{uuid4().hex}"
    administration = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_id, user_id = str(uuid4()), str(uuid4())
    case = SimpleNamespace(
        sessions=sessions,
        actor=UserRecord(
            id=user_id, email=f"subscriber-{user_id}@example.test", name="Subscriber",
            role="Owner", password_hash="unused-synthetic-hash", organization_id=org_id,
            organization_name="Subscriber Organization", organization_plan="business",
            permissions=[],
        ),
        target_id=str(uuid4()),
        plans={},
    )
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=_required_tables())
            )
        async with sessions() as session:
            session.add(Organization(
                id=org_id, name="Subscriber Organization", slug=f"sub-{org_id}",
                plan="business", status="active",
            ))
            await session.flush()
            role = Role(id=str(uuid4()), organization_id=org_id, name="Owner", status="active")
            session.add(role)
            await session.flush()
            session.add(User(
                id=user_id, organization_id=org_id, role_id=role.id, name="Subscriber",
                email=case.actor.email, password_hash="unused-synthetic-hash", status="active",
            ))
            for code, amount in (("free", 0), ("professional", 4900), ("business", 9900)):
                plan = BillingPlan(
                    id=str(uuid4()), code=code, name=code.title(), status="active",
                    default_currency="USD", limits={}, entitlements=[], metering={},
                    source_version=1, source_hash="0" * 64,
                )
                session.add(plan)
                await session.flush()
                session.add(BillingPrice(
                    id=str(uuid4()), plan_id=plan.id, period_code="monthly", months=1,
                    amount_minor=amount, currency="USD", enabled=True, provider="manual",
                    price_metadata={},
                ))
                case.plans[code] = plan.id
            # An internal wildcard plan must never count as the scanning flag.
            session.add(BillingPlan(
                id=str(uuid4()), code="internal", name="Internal", status="internal",
                default_currency="USD", limits={}, entitlements=["*"], metering={},
                source_version=0, source_hash="1" * 64,
            ))
            session.add(BillingAccount(
                id=str(uuid4()), organization_id=org_id, plan_id=case.plans["business"],
                status="active", licensed_seats=1, provider_customers={}, limits={},
                entitlements=["*"],
            ))
            session.add(SecurityTarget(
                id=case.target_id, organization_id=org_id, created_by_id=user_id,
                verified_by_id=user_id, kind="external_authorized",
                origin="https://93.184.216.34", hostname="93.184.216.34",
                authorization_status="verified", verification_method="http_file",
                active_scan_allowed=True, status="active", verified_at=datetime.now(UTC),
                target_metadata={
                    "verified_addresses": ["93.184.216.34"],
                    "verification": {"method": "http_file", "challenge_sha256": hashlib.sha256(b"x").hexdigest()},
                },
            ))
            session.add(OwnerControlRecord(
                domain=security_fabric.POLICY_DOMAIN, resource_id=security_fabric.POLICY_RESOURCE,
                status="active", enabled=True, version=1, payload=dict(security_fabric.DEFAULT_POLICY),
            ))
            await session.commit()

        async def open_admission(_session):
            return None

        monkeypatch.setattr(security_scanning, "require_scan_admission", open_admission)

        async def request_db():
            async with sessions() as session:
                yield session

        async def actor_dependency():
            return case.actor

        app = FastAPI()
        app.include_router(security_lab.router, prefix=PREFIX, dependencies=[Depends(require_non_free_user)])
        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[current_user] = actor_dependency
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://isolated.test"
        ) as client:
            case.client = client
            yield case
    finally:
        await engine.dispose()
        if created:
            async with administration.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await administration.dispose()


async def _subscribe(case, code, status="active"):
    async with case.sessions() as session:
        existing = await session.scalar(select(BillingSubscription))
        if existing is None:
            session.add(BillingSubscription(
                id=str(uuid4()), organization_id=case.actor.organization_id,
                plan_id=case.plans[code], provider="manual", status=status,
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC) + timedelta(days=20),
                subscription_metadata={},
            ))
        else:
            existing.plan_id = case.plans[code]
            existing.status = status
        await session.commit()


async def _policy(case, **subscription_access):
    async with case.sessions() as session:
        await security_fabric.update_policy(session, {"subscription_access": subscription_access})
        await session.commit()


async def _scan(case):
    return await case.client.post(
        PREFIX + "/scans", json={"target_id": case.target_id, "profile": "standard"}
    )


@pytest.mark.asyncio
async def test_top_plan_subscription_entitlement_limits_and_lapse(subscriber_case):
    case = subscriber_case
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["granted"] is False and access["upgrade_required"] is True
    assert access["entitled_plans"] == ["business"]

    response = await _scan(case)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"

    await _subscribe(case, "professional")
    response = await _scan(case)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"

    await _subscribe(case, "business")
    access = (await case.client.get(PREFIX + "/access")).json()
    assert (access["granted"], access["level"], access["source"]) == (True, "subscriber", "subscription")
    assert access["limits"] == {"max_verified_targets": 3, "max_scans_per_month": 20, "max_concurrent_scans": 1}
    assert access["usage"]["verified_targets"] == 1

    response = await _scan(case)
    assert response.status_code == 202, response.text
    scan_id = response.json()["id"]
    assert response.json()["summary"]["access_source"] == "subscription"

    response = await _scan(case)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SECURITY_CONCURRENT_SCAN_LIMIT_REACHED"

    async with case.sessions() as session:
        scan = await session.get(SecurityScan, scan_id)
        scan.status = "completed"
        await session.commit()
    await _policy(case, max_scans_per_month=1)
    response = await _scan(case)
    assert response.status_code == 429
    assert response.json()["detail"] == {
        "code": "SECURITY_MONTHLY_SCAN_LIMIT_REACHED",
        "message": response.json()["detail"]["message"],
        "limit": "max_scans_per_month",
        "allowed": 1,
        "used": 1,
    }

    await _policy(case, max_verified_targets=1)
    response = await case.client.post(PREFIX + "/targets/external", json={"origin": "https://93.184.216.35"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SECURITY_TARGET_LIMIT_REACHED"

    # Lapse: new scans are refused, past reports remain readable.
    await _subscribe(case, "business", status="canceled")
    await _policy(case, max_scans_per_month=20)
    response = await _scan(case)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"
    history = await case.client.get(PREFIX + "/scans")
    assert history.status_code == 200 and [row["id"] for row in history.json()] == [scan_id]
    assert (await case.client.get(PREFIX + f"/scans/{scan_id}/findings")).status_code == 200
    report = await case.client.get(PREFIX + f"/scans/{scan_id}/report")
    assert report.status_code == 200
    assert report.json()["target"]["origin"] == "https://93.184.216.34"
    targets = await case.client.get(PREFIX + "/targets")
    assert targets.status_code == 200 and [row["id"] for row in targets.json()] == [case.target_id]


@pytest.mark.asyncio
async def test_owner_plan_codes_override_and_entitlement_flag(subscriber_case):
    case = subscriber_case
    await _subscribe(case, "professional")
    await _policy(case, plan_codes=["professional"])
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["level"] == "subscriber" and access["plan_code"] == "professional"

    await _policy(case, plan_codes=[])
    async with case.sessions() as session:
        plan = await session.get(BillingPlan, case.plans["professional"])
        plan.entitlements = ["security.web_scanning"]
        await session.commit()
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["entitled_plans"] == ["professional"]
    assert access["granted"] is True

    await _policy(case, enabled=False)
    access = (await case.client.get(PREFIX + "/access")).json()
    assert access["granted"] is False
