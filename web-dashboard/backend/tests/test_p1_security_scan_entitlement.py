"""Phase 1 (1.1-1.4): top-plan Security Lab entitlement, DNS TXT verification,
re-verification, per-subscriber limits and the public API contract.

These tests never contact a resolver or a website: dnspython's resolver,
``socket.getaddrinfo`` and the HTTP proof fetch are replaced in-process.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import dns.asyncresolver
import dns.exception
import dns.resolver
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import security_lab
from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import BillingPlan, BillingPrice, SecurityScan, SecurityTarget
from app.services import (
    security_dns_verification,
    security_entitlement,
    security_fabric,
    security_scanning,
)
from app.services.free_tier import require_non_free_user
from app.services.security_entitlement import SecurityAccess, SecurityLabError

PREFIX = "/api/v1/security-lab"
CHALLENGE = "aionex-verify-" + "x" * 43


def _actor(role: str = "Owner") -> UserRecord:
    return UserRecord(
        id="user-1",
        email="subscriber@example.test",
        name="Subscriber",
        role=role,
        password_hash="unused-synthetic-hash",
        organization_id="org-1",
        organization_name="Subscriber Organization",
        organization_plan="business",
        permissions=[],
    )


def _policy(**subscription: Any) -> dict[str, Any]:
    policy = {
        **security_fabric.DEFAULT_POLICY,
        "subscription_access": security_fabric.normalize_subscription_access(subscription),
    }
    return policy


def _target(**overrides: Any) -> SecurityTarget:
    values: dict[str, Any] = {
        "id": "target-1",
        "organization_id": "org-1",
        "created_by_id": "user-1",
        "kind": "external_authorized",
        "origin": "https://example.com",
        "hostname": "example.com",
        "authorization_status": "pending",
        "verification_method": "http_file",
        "challenge_hash": hashlib.sha256(CHALLENGE.encode()).hexdigest(),
        "active_scan_allowed": False,
        "status": "active",
        "target_metadata": {"verified_addresses": ["93.184.216.34"]},
    }
    values.update(overrides)
    return SecurityTarget(**values)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Minimal AsyncSession stand-in: queued results, recorded writes."""

    def __init__(
        self,
        *,
        scalar: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        get: dict[Any, Any] | None = None,
    ) -> None:
        self.scalar_results = list(scalar or [])
        self.scalars_results = list(scalars or [])
        self.get_results = dict(get or {})
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, _statement: Any) -> Any:
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def scalars(self, _statement: Any) -> _Result:
        return _Result(self.scalars_results.pop(0) if self.scalars_results else [])

    async def get(self, _model: Any, key: Any) -> Any:
        return self.get_results.get(key)

    async def execute(self, _statement: Any) -> None:
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _item: Any) -> None:
        return None


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        security_fabric.socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (security_fabric.socket.AF_INET, security_fabric.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )


@pytest.fixture
def fixed_policy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    policy = _policy()

    async def get_policy(_session: Any, *, for_update: bool = False) -> dict[str, Any]:
        return policy

    monkeypatch.setattr(security_fabric, "get_policy", get_policy)
    return policy


def _txt_answer(*values: str) -> list[Any]:
    return [SimpleNamespace(strings=(value.encode(),)) for value in values]


def _install_resolver(monkeypatch: pytest.MonkeyPatch, behaviour: Any) -> list[str]:
    calls: list[str] = []

    async def resolve(self: Any, name: str, rdtype: str, **_kwargs: Any) -> Any:
        calls.append(name)
        assert rdtype == "TXT"
        assert self.lifetime <= 15
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", resolve)
    return calls


# --- DNS TXT verification ---------------------------------------------------


def test_dns_record_name_and_instructions() -> None:
    assert security_dns_verification.record_name("Example.COM.") == "_aionex-security.example.com"
    info = security_dns_verification.instructions("example.com", "tok")
    assert info == {
        "method": "dns_txt",
        "available": True,
        "record_name": "_aionex-security.example.com",
        "record_type": "TXT",
        "record_value": "aionex-verify=tok",
    }
    assert security_dns_verification.instructions("93.184.216.34", "tok")["available"] is False
    with pytest.raises(security_dns_verification.DnsVerificationError):
        security_dns_verification.record_name("93.184.216.34")


