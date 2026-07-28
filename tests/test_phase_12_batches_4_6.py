from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aios.meetings_access.booking_service import (
    BookingStatus,
    SessionBooking,
    SessionBookingService,
    StaffAvailability,
)
from aios.meetings_access.entitlements import SessionEntitlement, SessionEntitlementService
from aios.meetings_access.settlement import (
    SessionSettlement,
    SessionSettlementService,
    SettlementStatus,
)


def test_booking_requires_availability_and_owner_confirmation() -> None:
    service = SessionBookingService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=1)
    service.add_availability(
        StaffAvailability(
            staff_id="staff-1",
            role="engineer",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
        )
    )
    booking = service.create(
        SessionBooking(
            booking_id="booking-1",
            request_id="request-1",
            owner_id="owner-1",
            user_id="user-1",
            staff_id="staff-1",
            role="engineer",
            starts_at=starts_at,
            duration_minutes=60,
        )
    )
    assert booking.status is BookingStatus.PENDING
    assert service.confirm("booking-1", "owner-1").status is BookingStatus.CONFIRMED


def test_booking_prevents_overlap() -> None:
    service = SessionBookingService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=1)
    service.add_availability(
        StaffAvailability("staff-1", "manager", starts_at, starts_at + timedelta(hours=3))
    )
    service.create(
        SessionBooking(
            "booking-1", "request-1", "owner-1", "user-1", "staff-1", "manager", starts_at, 60
        )
    )
    try:
        service.create(
            SessionBooking(
                "booking-2",
                "request-2",
                "owner-1",
                "user-2",
                "staff-1",
                "manager",
                starts_at + timedelta(minutes=30),
                60,
            )
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("overlapping booking must be rejected")


def test_entitlement_consumption_enforces_scope_and_balance() -> None:
    service = SessionEntitlementService()
    service.grant(
        SessionEntitlement(
            entitlement_id="ent-1",
            owner_id="owner-1",
            user_id="user-1",
            role="employee",
            included_minutes=30,
        )
    )
    entitlement = service.consume(
        "ent-1", owner_id="owner-1", user_id="user-1", role="employee", minutes=20
    )
    assert entitlement.remaining_minutes == 10


def test_settlement_capture_and_refund_lifecycle() -> None:
    service = SessionSettlementService()
    settlement = service.create(
        SessionSettlement(
            settlement_id="settlement-1",
            booking_id="booking-1",
            owner_id="owner-1",
            user_id="user-1",
            currency="USD",
            gross_amount=Decimal("100.00"),
            platform_fee=Decimal("20.00"),
            staff_amount=Decimal("80.00"),
        )
    )
    assert settlement.status is SettlementStatus.PENDING
    captured = service.capture("settlement-1", "owner-1", "provider-ref-1")
    assert captured.status is SettlementStatus.CAPTURED
    assert service.refund("settlement-1", "owner-1").status is SettlementStatus.REFUNDED
