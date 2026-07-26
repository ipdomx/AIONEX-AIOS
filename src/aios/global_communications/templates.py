from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MessageTemplate:
    template_id: str
    subject: str
    body: str
    locale: str = "en"
    metadata: dict[str, str] = field(default_factory=dict)


class TemplateEngine:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], MessageTemplate] = {}

    def register(self, template: MessageTemplate) -> MessageTemplate:
        if not template.template_id.strip():
            raise ValueError("template_id is required")
        self._templates[(template.template_id, template.locale)] = template
        return template

    def get(self, template_id: str, locale: str = "en") -> MessageTemplate:
        key = (template_id, locale)
        if key in self._templates:
            return self._templates[key]
        fallback = (template_id, "en")
        try:
            return self._templates[fallback]
        except KeyError as exc:
            raise LookupError(f"template not found: {template_id}/{locale}") from exc

    def render(self, template_id: str, values: dict[str, object], locale: str = "en") -> tuple[str, str]:
        template = self.get(template_id, locale)
        try:
            return template.subject.format_map(values), template.body.format_map(values)
        except KeyError as exc:
            raise ValueError(f"missing template value: {exc.args[0]}") from exc
