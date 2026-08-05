from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(slots=True)
class StaffAvailability:
    staff_id: str
    role: str
    starts_at: datetime
    ends_at: datetime
    active: bool = True

    def overlaps(self, starts_at: datetime, ends_at: datetime) -> bool:
        return self.active and starts_at < self.ends_at and ends_at > self.starts_at


@dataclass(slots=True)
class SessionBooking:
    booking_id: str
    request_id: str
    owner_id: str
    user_id: str
    staff_id: str
    role: str
    starts_at: datetime
    duration_minutes: int
    status: BookingStatus = BookingStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancellation_reason: str | None = None

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)


class SessionBookingService:
    def __init__(self) -> None:
        self._availability: list[StaffAvailability] = []
        self._bookings: dict[str, SessionBooking] = {}

    def add_availability(self, slot: StaffAvailability) -> None:
        if slot.ends_at <= slot.starts_at:
            raise ValueError("availability end must be after start")
        self._availability.append(slot)

    def create(self, booking: SessionBooking) -> SessionBooking:
        if booking.booking_id in self._bookings:
            raise ValueError(f"duplicate booking: {booking.booking_id}")
        if booking.duration_minutes <= 0:
            raise ValueError("duration must be positive")
        if not any(
            slot.staff_id == booking.staff_id
            and slot.role == booking.role
            and slot.starts_at <= booking.starts_at
            and slot.ends_at >= booking.ends_at
            and slot.active
            for slot in self._availability
        ):
            raise RuntimeError("requested staff member is unavailable")
        if any(
            existing.staff_id == booking.staff_id
            and existing.status in {BookingStatus.PENDING, BookingStatus.CONFIRMED}
            and existing.starts_at < booking.ends_at
            and existing.ends_at > booking.starts_at
            for existing in self._bookings.values()
        ):
            raise RuntimeError("staff member already has an overlapping booking")
        self._bookings[booking.booking_id] = booking
        return booking

    def confirm(self, booking_id: str, owner_id: str) -> SessionBooking:
        booking = self._require_owner(booking_id, owner_id)
        if booking.status is not BookingStatus.PENDING:
            raise RuntimeError("only pending bookings can be confirmed")
        booking.status = BookingStatus.CONFIRMED
        return booking

    def cancel(self, booking_id: str, actor_id: str, reason: str) -> SessionBooking:
        booking = self._bookings[booking_id]
        if actor_id not in {booking.owner_id, booking.user_id}:
            raise PermissionError("booking cannot be cancelled by this actor")
        if booking.status is BookingStatus.COMPLETED:
            raise RuntimeError("completed bookings cannot be cancelled")
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = reason
        return booking

    def complete(self, booking_id: str, owner_id: str) -> SessionBooking:
        booking = self._require_owner(booking_id, owner_id)
        if booking.status is not BookingStatus.CONFIRMED:
            raise RuntimeError("only confirmed bookings can be completed")
        booking.status = BookingStatus.COMPLETED
        return booking

    def _require_owner(self, booking_id: str, owner_id: str) -> SessionBooking:
        booking = self._bookings[booking_id]
        if booking.owner_id != owner_id:
            raise PermissionError("booking is not owned by this owner")
        return booking
