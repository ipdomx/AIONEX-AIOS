from aios.mobile_ecosystem import (
    DevicePlatform,
    DeviceRegistration,
    MobileEcosystemPlatform,
    MobileNotification,
    NotificationPriority,
    SyncConflict,
)


def test_mobile_ecosystem_end_to_end() -> None:
    platform = MobileEcosystemPlatform.build_default()
    device = DeviceRegistration(
        device_id="device-1",
        user_id="user-1",
        platform=DevicePlatform.IOS,
        push_token="token-1",
        app_version="1.0.0",
    )
    platform.devices.register(device)
    assert platform.devices.count() == 1

    session = platform.sessions.create("user-1", "device-1", scopes={"projects:read"})
    assert session.is_active()

    notification = MobileNotification(
        notification_id="notification-1",
        user_id="user-1",
        title="Project completed",
        body="The project has completed successfully.",
        priority=NotificationPriority.HIGH,
        project_id="project-1",
    )
    platform.notifications.publish(notification)
    assert platform.notifications.unread_count("user-1") == 1
    platform.notifications.mark_read("notification-1")
    assert platform.notifications.unread_count("user-1") == 0

    first = platform.sync.push("project-1", 1, {"status": "running"})
    assert first.conflict is SyncConflict.NONE
    stale = platform.sync.push("project-1", 1, {"status": "completed"})
    assert stale.conflict is SyncConflict.SERVER_NEWER
    assert platform.validate()["ready"] is True


def test_session_revoke_and_device_unregister() -> None:
    platform = MobileEcosystemPlatform.build_default()
    platform.devices.register(
        DeviceRegistration(
            device_id="device-2",
            user_id="user-2",
            platform=DevicePlatform.ANDROID,
        )
    )
    session = platform.sessions.create("user-2", "device-2")
    platform.sessions.revoke(session.session_id)
    assert not session.is_active()
    assert platform.devices.unregister("device-2") is True
