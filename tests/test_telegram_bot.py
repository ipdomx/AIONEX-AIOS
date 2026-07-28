from aios.telegram_bot.auth import TelegramIdentityService
from aios.telegram_bot.client import TelegramBotClient, TelegramDelivery, TelegramMessage
from aios.telegram_bot.models import TelegramChatType, TelegramCommand, TelegramCommandState
from aios.telegram_bot.router import TelegramCommandRouter
from aios.telegram_bot.webhook import TelegramUpdate, TelegramWebhookService


class FakeTransport:
    def send_message(self, token: str, message: TelegramMessage) -> TelegramDelivery:
        return TelegramDelivery(chat_id=message.chat_id, message_id="m-1", accepted=True)

    def set_webhook(self, token: str, url: str, secret_token: str) -> bool:
        return True

    def delete_webhook(self, token: str) -> bool:
        return True


def test_identity_link_and_command_dispatch() -> None:
    identities = TelegramIdentityService()
    token = identities.issue_link_token("owner-1")
    identities.link(token=token.token, telegram_user_id="tg-1")

    router = TelegramCommandRouter(identities)
    router.register("status", lambda owner_id, args: f"{owner_id}:ok")
    command = TelegramCommand(
        command_id="c-1",
        telegram_user_id="tg-1",
        chat_id="chat-1",
        chat_type=TelegramChatType.PRIVATE,
        command="/status",
    )

    result = router.dispatch(command)
    assert result.state is TelegramCommandState.COMPLETED
    assert result.response_text == "owner-1:ok"


def test_unauthorized_command_is_rejected() -> None:
    router = TelegramCommandRouter(TelegramIdentityService())
    request = TelegramCommand(
        command_id="c-2",
        telegram_user_id="unknown",
        chat_id="chat-2",
        chat_type=TelegramChatType.PRIVATE,
        command="/status",
    )
    assert router.dispatch(request).state is TelegramCommandState.REJECTED


def test_webhook_verification_and_idempotency() -> None:
    webhook = TelegramWebhookService(secret_token="0123456789abcdef")
    assert webhook.verify("0123456789abcdef") is True
    update = TelegramUpdate(
        update_id="1",
        telegram_user_id="tg-1",
        chat_id="chat-1",
        chat_type=TelegramChatType.PRIVATE,
        text="/status now",
    )
    command = webhook.accept(update)
    assert command is not None
    assert command.arguments == ("now",)
    assert webhook.accept(update) is None


def test_client_requires_https_webhook() -> None:
    client = TelegramBotClient(token="bot-token", transport=FakeTransport())
    try:
        client.configure_webhook(url="http://example.test/hook", secret_token="0123456789abcdef")
    except ValueError:
        pass
    else:
        raise AssertionError("non-HTTPS webhook must be rejected")

    delivery = client.send(TelegramMessage(chat_id="chat-1", text="Ready"))
    assert delivery.accepted is True
