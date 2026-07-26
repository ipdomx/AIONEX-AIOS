from __future__ import annotations

from dataclasses import dataclass

from .channels import ChannelRegistry, CommunicationChannel
from .delivery import DeliveryManager, InMemoryChannelAdapter
from .messages import MessageStore
from .routing import CommunicationRouter
from .templates import TemplateEngine


@dataclass
class GlobalCommunicationsPlatform:
    channels: ChannelRegistry
    messages: MessageStore
    router: CommunicationRouter
    delivery: DeliveryManager
    templates: TemplateEngine

    @classmethod
    def build_default(cls) -> "GlobalCommunicationsPlatform":
        channels = ChannelRegistry()
        messages = MessageStore()
        router = CommunicationRouter(channels)
        delivery = DeliveryManager(messages)
        for channel in CommunicationChannel:
            delivery.register_adapter(InMemoryChannelAdapter(channel))
        return cls(
            channels=channels,
            messages=messages,
            router=router,
            delivery=delivery,
            templates=TemplateEngine(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "channel_registry": self.channels is not None,
            "message_store": self.messages is not None,
            "communication_router": self.router is not None,
            "delivery_manager": self.delivery is not None,
            "template_engine": self.templates is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
