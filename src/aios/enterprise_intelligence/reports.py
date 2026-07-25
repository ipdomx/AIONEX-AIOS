from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ReportSection:
    title: str
    data: dict[str, object]


@dataclass(frozen=True)
class Report:
    title: str
    sections: list[ReportSection]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class EnterpriseReportBuilder:
    def build(
        self,
        title: str,
        sections: list[ReportSection],
        metadata: dict[str, str] | None = None,
    ) -> Report:
        if not title.strip():
            raise ValueError("report title is required")
        if not sections:
            raise ValueError("report must contain at least one section")
        return Report(title=title, sections=list(sections), metadata=dict(metadata or {}))
