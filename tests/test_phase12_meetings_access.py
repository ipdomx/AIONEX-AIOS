from datetime import datetime, timezone

from aios.meetings_access.access_policy import AccessPolicy, AccessPolicyService
from aios.meetings_access.models import RoleSessionRequest, SessionRole, SessionStatus
from aios.meetings_access.pricing import RoleRate, SessionPricingService
from aios.meetings_access.session_service import RoleSessionService


def test_owner_approval_and_session_lifecycle() -> None:
    service = RoleSessionService()
    request = service.submit(
        RoleSessionRequest(
            session_id="session-1",
            user_id="user-1",
            project_id="project-1",
            role=SessionRole.ENGINEER,
            requested_minutes=30,
            paid=True,
            reason="architecture review",
        )
    )
    assert request.status is SessionStatus.PENDING_OWNER_APPROVAL

    approved = service.approve(
        "session-1",
        owner_id="owner-1",
        approved_minutes=30,
        price_minor=4500,
        starts_at=datetime.now(timezone.utc),
    )
    assert approved.status is SessionStatus.SCHEDULED
    assert approved.owner_id == "owner-1"

    service.start("session-1")
    assert service.get("session-1").status is SessionStatus.ACTIVE
    service.complete("session-1")
    assert service.get("session-1").status is SessionStatus.COMPLETED


def test_access_policy_enforces_free_limits_and_paid_toggle() -> None:
    service = AccessPolicyService()
    service.set_policy(
        AccessPolicy(
            owner_id="owner-1",
            free_minutes_by_role={SessionRole.EMPLOYEE: 20},
            paid_access_enabled=True,
            role_enabled={SessionRole.CHIEF_ENGINEER: False},
        )
    )

    assert service.can_request(
        owner_id="owner-1",
        user_id="user-1",
        role=SessionRole.EMPLOYEE,
        paid=False,
    )
    service.reserve_free_minutes(
        owner_id="owner-1",
        user_id="user-1",
        role=SessionRole.EMPLOYEE,
        minutes=20,
    )
    assert not service.can_request(
        owner_id="owner-1",
        user_id="user-1",
        role=SessionRole.EMPLOYEE,
        paid=False,
    )
    assert not service.can_request(
        owner_id="owner-1",
        user_id="user-1",
        role=SessionRole.CHIEF_ENGINEER,
        paid=True,
    )


def test_role_pricing_quote() -> None:
    pricing = SessionPricingService(
        [
            RoleRate(SessionRole.EMPLOYEE, 25),
            RoleRate(SessionRole.ENGINEER, 150),
            RoleRate(SessionRole.MANAGER, 250),
            RoleRate(SessionRole.CHIEF_ENGINEER, 500),
        ]
    )
    amount, currency = pricing.quote(role=SessionRole.ENGINEER, minutes=30)
    assert amount == 4500
    assert currency == "EUR"
