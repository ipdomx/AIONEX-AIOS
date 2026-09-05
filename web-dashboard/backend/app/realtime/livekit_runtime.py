"""Activated Phase 36H LiveKit/Coturn runtime bridge.

The static LiveKit API secret and Coturn shared secret are never returned or
persisted in the database. Authorized users receive only short-lived LiveKit
participant JWTs and TURN REST credentials scoped to one admission.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

from app.core.config import settings
from app.realtime.sfu import SFURoomPlan, build_livekit_room_plan


class RealtimeProviderUnavailable(RuntimeError):
    """The realtime provider runtime is disabled or unavailable."""


class RealtimeProviderProtocolError(RuntimeError):
    """The provider returned an invalid or rejected control-plane response."""


@dataclass(frozen=True, slots=True)
class ParticipantSession:
    token: str
    token_jti_sha256: str
    expires_at: datetime
    server_url: str
    ice_servers: tuple[dict[str, Any], ...]

    def response_payload(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "expires_at": self.expires_at.isoformat(),
            "server_url": self.server_url,
            "ice_servers": [dict(item) for item in self.ice_servers],
            "provider": "livekit",
        }


@dataclass(frozen=True, slots=True)
class ProviderEgressState:
    egress_id: str
    status: str
    error: str | None
    file_results: tuple[dict[str, Any], ...]

    @property
    def terminal(self) -> bool:
        return self.status in {"EGRESS_COMPLETE", "EGRESS_FAILED", "EGRESS_ABORTED"}

    @property
    def completed(self) -> bool:
        return self.status == "EGRESS_COMPLETE" and not self.error


def _read_secret(path_text: str, *, label: str) -> str:
    path = Path(path_text)
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise RealtimeProviderUnavailable(f"{label} secret file is unavailable") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RealtimeProviderUnavailable(f"{label} secret path must be a regular file")
    if st.st_mode & 0o077:
        raise RealtimeProviderUnavailable(f"{label} secret file must not be group/world accessible")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RealtimeProviderUnavailable(f"{label} secret file cannot be read") from exc
    if not 12 <= len(value) <= 4096:
        raise RealtimeProviderUnavailable(f"{label} secret file content is invalid")
    return value


def _validated_signaling_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "wss" or not parsed.hostname or parsed.username or parsed.password:
        raise RealtimeProviderUnavailable("realtime signaling URL must be a credential-free wss URL")
    if parsed.query or parsed.fragment:
        raise RealtimeProviderUnavailable("realtime signaling URL must not contain query or fragment")
    return value.strip().rstrip("/")


def _validated_internal_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise RealtimeProviderUnavailable("LiveKit internal API URL must be credential-free HTTP")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise RealtimeProviderUnavailable("LiveKit internal API URL must be an origin only")
    # Prevent configuration drift from turning the privileged Twirp client into an
    # arbitrary external HTTP client. Production uses the fixed Docker DNS name.
    if parsed.hostname not in {"realtime-livekit", "localhost", "127.0.0.1"}:
        raise RealtimeProviderUnavailable("LiveKit internal API host is not allowlisted")
    return value.strip().rstrip("/")


def _validated_turn_host(value: str) -> str:
    host = value.strip()
    if not host or any(char in host for char in "/?#@[]"):
        raise RealtimeProviderUnavailable("TURN public host is invalid")
    return host


class LiveKitRuntime:
    provider = "livekit"

    def __init__(self) -> None:
        self._signaling_url = _validated_signaling_url(settings.REALTIME_SIGNALING_URL)
        self._internal_url = _validated_internal_url(settings.REALTIME_LIVEKIT_INTERNAL_URL)
        self._turn_host = _validated_turn_host(settings.REALTIME_TURN_PUBLIC_HOST)
        self._turn_port = settings.REALTIME_TURN_PORT

    @property
    def enabled(self) -> bool:
        return bool(settings.REALTIME_MEDIA_LIVE_ENABLED)

    def require_enabled(self) -> None:
        if not self.enabled:
            raise RealtimeProviderUnavailable("realtime media runtime is not activated")

    def readiness_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": "livekit",
            "signaling_url": self._signaling_url if self.enabled else None,
            "turn_host_configured": bool(self._turn_host and self._turn_host != "127.0.0.1"),
            "turn_port": self._turn_port if self.enabled else None,
            "static_provider_credentials_returned": False,
            "short_lived_participant_credentials": True,
            "recording_provider": "livekit-egress",
        }

    def plan_room(
        self, *, organization_id: str, room_id: str, max_participants: int
    ) -> SFURoomPlan:
        self.require_enabled()
        return build_livekit_room_plan(
            organization_id=organization_id,
            room_id=room_id,
            max_participants=max_participants,
            signaling_url=self._signaling_url,
            provider_mutation_allowed=True,
        )

    def _api_credentials(self) -> tuple[str, str]:
        self.require_enabled()
        return (
            _read_secret(settings.REALTIME_LIVEKIT_API_KEY_FILE, label="LiveKit API key"),
            _read_secret(settings.REALTIME_LIVEKIT_API_SECRET_FILE, label="LiveKit API secret"),
        )

    def _admin_token(self, video_grant: dict[str, Any], *, ttl_seconds: int = 90) -> str:
        key, secret = self._api_credentials()
        now = int(time.time())
        return jwt.encode(
            {
                "iss": key,
                "nbf": now - 5,
                "exp": now + ttl_seconds,
                "jti": uuid.uuid4().hex,
                "video": video_grant,
            },
            secret,
            algorithm="HS256",
        )

    async def _twirp(
        self,
        *,
        service: str,
        method: str,
        payload: dict[str, Any],
        video_grant: dict[str, Any],
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        token = self._admin_token(video_grant)
        url = f"{self._internal_url}/twirp/livekit.{service}/{method}"
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise RealtimeProviderUnavailable("LiveKit control plane is unavailable") from exc
        if response.status_code >= 400:
            code = "provider_rejected"
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("code"), str):
                    code = str(body["code"])[:80]
            except ValueError:
                body = {}
            raise RealtimeProviderProtocolError(
                f"LiveKit {method} failed with HTTP {response.status_code} ({code})"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RealtimeProviderProtocolError("LiveKit returned non-JSON control response") from exc
        if not isinstance(body, dict):
            raise RealtimeProviderProtocolError("LiveKit returned invalid control response")
        return body

    async def provision_room(self, plan: SFURoomPlan) -> dict[str, Any]:
        if not plan.provider_mutation_allowed:
            raise RealtimeProviderUnavailable("provider room plan is not mutation-authorized")
        return await self._twirp(
            service="RoomService",
            method="CreateRoom",
            payload={
                "name": plan.provider_room_name,
                "emptyTimeout": 300,
                "departureTimeout": 20,
                "maxParticipants": plan.max_participants,
            },
            video_grant={"roomCreate": True, "roomAdmin": True},
        )

    @staticmethod
    def _room_service_admin_grant() -> dict[str, bool]:
        # LiveKit 1.13.x RoomService admin mutations require the complete
        # server-side room administration grant profile. This token is only
        # used on the private Docker control plane and is never returned to a
        # participant or persisted.
        return {
            "roomCreate": True,
            "roomList": True,
            "roomAdmin": True,
            "roomRecord": True,
        }

    async def delete_room(self, provider_room_name: str) -> None:
        await self._twirp(
            service="RoomService",
            method="DeleteRoom",
            payload={"room": provider_room_name},
            video_grant=self._room_service_admin_grant(),
        )

    async def remove_participant(
        self, *, provider_room_name: str, participant_identity: str
    ) -> None:
        await self._twirp(
            service="RoomService",
            method="RemoveParticipant",
            payload={"room": provider_room_name, "identity": participant_identity},
            video_grant=self._room_service_admin_grant(),
        )

    def participant_session(
        self,
        *,
        room_name: str,
        participant_id: str,
        participant_name: str,
        can_publish: bool,
        can_subscribe: bool,
        can_publish_data: bool = True,
    ) -> ParticipantSession:
        key, secret = self._api_credentials()
        now = int(time.time())
        expires = now + settings.REALTIME_PROVIDER_TOKEN_TTL_SECONDS
        jti = uuid.uuid4().hex
        token = jwt.encode(
            {
                "iss": key,
                "sub": participant_id,
                "name": participant_name[:200],
                "nbf": now - 5,
                "exp": expires,
                "jti": jti,
                "video": {
                    "roomJoin": True,
                    "room": room_name,
                    "canPublish": can_publish,
                    "canSubscribe": can_subscribe,
                    "canPublishData": can_publish_data,
                },
            },
            secret,
            algorithm="HS256",
        )
        turn_secret = _read_secret(
            settings.REALTIME_TURN_SHARED_SECRET_FILE, label="Coturn shared"
        )
        turn_expiry = int(time.time()) + settings.REALTIME_TURN_CREDENTIAL_TTL_SECONDS
        turn_username = f"{turn_expiry}:{participant_id}"
        turn_password = base64.b64encode(
            hmac.new(
                turn_secret.encode("utf-8"),
                turn_username.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")
        host = self._turn_host
        port = self._turn_port
        ice_servers = (
            {"urls": [f"stun:{host}:{port}"]},
            {
                "urls": [
                    f"turn:{host}:{port}?transport=udp",
                    f"turn:{host}:{port}?transport=tcp",
                ],
                "username": turn_username,
                "credential": turn_password,
                "credentialType": "password",
            },
        )
        return ParticipantSession(
            token=token,
            token_jti_sha256=hashlib.sha256(jti.encode("utf-8")).hexdigest(),
            expires_at=datetime.fromtimestamp(expires, tz=UTC),
            server_url=self._signaling_url,
            ice_servers=ice_servers,
        )

    async def start_room_recording(
        self, *, provider_room_name: str, output_relpath: str
    ) -> ProviderEgressState:
        if not output_relpath.endswith(".mp4") or "/" in output_relpath or "\\" in output_relpath:
            raise RealtimeProviderProtocolError("recording output path is invalid")
        body = await self._twirp(
            service="Egress",
            method="StartRoomCompositeEgress",
            payload={
                "roomName": provider_room_name,
                "layout": "grid",
                "fileOutputs": [
                    {"fileType": "MP4", "filepath": f"/recordings/{output_relpath}"}
                ],
            },
            video_grant={"roomRecord": True, "room": provider_room_name},
            timeout_seconds=15.0,
        )
        return self._egress_state(body)

    async def list_egress(self, *, egress_id: str) -> ProviderEgressState:
        body = await self._twirp(
            service="Egress",
            method="ListEgress",
            payload={"egressId": egress_id},
            video_grant={"roomRecord": True},
            timeout_seconds=10.0,
        )
        items = body.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise RealtimeProviderProtocolError("LiveKit egress state is unavailable")
        return self._egress_state(items[0])

    async def stop_egress(self, *, egress_id: str) -> ProviderEgressState:
        body = await self._twirp(
            service="Egress",
            method="StopEgress",
            payload={"egressId": egress_id},
            video_grant={"roomRecord": True},
            timeout_seconds=15.0,
        )
        return self._egress_state(body)

    @staticmethod
    def _egress_state(body: dict[str, Any]) -> ProviderEgressState:
        egress_id = str(body.get("egressId") or body.get("egress_id") or "").strip()
        if not egress_id:
            raise RealtimeProviderProtocolError("LiveKit egress response omitted egress ID")
        raw_status = body.get("status")
        status_text = str(raw_status or "EGRESS_STARTING")
        # Twirp JSON normally returns enum names, but keep the numeric mapping for
        # compatibility with alternate protobuf JSON gateways.
        numeric = {
            "0": "EGRESS_STARTING",
            "1": "EGRESS_ACTIVE",
            "2": "EGRESS_ENDING",
            "3": "EGRESS_COMPLETE",
            "4": "EGRESS_FAILED",
            "5": "EGRESS_ABORTED",
            "6": "EGRESS_LIMIT_REACHED",
        }
        status_text = numeric.get(status_text, status_text)
        error = body.get("error")
        file_results = body.get("fileResults") or body.get("file_results") or []
        safe_results: list[dict[str, Any]] = []
        if isinstance(file_results, list):
            for result in file_results:
                if not isinstance(result, dict):
                    continue
                safe_results.append(
                    {
                        "duration": result.get("duration"),
                        "size": result.get("size"),
                        "filename": Path(str(result.get("filename") or "")).name,
                    }
                )
        return ProviderEgressState(
            egress_id=egress_id,
            status=status_text,
            error=str(error)[:1000] if error else None,
            file_results=tuple(safe_results),
        )

    def recording_path(self, output_relpath: str) -> Path:
        root = Path(settings.REALTIME_RECORDING_ROOT).resolve()
        candidate = (root / output_relpath).resolve()
        if candidate.parent != root:
            raise RealtimeProviderProtocolError("recording output escaped protected root")
        return candidate

    @staticmethod
    def retention_deadline(days: int) -> datetime:
        if not 1 <= days <= 90:
            raise ValueError("recording retention must be between 1 and 90 days")
        return datetime.now(UTC) + timedelta(days=days)


livekit_runtime = LiveKitRuntime()
