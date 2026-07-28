from datetime import datetime, timedelta, timezone

from aios.notifications.models import NotificationChannel
from aios.notifications.preferences import NotificationPreferenceStore, NotificationPreferences
from aios.notifications.retry import NotificationRetryManager
from aios.notifications.templates import NotificationTemplate, NotificationTemplateRegistry


def test_preferences_enforce_channels_and_muted_topics() -> None:
    store = NotificationPreferenceStore()
    preferences = store.save(
        NotificationPreferences(
            recipient_id="user-1",
            enabled_channels={NotificationChannel.IN_APP, NotificationChannel.EMAIL},
            muted_topics={"marketing"},
        )
    )

    assert preferences.allows(NotificationChannel.EMAIL, "project") is True
    assert preferences.allows(NotificationChannel.EMAIL, "marketing") is False
    assert preferences.allows(NotificationChannel.PUSH, "project") is False
    assert store.get("user-1") is preferences


def test_templates_render_context_and_reject_duplicates() -> None:
    registry = NotificationTemplateRegistry()
    registry.register(
        NotificationTemplate(
            template_id="project-complete",
            subject="Project {project_id} completed",
            body="Hello {name}, your project is ready.",
        )
    )

    subject, body = registry.render(
        "project-complete",
        {"project_id": "p-1", "name": "Ahmed"},
    )
    assert subject == "Project p-1 completed"
    assert body == "Hello Ahmed, your project is ready."


def test_retry_backoff_and_dead_letter_lifecycle() -> None:
    manager = NotificationRetryManager(base_delay_seconds=1)
    first = manager.register_failure("delivery-1", "timeout", max_attempts=2)
    assert first.attempts == 1
    assert first.dead_lettered is False

    due_at = datetime.now(timezone.utc) + timedelta(seconds=2)
    assert manager.due(due_at)[0].delivery_id == "delivery-1"

    second = manager.register_failure("delivery-1", "provider unavailable", max_attempts=2)
    assert second.dead_lettered is True
    assert manager.dead_letters()[0].delivery_id == "delivery-1"

    manager.mark_success("delivery-1")
    assert manager.dead_letters() == []
