from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class CommunicationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    PUSH = "push"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class ChannelEndpoint:
    endpoint_id: str
    owner_id: str
    channel: CommunicationChannel
    address: str
    verified: bool = False
    enabled: bool = True
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelRegistry:
    def __init__(self) -> None:
        self._endpoints: dict[str, ChannelEndpoint] = {}

    def register(self, endpoint: ChannelEndpoint) -> ChannelEndpoint:
        if not endpoint.endpoint_id.strip() or not endpoint.owner_id.strip():
            raise ValueError("endpoint_id and owner_id are required")
        if not endpoint.address.strip():
            raise ValueError("endpoint address is required")
        self._endpoints[endpoint.endpoint_id] = endpoint
        return endpoint

    def get(self, endpoint_id: str) -> ChannelEndpoint:
        try:
            return self._endpoints[endpoint_id]
        except KeyError as exc:
            raise LookupError(f"endpoint not found: {endpoint_id}") from exc

    def list_for_owner(self, owner_id: str, enabled_only: bool = True) -> list[ChannelEndpoint]:
        items = [item for item in self._endpoints.values() if item.owner_id == owner_id]
        if enabled_only:
            items = [item for item in items if item.enabled]
        return items

    def list_by_channel(self, channel: CommunicationChannel) -> list[ChannelEndpoint]:
        return [item for item in self._endpoints.values() if item.channel is channel]
