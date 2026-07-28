from __future__ import annotations

from .models import AndroidDevice, AndroidNotificationItem


class AndroidNotificationService:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], AndroidNotificationItem] = {}
        self._devices: dict[str, AndroidDevice] = {}

    def register_device(self, device: AndroidDevice) -> None:
        self._devices[device.device_id] = device

    def publish(self, user_id: str, item: AndroidNotificationItem) -> AndroidNotificationItem:
        key = (user_id, item.notification_id)
        if key in self._items:
            raise ValueError(f"duplicate notification: {item.notification_id}")
        self._items[key] = item
        return item

    def list_for_user(self, user_id: str, unresolved_only: bool = False) -> list[AndroidNotificationItem]:
        items = [item for (stored_user_id, _), item in self._items.items() if stored_user_id == user_id]
        if unresolved_only:
            items = [item for item in items if not item.acknowledged]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def acknowledge(self, user_id: str, notification_id: str) -> AndroidNotificationItem:
        item = self._items[(user_id, notification_id)]
        item.acknowledged = True
        return item

    def push_targets(self, user_id: str) -> list[str]:
        return sorted(
            device.push_token
            for device in self._devices.values()
            if device.user_id == user_id and not device.revoked and device.push_token
        )
