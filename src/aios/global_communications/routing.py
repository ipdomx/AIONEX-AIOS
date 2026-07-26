from __future__ import annotations

from dataclasses import dataclass, field

from .channels import ChannelEndpoint, ChannelRegistry, CommunicationChannel
from .messages import MessagePriority, OutboundMessage


@dataclass(frozen=True)
class RoutingPolicy:
    policy_id: str
    owner_id: str
    preferred_channels: tuple[CommunicationChannel, ...]
    minimum_priority: MessagePriority = MessagePriority.LOW
    require_verified: bool = True
    project_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class CommunicationRouter:
    def __init__(self, registry: ChannelRegistry) -> None:
        self.registry = registry
        self._policies: dict[str, RoutingPolicy] = {}

    def add_policy(self, policy: RoutingPolicy) -> RoutingPolicy:
        if not policy.policy_id.strip() or not policy.owner_id.strip():
            raise ValueError("policy_id and owner_id are required")
        if not policy.preferred_channels:
            raise ValueError("preferred_channels cannot be empty")
        self._policies[policy.policy_id] = policy
        return policy

    def route(self, message: OutboundMessage, owner_id: str) -> ChannelEndpoint:
        candidates = self.registry.list_for_owner(owner_id)
        policies = [policy for policy in self._policies.values() if policy.owner_id == owner_id]
        policies.sort(key=lambda policy: policy.project_id is None)
        for policy in policies:
            if policy.project_id is not None and policy.project_id != message.project_id:
                continue
            if self._priority_rank(message.priority) < self._priority_rank(policy.minimum_priority):
                continue
            endpoint = self._select(candidates, policy)
            if endpoint is not None:
                return endpoint
        direct = [item for item in candidates if item.channel is message.channel]
        if direct:
            return direct[0]
        raise LookupError(f"no routable endpoint found for owner: {owner_id}")

    @staticmethod
    def _select(candidates: list[ChannelEndpoint], policy: RoutingPolicy) -> ChannelEndpoint | None:
        for channel in policy.preferred_channels:
            for endpoint in candidates:
                if endpoint.channel is not channel:
                    continue
                if policy.require_verified and not endpoint.verified:
                    continue
                return endpoint
        return None

    @staticmethod
    def _priority_rank(priority: MessagePriority) -> int:
        return {
            MessagePriority.LOW: 0,
            MessagePriority.NORMAL: 1,
            MessagePriority.HIGH: 2,
            MessagePriority.CRITICAL: 3,
        }[priority]