@pytest.mark.asyncio
async def test_dns_txt_verification_success(monkeypatch, public_dns, fixed_policy) -> None:
    calls = _install_resolver(
        monkeypatch, _txt_answer("v=spf1 -all", f"aionex-verify={CHALLENGE}")
    )
    target = _target()
    session = FakeSession()
    await security_fabric.verify_external_target(
        session, _actor(), target, challenge=CHALLENGE, method="dns_txt"  # type: ignore[arg-type]
    )
    assert calls == ["_aionex-security.example.com"]
    assert target.authorization_status == "verified"
    assert target.verification_method == "dns_txt"
    assert target.challenge_hash is None
    record = target.target_metadata["verification"]
    assert record["method"] == "dns_txt"
    assert record["challenge_sha256"] == hashlib.sha256(CHALLENGE.encode()).hexdigest()
    assert "challenge_sha256" not in security_fabric.target_snapshot(target)["metadata"]["verification"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behaviour",
    [
        _txt_answer("aionex-verify=someone-elses-token"),
        dns.resolver.NXDOMAIN(),
        dns.resolver.NoAnswer(),
    ],
)
async def test_dns_txt_verification_failure(monkeypatch, public_dns, fixed_policy, behaviour) -> None:
    _install_resolver(monkeypatch, behaviour)
    target = _target()
    with pytest.raises(security_dns_verification.DnsVerificationError) as raised:
        await security_fabric.verify_external_target(
            FakeSession(), _actor(), target, challenge=CHALLENGE, method="dns_txt"  # type: ignore[arg-type]
        )
    assert raised.value.code == "SECURITY_DNS_VERIFICATION_FAILED"
    assert target.authorization_status == "pending"
    assert target.challenge_hash is not None


@pytest.mark.asyncio
async def test_dns_txt_verification_timeout(monkeypatch, public_dns, fixed_policy) -> None:
    _install_resolver(monkeypatch, dns.exception.Timeout())
    target = _target()
    with pytest.raises(security_dns_verification.DnsVerificationTimeout) as raised:
        await security_fabric.verify_external_target(
            FakeSession(), _actor(), target, challenge=CHALLENGE, method="dns_txt"  # type: ignore[arg-type]
        )
    assert raised.value.code == "SECURITY_DNS_TIMEOUT"
    assert target.authorization_status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "::1"])
@pytest.mark.parametrize("method", ["http_file", "dns_txt"])
async def test_ssrf_still_blocked_before_any_proof_fetch(
    monkeypatch, fixed_policy, address, method
) -> None:
    monkeypatch.setattr(
        security_fabric.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(security_fabric.socket.AF_INET, security_fabric.socket.SOCK_STREAM, 6, "", (address, 0))],
    )
    resolver_calls = _install_resolver(monkeypatch, _txt_answer(f"aionex-verify={CHALLENGE}"))
    http_calls: list[str] = []

    async def http_value(target: SecurityTarget) -> str:
        http_calls.append(target.origin)
        return CHALLENGE

    monkeypatch.setattr(security_fabric, "_http_file_value", http_value)
    target = _target()
    with pytest.raises(ValueError, match="public routable addresses"):
        await security_fabric.verify_external_target(
            FakeSession(), _actor(), target, challenge=CHALLENGE, method=method  # type: ignore[arg-type]
        )
    assert not resolver_calls and not http_calls
    assert target.authorization_status == "pending"
    with pytest.raises(ValueError, match="public routable addresses"):
        security_fabric.assert_public_target("internal.example")


@pytest.mark.asyncio
async def test_http_file_verification_still_supported(monkeypatch, public_dns, fixed_policy) -> None:
    async def http_value(_target: SecurityTarget) -> str:
        return CHALLENGE

    monkeypatch.setattr(security_fabric, "_http_file_value", http_value)
    target = _target()
    await security_fabric.verify_external_target(
        FakeSession(), _actor(), target, challenge=CHALLENGE  # type: ignore[arg-type]
    )
    assert target.authorization_status == "verified"
    assert target.verification_method == "http_file"


