from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DevicePlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


@dataclass(frozen=True)
class DeviceRegistration:
    device_id: str
    user_id: str
    platform: DevicePlatform
    push_token: str | None = None
    app_version: str | None = None
    locale: str | None = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, DeviceRegistration] = {}

    def register(self, registration: DeviceRegistration) -> DeviceRegistration:
        if not registration.device_id.strip() or not registration.user_id.strip():
            raise ValueError("device_id and user_id are required")
        self._devices[registration.device_id] = registration
        return registration

    def unregister(self, device_id: str) -> bool:
        return self._devices.pop(device_id, None) is not None

    def get(self, device_id: str) -> DeviceRegistration:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise LookupError(f"device not found: {device_id}") from exc

    def list_for_user(self, user_id: str) -> list[DeviceRegistration]:
        return [device for device in self._devices.values() if device.user_id == user_id]

    def count(self) -> int:
        return len(self._devices)
