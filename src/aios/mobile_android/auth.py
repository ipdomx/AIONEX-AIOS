from __future__ import annotations

from datetime import datetime, timezone

from .models import AndroidDevice, AndroidSession, AndroidSessionState


class AndroidAuthService:
    def __init__(self) -> None:
        self._devices: dict[str, AndroidDevice] = {}
        self._sessions: dict[str, AndroidSession] = {}

    def register_device(self, device: AndroidDevice) -> AndroidDevice:
        if device.device_id in self._devices:
            raise ValueError(f"device already registered: {device.device_id}")
        self._devices[device.device_id] = device
        return device

    def create_session(self, session: AndroidSession) -> AndroidSession:
        device = self._devices.get(session.device_id)
        if device is None:
            raise KeyError(f"unknown device: {session.device_id}")
        if device.revoked:
            raise PermissionError("device is revoked")
        if device.user_id != session.user_id or device.owner_id != session.owner_id:
            raise PermissionError("session identity does not match device ownership")
        if session.session_id in self._sessions:
            raise ValueError(f"session already exists: {session.session_id}")
        self._sessions[session.session_id] = session
        return session

    def refresh(self, session_id: str, refresh_token: str, new_access_token: str) -> AndroidSession:
        session = self._sessions[session_id]
        if session.state is not AndroidSessionState.ACTIVE:
            raise RuntimeError(f"session is not active: {session.state.value}")
        if session.refresh_token != refresh_token:
            raise PermissionError("invalid refresh token")
        if session.expires_at is not None and session.expires_at <= datetime.now(timezone.utc):
            session.state = AndroidSessionState.EXPIRED
            raise RuntimeError("session expired")
        session.access_token = new_access_token
        return session

    def revoke_device(self, device_id: str, owner_id: str) -> AndroidDevice:
        device = self._devices[device_id]
        if device.owner_id != owner_id:
            raise PermissionError("device is not owned by this owner")
        device.revoked = True
        for session in self._sessions.values():
            if session.device_id == device_id:
                session.state = AndroidSessionState.REVOKED
        return device

    def touch_device(self, device_id: str) -> AndroidDevice:
        device = self._devices[device_id]
        device.last_seen_at = datetime.now(timezone.utc)
        return device