@pytest.mark.asyncio
async def test_stale_verification_is_reproven_from_stored_digest(monkeypatch, public_dns, fixed_policy) -> None:
    old = datetime.now(UTC) - timedelta(days=45)
    digest = hashlib.sha256(CHALLENGE.encode()).hexdigest()
    target = _target(
        authorization_status="verified",
        verification_method="dns_txt",
        challenge_hash=None,
        verified_at=old,
        target_metadata={
            "verified_addresses": ["93.184.216.34"],
            "verification": {"method": "dns_txt", "challenge_sha256": digest},
        },
    )
    assert security_fabric.verification_is_stale(target, max_age_days=30)
    assert not security_fabric.verification_is_stale(target, max_age_days=60)
    managed = _target(kind="managed_project", verified_at=old)
    assert not security_fabric.verification_is_stale(managed, max_age_days=1)

    _install_resolver(monkeypatch, _txt_answer(f"aionex-verify={CHALLENGE}"))
    await security_fabric.reverify_external_target(FakeSession(), target)  # type: ignore[arg-type]
    assert target.verified_at is not None and target.verified_at > old

    _install_resolver(monkeypatch, _txt_answer())
    with pytest.raises(ValueError):
        await security_fabric.reverify_external_target(FakeSession(), target)  # type: ignore[arg-type]

    legacy = _target(authorization_status="verified", verified_at=old, target_metadata={})
    with pytest.raises(ValueError, match="register the target again"):
        await security_fabric.reverify_external_target(FakeSession(), legacy)  # type: ignore[arg-type]


# --- Highest-plan entitlement ----------------------------------------------


def _plan(code: str, *, entitlements: list[str] | None = None, plan_id: str | None = None) -> BillingPlan:
    return BillingPlan(
        id=plan_id or f"plan-{code}",
        code=code,
        name=code.title(),
        status="active",
        default_currency="USD",
        limits={},
        entitlements=entitlements or [],
        metering={},
        source_version=1,
        source_hash="0" * 64,
    )


def _price(plan: BillingPlan, amount: int | None, *, months: int = 1, currency: str = "USD", enabled: bool = True) -> BillingPrice:
    return BillingPrice(
        id=f"price-{plan.code}-{months}-{currency}",
        plan_id=plan.id,
        period_code=f"p{months}",
        months=months,
        amount_minor=amount,
        currency=currency,
        enabled=enabled,
        provider="manual",
        price_metadata={},
    )


@pytest.mark.asyncio
async def test_highest_plan_defaults_to_top_ranked_monthly_price() -> None:
    free, pro, business, scale = _plan("free"), _plan("professional"), _plan("business"), _plan("scale")
    prices = [
        _price(free, 0),
        _price(pro, 4900),
        _price(business, 9900),
        # 12 x 9000 billed yearly is cheaper per month than business monthly.
        _price(scale, 108000, months=12),
        # A foreign-currency price never outranks by unit alone.
        _price(pro, 99999999, currency="JPY"),
        _price(free, 999999, enabled=False),
    ]
    session = FakeSession(scalars=[[free, pro, business, scale], [free, pro, business, scale], prices])
    codes, basis = await security_entitlement.entitled_plans(
        session, security_fabric.normalize_subscription_access({})  # type: ignore[arg-type]
    )
    assert (codes, basis) == (["business"], "top_ranked_plan")


@pytest.mark.asyncio
async def test_plan_entitlement_flag_and_owner_plan_codes_take_precedence() -> None:
    internal = _plan("internal", entitlements=["*"])
    flagged = _plan("professional", entitlements=["security.web_scanning"])
    session = FakeSession(scalars=[[internal, flagged]])
    codes, basis = await security_entitlement.entitled_plans(
        session, security_fabric.normalize_subscription_access({})  # type: ignore[arg-type]
    )
    assert (codes, basis) == (["professional"], "plan_entitlement")
    codes, basis = await security_entitlement.entitled_plans(
        FakeSession(),  # type: ignore[arg-type]
        security_fabric.normalize_subscription_access({"plan_codes": ["Business Plus"]}),
    )
    assert (codes, basis) == (["business-plus"], "policy_plan_codes")


def _subscription(status: str = "active", period_end: datetime | None = None) -> Any:
    return SimpleNamespace(plan_id="plan-business", status=status, current_period_end=period_end)


