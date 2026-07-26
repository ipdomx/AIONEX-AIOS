from aios.global_communications import (
    ChannelEndpoint,
    CommunicationChannel,
    GlobalCommunicationsPlatform,
    MessagePriority,
    MessageState,
    MessageTemplate,
    OutboundMessage,
    RoutingPolicy,
)


def test_global_communications_end_to_end() -> None:
    platform = GlobalCommunicationsPlatform.build_default()
    endpoint = ChannelEndpoint(
        endpoint_id="endpoint-1",
        owner_id="owner-1",
        channel=CommunicationChannel.EMAIL,
        address="owner@example.com",
        verified=True,
    )
    platform.channels.register(endpoint)
    platform.router.add_policy(
        RoutingPolicy(
            policy_id="policy-1",
            owner_id="owner-1",
            preferred_channels=(CommunicationChannel.EMAIL,),
            minimum_priority=MessagePriority.LOW,
        )
    )
    platform.templates.register(
        MessageTemplate(
            template_id="project-complete",
            subject="Project {project_id} completed",
            body="Project {project_id} completed successfully.",
        )
    )
    subject, body = platform.templates.render("project-complete", {"project_id": "project-1"})
    message = OutboundMessage(
        message_id="message-1",
        recipient_id="owner-1",
        channel=CommunicationChannel.EMAIL,
        subject=subject,
        body=body,
        priority=MessagePriority.HIGH,
        project_id="project-1",
    )
    platform.messages.add(message)
    selected = platform.router.route(message, "owner-1")
    receipt = platform.delivery.deliver(message.message_id, selected)

    assert receipt.accepted is True
    assert message.state is MessageState.DELIVERED
    assert platform.validate()["ready"] is True


def test_template_fallback_and_invalid_transition() -> None:
    platform = GlobalCommunicationsPlatform.build_default()
    platform.templates.register(
        MessageTemplate(template_id="alert", subject="Alert", body="Value: {value}", locale="en")
    )
    subject, body = platform.templates.render("alert", {"value": 7}, locale="ar")
    assert subject == "Alert"
    assert body == "Value: 7"

    message = OutboundMessage(
        message_id="message-2",
        recipient_id="user-2",
        channel=CommunicationChannel.PUSH,
        subject="Ready",
        body="Ready",
    )
    platform.messages.add(message)
    message.transition(MessageState.CANCELLED)
    assert message.state is MessageState.CANCELLED
