from datetime import datetime, timedelta, timezone

from aios.api_gateway.realtime import RealtimeEvent, RealtimeHub


def _event(
    event_id: str,
    *,
    topic: str,
    owner_id: str = "owner-1",
    created_at: datetime,
) -> RealtimeEvent:
    return RealtimeEvent(
        event_id=event_id,
        topic=topic,
        owner_id=owner_id,
        payload={"event_id": event_id},
        created_at=created_at,
    )


def test_resume_orders_owner_events_before_applying_cross_topic_cursor() -> None:
    hub = RealtimeHub()
    started_at = datetime(2026, 10, 13, tzinfo=timezone.utc)

    hub.publish(
        _event("cursor", topic="projects", created_at=started_at)
    )
    hub.publish(
        _event(
            "newer",
            topic="conversations",
            created_at=started_at + timedelta(seconds=1),
        )
    )

    events = hub.read(
        owner_id="owner-1",
        topics=["conversations", "projects"],
        after_event_id="cursor",
    )

    assert [event.event_id for event in events] == ["newer"]


def test_publish_deduplicates_event_id_per_owner_across_topics() -> None:
    hub = RealtimeHub()
    created_at = datetime(2026, 10, 13, tzinfo=timezone.utc)
    original = _event("shared-id", topic="projects", created_at=created_at)
    duplicate = _event(
        "shared-id",
        topic="conversations",
        created_at=created_at + timedelta(seconds=1),
    )

    assert hub.publish(original) is original
    assert hub.publish(duplicate) is original
    assert [
        event.event_id
        for event in hub.read(
            owner_id="owner-1",
            topics=["projects", "conversations"],
        )
    ] == ["shared-id"]


def test_same_event_id_isolated_between_owners() -> None:
    hub = RealtimeHub()
    created_at = datetime(2026, 10, 13, tzinfo=timezone.utc)

    first = _event("shared-id", topic="projects", created_at=created_at)
    second = _event(
        "shared-id",
        topic="projects",
        owner_id="owner-2",
        created_at=created_at,
    )

    assert hub.publish(first) is first
    assert hub.publish(second) is second
    assert [
        event.event_id
        for event in hub.read(owner_id="owner-1", topics=["projects"])
    ] == ["shared-id"]
    assert [
        event.event_id
        for event in hub.read(owner_id="owner-2", topics=["projects"])
    ] == ["shared-id"]