@pytest.mark.asyncio
async def test_active_subscription_plan_respects_period_and_account_status() -> None:
    business = _plan("business")
    future = datetime.now(UTC) + timedelta(days=10)
    past = datetime.now(UTC) - timedelta(minutes=1)
    active_account = SimpleNamespace(status="active")
    session = FakeSession(scalar=[active_account], scalars=[[_subscription(period_end=future)]], get={"plan-business": business})
    assert await security_entitlement.active_subscription_plan(session, "org-1") is business  # type: ignore[arg-type]
    session = FakeSession(scalar=[active_account], scalars=[[_subscription(period_end=past)]], get={"plan-business": business})
    assert await security_entitlement.active_subscription_plan(session, "org-1") is None  # type: ignore[arg-type]
    session = FakeSession(scalar=[SimpleNamespace(status="suspended")], scalars=[[_subscription()]], get={"plan-business": business})
    assert await security_entitlement.active_subscription_plan(session, "org-1") is None  # type: ignore[arg-type]


def _patch_resolution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    grant: str | None = None,
    subscribed: str | None = None,
    entitled: tuple[list[str], str] = (["business"], "top_ranked_plan"),
) -> list[str]:
    billing_calls: list[str] = []

    async def access_level(_session: Any, _actor: Any) -> str | None:
        return grant

    async def entitled_plans(_session: Any, _settings: Any) -> tuple[list[str], str]:
        billing_calls.append("plans")
        return entitled

    async def active_plan(_session: Any, _org: str) -> BillingPlan | None:
        billing_calls.append("subscription")
        return _plan(subscribed) if subscribed else None

    monkeypatch.setattr(security_fabric, "access_level", access_level)
    monkeypatch.setattr(security_entitlement, "entitled_plans", entitled_plans)
    monkeypatch.setattr(security_entitlement, "active_subscription_plan", active_plan)
    return billing_calls


