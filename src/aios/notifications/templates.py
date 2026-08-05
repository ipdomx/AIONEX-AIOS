from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotificationTemplate:
    template_id: str
    subject: str
    body: str

    def render(self, context: dict[str, object]) -> tuple[str, str]:
        return self.subject.format_map(context), self.body.format_map(context)


class NotificationTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, NotificationTemplate] = {}

    def register(self, template: NotificationTemplate) -> None:
        if template.template_id in self._templates:
            raise ValueError(f"duplicate notification template: {template.template_id}")
        self._templates[template.template_id] = template

    def render(self, template_id: str, context: dict[str, object]) -> tuple[str, str]:
        try:
            template = self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"unknown notification template: {template_id}") from exc
        return template.render(context)
