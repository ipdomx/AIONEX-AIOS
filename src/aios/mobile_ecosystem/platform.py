from __future__ import annotations

from dataclasses import dataclass

from .devices import DeviceRegistry
from .notifications import MobileNotificationCenter
from .sessions import MobileSessionManager
from .sync import MobileSyncEngine


@dataclass
class MobileEcosystemPlatform:
    devices: DeviceRegistry
    notifications: MobileNotificationCenter
    sessions: MobileSessionManager
    sync: MobileSyncEngine

    @classmethod
    def build_default(cls) -> "MobileEcosystemPlatform":
        return cls(
            devices=DeviceRegistry(),
            notifications=MobileNotificationCenter(),
            sessions=MobileSessionManager(),
            sync=MobileSyncEngine(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "device_registry": self.devices is not None,
            "notification_center": self.notifications is not None,
            "session_manager": self.sessions is not None,
            "sync_engine": self.sync is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