@pytest.mark.asyncio
async def test_entitlement_on_for_top_plan_subscriber(monkeypatch) -> None:
    _patch_resolution(monkeypatch, subscribed="business")
    access = await security_entitlement.resolve_access(FakeSession(), _actor(), policy=_policy())  # type: ignore[arg-type]
    assert (access.level, access.source, access.plan_code) == ("subscriber", "subscription", "business")
    assert access.profiles() == ["passive", "standard"]
    assert security_entitlement.limits(access) == {
        "max_verified_targets": 3,
        "max_scans_per_month": 20,
        "max_concurrent_scans": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("subscribed", [None, "professional"])
async def test_entitlement_off_for_lapsed_or_lower_plan(monkeypatch, subscribed) -> None:
    _patch_resolution(monkeypatch, subscribed=subscribed)
    access = await security_entitlement.resolve_access(FakeSession(), _actor(), policy=_policy())  # type: ignore[arg-type]
    assert access.level is None
    error = access.plan_required()
    assert error.status_code == 403
    assert error.detail()["code"] == "SECURITY_PLAN_REQUIRED"
    assert error.detail()["entitled_plans"] == ["business"]


@pytest.mark.asyncio
async def test_owner_grant_override_and_super_owner_skip_billing(monkeypatch) -> None:
    calls = _patch_resolution(monkeypatch, grant="elite")
    access = await security_entitlement.resolve_access(FakeSession(), _actor(), policy=_policy())  # type: ignore[arg-type]
    assert (access.level, access.source) == ("elite", "grant")
    assert security_entitlement.limits(access) is None
    calls_owner = _patch_resolution(monkeypatch, grant="owner")
    access = await security_entitlement.resolve_access(
        FakeSession(), _actor("Super Owner"), policy=_policy()  # type: ignore[arg-type]
    )
    assert access.is_owner
    assert not calls and not calls_owner


@pytest.mark.asyncio
async def test_subscription_access_can_be_disabled_by_owner(monkeypatch) -> None:
    calls = _patch_resolution(monkeypatch, subscribed="business")
    access = await security_entitlement.resolve_access(
        FakeSession(), _actor(), policy=_policy(enabled=False)  # type: ignore[arg-type]
    )
    assert access.level is None and not calls


def test_subscription_policy_normalization_bounds_values() -> None:
    normalized = security_fabric.normalize_subscription_access(
        {"max_concurrent_scans": 0, "max_scans_per_month": "x", "plan_codes": [" Business ", ""]}
    )
    assert normalized["max_concurrent_scans"] == 1
    assert normalized["max_scans_per_month"] == 20
    assert normalized["plan_codes"] == ["business"]
    with pytest.raises(ValueError):
        security_fabric.normalize_subscription_access({"plan_codes": [f"p{i}" for i in range(21)]})


# --- Usage limits ----------------------------------------------------------


def _subscriber(**settings: Any) -> SecurityAccess:
    return SecurityAccess(
        level="subscriber",
        source="subscription",
        plan_code="business",
        settings=security_fabric.normalize_subscription_access(settings),
    )


def _usage(**values: int) -> Any:
    async def usage(_session: Any, _actor: Any) -> dict[str, Any]:
        return {
            "targets": 0,
            "verified_targets": 0,
            "scans_this_month": 0,
            "active_scans": 0,
            **values,
        }

    return usage


@pytest.mark.asyncio
async def test_scan_limits_concurrent_and_monthly(monkeypatch) -> None:
    session = FakeSession()
    monkeypatch.setattr(security_entitlement, "usage", _usage(active_scans=1))
    with pytest.raises(SecurityLabError) as raised:
        await security_entitlement.enforce_scan_limits(session, _subscriber(), _actor())  # type: ignore[arg-type]
    assert raised.value.status_code == 429
    assert raised.value.detail()["code"] == "SECURITY_CONCURRENT_SCAN_LIMIT_REACHED"

    monkeypatch.setattr(security_entitlement, "usage", _usage(scans_this_month=5))
    with pytest.raises(SecurityLabError) as raised:
        await security_entitlement.enforce_scan_limits(
            session, _subscriber(max_scans_per_month=5), _actor()  # type: ignore[arg-type]
        )
    assert raised.value.detail() | {} == {
        "code": "SECURITY_MONTHLY_SCAN_LIMIT_REACHED",
        "message": raised.value.message,
        "limit": "max_scans_per_month",
        "allowed": 5,
        "used": 5,
    }

    monkeypatch.setattr(security_entitlement, "usage", _usage(scans_this_month=4))
    await security_entitlement.enforce_scan_limits(
        session, _subscriber(max_scans_per_month=5), _actor()  # type: ignore[arg-type]
    )
    # Owner grants are overrides and are never metered.
    grant = SecurityAccess(level="standard", source="grant")
    monkeypatch.setattr(security_entitlement, "usage", _usage(active_scans=9, scans_this_month=999))
    await security_entitlement.enforce_scan_limits(session, grant, _actor())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_target_limit(monkeypatch) -> None:
    with pytest.raises(SecurityLabError) as raised:
        await security_entitlement.enforce_target_limit(
            FakeSession(scalar=[3]), _subscriber(), _actor(), origin="https://new.example"  # type: ignore[arg-type]
        )
    assert raised.value.detail()["code"] == "SECURITY_TARGET_LIMIT_REACHED"
    assert raised.value.detail()["allowed"] == 3
    await security_entitlement.enforce_target_limit(
        FakeSession(scalar=[2]), _subscriber(), _actor(), origin="https://new.example"  # type: ignore[arg-type]
    )


def test_month_bounds() -> None:
    start, end = security_entitlement.month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert start == datetime(2026, 12, 1, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, tzinfo=UTC)


# --- Public API contract ---------------------------------------------------


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(session=FakeSession(), actor=_actor(), access=SecurityAccess(level=None, source=None, entitled_plan_codes=("business",)))
    policy = _policy()

    async def get_policy(_session: Any, *, for_update: bool = False) -> dict[str, Any]:
        return policy

    async def resolve_access(_session: Any, _actor: Any, *, policy: Any = None) -> SecurityAccess:
        return state.access

    async def admission(_session: Any) -> None:
        return None

    monkeypatch.setattr(security_fabric, "get_policy", get_policy)
    monkeypatch.setattr(security_entitlement, "resolve_access", resolve_access)
    monkeypatch.setattr(security_scanning, "require_scan_admission", admission)
    monkeypatch.setattr(security_entitlement, "usage", _usage())

    app = FastAPI()
    app.include_router(security_lab.router, prefix=PREFIX, dependencies=[Depends(require_non_free_user)])

    async def db() -> Any:
        yield state.session

    async def actor() -> UserRecord:
        return state.actor

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[current_user] = actor
    state.app = app
    return state


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated.test")


@pytest.mark.asyncio
async def test_api_returns_plan_required_code_for_non_entitled_user(api) -> None:
    async with _client(api.app) as client:
        response = await client.post(PREFIX + "/scans", json={"target_id": "target-1", "profile": "passive"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"
        response = await client.post(PREFIX + "/targets/external", json={"origin": "https://example.com"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"
        api.session.scalar_results = [0]
        response = await client.get(PREFIX + "/access")
        assert response.status_code == 200
        body = response.json()
        assert body["granted"] is False
        assert body["upgrade_required"] is True
        assert body["denial_code"] == "SECURITY_PLAN_REQUIRED"
        assert body["entitled_plans"] == ["business"]
        assert body["verification"]["dns_record_prefix"] == "_aionex-security"


@pytest.mark.asyncio
async def test_api_lapsed_subscriber_keeps_reading_past_reports(api) -> None:
    scan = SecurityScan(
        id="scan-1", organization_id="org-1", target_id="target-1", requested_by_id="user-1",
        profile="standard", status="completed", execution_mode="active_safe", tool_plan=[],
        summary={"finding_count": 0},
    )
    async with _client(api.app) as client:
        api.session.scalars_results = [[scan]]
        response = await client.get(PREFIX + "/scans")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["scan-1"]
        api.session.scalar_results = [scan]
        api.session.scalars_results = [[]]
        response = await client.get(PREFIX + "/scans/scan-1/findings")
        assert response.status_code == 200 and response.json() == []
        api.session.scalar_results = [scan]
        api.session.scalars_results = [[]]
        api.session.get_results = {"target-1": _target(authorization_status="verified")}
        response = await client.get(PREFIX + "/scans/scan-1/report")
        assert response.status_code == 200
        report = response.json()
        assert report["target"]["origin"] == "https://example.com"
        assert list(report["findings_by_severity"]) == ["critical", "high", "medium", "low", "info"]
        # A new scan is refused once the subscription has lapsed.
        response = await client.post(PREFIX + "/scans", json={"target_id": "target-1", "profile": "passive"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "SECURITY_PLAN_REQUIRED"


@pytest.mark.asyncio
async def test_api_subscriber_cannot_scan_someone_elses_target(api, public_dns) -> None:
    api.access = _subscriber()
    foreign = _target(created_by_id="user-2", authorization_status="verified", verified_at=datetime.now(UTC))
    async with _client(api.app) as client:
        api.session.scalar_results = [foreign]
        response = await client.post(PREFIX + "/scans", json={"target_id": "target-1", "profile": "standard"})
        assert response.status_code == 404
        response = await client.post(PREFIX + "/scans", json={"target_id": "target-1", "profile": "advanced"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "SECURITY_PROFILE_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_api_scan_limit_is_reported_as_429(api, public_dns, monkeypatch) -> None:
    api.access = _subscriber()
    monkeypatch.setattr(security_entitlement, "usage", _usage(active_scans=1))
    own = _target(authorization_status="verified", verified_at=datetime.now(UTC))
    async with _client(api.app) as client:
        api.session.scalar_results = [own]
        response = await client.post(PREFIX + "/scans", json={"target_id": "target-1", "profile": "standard"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SECURITY_CONCURRENT_SCAN_LIMIT_REACHED"
    assert api.session.rollbacks == 1 and api.session.commits == 0


@pytest.mark.asyncio
async def test_api_dns_timeout_on_verify_returns_coded_error(api, public_dns, monkeypatch) -> None:
    api.access = _subscriber()
    _install_resolver(monkeypatch, dns.exception.Timeout())
    pending = _target()
    async with _client(api.app) as client:
        api.session.scalar_results = [pending, 0]
        response = await client.post(
            PREFIX + "/targets/target-1/verify",
            json={"challenge": CHALLENGE, "method": "dns_txt"},
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SECURITY_DNS_TIMEOUT"
    assert pending.authorization_status == "pending"
