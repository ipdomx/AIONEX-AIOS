from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from .channels import ChannelEndpoint, CommunicationChannel
from .messages import MessageState, MessageStore, OutboundMessage


@dataclass(frozen=True)
class DeliveryReceipt:
    message_id: str
    endpoint_id: str
    provider: str
    accepted: bool
    external_id: str | None = None
    error: str | None = None
    delivered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelAdapter(Protocol):
    channel: CommunicationChannel

    def send(self, message: OutboundMessage, endpoint: ChannelEndpoint) -> DeliveryReceipt:
        ...


class InMemoryChannelAdapter:
    def __init__(self, channel: CommunicationChannel) -> None:
        self.channel = channel
        self.sent: list[tuple[OutboundMessage, ChannelEndpoint]] = []

    def send(self, message: OutboundMessage, endpoint: ChannelEndpoint) -> DeliveryReceipt:
        if endpoint.channel is not self.channel:
            raise ValueError("adapter and endpoint channel mismatch")
        self.sent.append((message, endpoint))
        return DeliveryReceipt(
            message_id=message.message_id,
            endpoint_id=endpoint.endpoint_id,
            provider=f"memory-{self.channel.value}",
            accepted=True,
            external_id=f"{self.channel.value}:{message.message_id}",
        )


class DeliveryManager:
    def __init__(self, store: MessageStore) -> None:
        self.store = store
        self._adapters: dict[CommunicationChannel, ChannelAdapter] = {}
        self._receipts: list[DeliveryReceipt] = []

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        self._adapters[adapter.channel] = adapter

    def deliver(self, message_id: str, endpoint: ChannelEndpoint) -> DeliveryReceipt:
        message = self.store.get(message_id)
        try:
            adapter = self._adapters[endpoint.channel]
        except KeyError as exc:
            raise LookupError(f"adapter not registered for channel: {endpoint.channel.value}") from exc
        if message.state not in {MessageState.QUEUED, MessageState.FAILED}:
            raise ValueError(f"message is not deliverable from state: {message.state.value}")
        if message.state is MessageState.FAILED:
            message.transition(MessageState.QUEUED)
        receipt = adapter.send(message, endpoint)
        if receipt.accepted:
            message.transition(MessageState.SENT)
            message.transition(MessageState.DELIVERED)
        else:
            message.transition(MessageState.FAILED)
        self._receipts.append(receipt)
        return receipt

    def receipts_for(self, message_id: str) -> list[DeliveryReceipt]:
        return [receipt for receipt in self._receipts if receipt.message_id == message_id]
