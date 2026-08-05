from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class IOSDeviceState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(slots=True)
class IOSDevice:
    device_id: str
    owner_id: str
    apns_token: str
    app_version: str
    platform_version: str
    state: IOSDeviceState = IOSDeviceState.ACTIVE
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSDeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, IOSDevice] = {}

    def register(self, device: IOSDevice) -> IOSDevice:
        existing = self._devices.get(device.device_id)
        if existing and existing.owner_id != device.owner_id:
            raise PermissionError("device belongs to another owner")
        self._devices[device.device_id] = device
        return device

    def revoke(self, device_id: str, owner_id: str) -> IOSDevice:
        device = self._devices[device_id]
        if device.owner_id != owner_id:
            raise PermissionError("device belongs to another owner")
        device.state = IOSDeviceState.REVOKED
        return device

    def active_for_owner(self, owner_id: str) -> list[IOSDevice]:
        return [d for d in self._devices.values() if d.owner_id == owner_id and d.state is IOSDeviceState.ACTIVE]
