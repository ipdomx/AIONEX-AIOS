from aios.ios_app.models import IOSDevice, IOSDeviceRegistry, IOSDeviceState
from aios.ios_app.notifications import IOSNotification, IOSNotificationCenter
from aios.ios_app.offline_queue import IOSOfflineQueue, OfflineAction, OfflineActionState
from aios.ios_app.projects import IOSProjectAccessService, IOSProjectSummary
from aios.ios_app.sessions import IOSSessionService


def test_ios_device_registration_and_revocation() -> None:
    registry = IOSDeviceRegistry()
    registry.register(
        IOSDevice(
            device_id="ios-1",
            owner_id="owner-1",
            apns_token="token",
            app_version="1.0.0",
            platform_version="18",
        )
    )
    assert len(registry.active_for_owner("owner-1")) == 1
    assert registry.revoke("ios-1", "owner-1").state is IOSDeviceState.REVOKED


def test_ios_session_refresh_and_scope() -> None:
    service = IOSSessionService()
    session = service.create(session_id="s-1", owner_id="owner-1", device_id="ios-1")
    old_access = session.access_token
    service.refresh("s-1", "owner-1", session.refresh_token)
    assert session.access_token != old_access


def test_ios_projects_are_owner_isolated() -> None:
    service = IOSProjectAccessService()
    service.upsert(IOSProjectSummary(project_id="p-1", owner_id="owner-1", name="AIOS", state="active", progress=50))
    assert service.get("p-1", "owner-1").progress == 50
    assert len(service.list_for_owner("owner-2")) == 0


def test_ios_notifications_and_offline_queue() -> None:
    center = IOSNotificationCenter()
    center.publish(IOSNotification(notification_id="n-1", owner_id="owner-1", title="Done", body="Ready", topic="project"))
    assert len(center.list_for_owner("owner-1", unread_only=True)) == 1
    assert center.mark_read("n-1", "owner-1").read is True

    queue = IOSOfflineQueue()
    queue.enqueue(OfflineAction(action_id="a-1", owner_id="owner-1", action_type="comment", payload={"text": "ok"}))
    assert queue.start("a-1", "owner-1").state is OfflineActionState.SYNCING
    assert queue.complete("a-1", "owner-1").state is OfflineActionState.COMPLETED
