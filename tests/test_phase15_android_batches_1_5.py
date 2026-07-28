from aios.mobile_android.auth import AndroidAuthService
from aios.mobile_android.models import (
    AndroidDevice,
    AndroidNotificationItem,
    AndroidProjectSummary,
    AndroidSession,
    AndroidSessionState,
)
from aios.mobile_android.notifications import AndroidNotificationService
from aios.mobile_android.offline import AndroidOfflineQueue, PendingMobileAction
from aios.mobile_android.projects import AndroidProjectService


def test_android_device_and_session_lifecycle() -> None:
    service = AndroidAuthService()
    device = AndroidDevice(
        device_id="device-1",
        user_id="user-1",
        owner_id="owner-1",
        model="Pixel",
        os_version="15",
        app_version="1.0.0",
    )
    service.register_device(device)
    session = service.create_session(
        AndroidSession(
            session_id="session-1",
            user_id="user-1",
            owner_id="owner-1",
            device_id="device-1",
            access_token="access-1",
            refresh_token="refresh-1",
        )
    )
    assert session.state is AndroidSessionState.ACTIVE
    service.refresh("session-1", "refresh-1", "access-2")
    assert session.access_token == "access-2"
    service.revoke_device("device-1", "owner-1")
    assert session.state is AndroidSessionState.REVOKED


def test_android_projects_are_owner_isolated() -> None:
    service = AndroidProjectService()
    summary = AndroidProjectSummary(
        project_id="project-1",
        name="Mobile rollout",
        status="active",
        progress_percent=50,
        open_tasks=3,
        open_incidents=0,
    )
    service.upsert("owner-1", summary)
    assert service.get("owner-1", "project-1").name == "Mobile rollout"
    assert service.list_for_owner("owner-2") == []


def test_android_notifications_and_push_targets() -> None:
    service = AndroidNotificationService()
    service.register_device(
        AndroidDevice(
            device_id="device-1",
            user_id="user-1",
            owner_id="owner-1",
            model="Pixel",
            os_version="15",
            app_version="1.0.0",
            push_token="push-token-1",
        )
    )
    item = service.publish(
        "user-1",
        AndroidNotificationItem(
            notification_id="notification-1",
            title="Project completed",
            body="Your project is ready.",
            priority="high",
        ),
    )
    assert service.push_targets("user-1") == ["push-token-1"]
    service.acknowledge("user-1", item.notification_id)
    assert service.list_for_user("user-1", unresolved_only=True) == []


def test_android_offline_queue_is_idempotent() -> None:
    queue = AndroidOfflineQueue()
    action = queue.enqueue(
        PendingMobileAction(
            action_id="action-1",
            user_id="user-1",
            owner_id="owner-1",
            action="acknowledge-notification",
            payload={"notification_id": "notification-1"},
        )
    )
    queue.record_attempt(action.action_id)
    queue.complete(action.action_id)
    assert action.attempts == 1
    assert action.completed is True
