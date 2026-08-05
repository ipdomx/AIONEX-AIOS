from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class OwnerReport:
    report_id: str
    owner_id: str
    title: str
    summary: str
    metrics: dict[str, float | int] = field(default_factory=dict)
    sections: dict[str, list[str]] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OwnerReportService:
    def __init__(self) -> None:
        self._reports: dict[str, OwnerReport] = {}

    def generate(
        self,
        *,
        report_id: str,
        owner_id: str,
        title: str,
        summary: str,
        metrics: dict[str, float | int] | None = None,
        sections: dict[str, list[str]] | None = None,
    ) -> OwnerReport:
        if report_id in self._reports:
            raise ValueError(f"duplicate report: {report_id}")
        report = OwnerReport(
            report_id=report_id,
            owner_id=owner_id,
            title=title,
            summary=summary,
            metrics=dict(metrics or {}),
            sections={name: list(items) for name, items in (sections or {}).items()},
        )
        self._reports[report_id] = report
        return report

    def get(self, report_id: str, owner_id: str) -> OwnerReport:
        report = self._reports[report_id]
        if report.owner_id != owner_id:
            raise PermissionError("report is not owned by this owner")
        return report

    def list_for_owner(self, owner_id: str) -> list[OwnerReport]:
        return sorted(
            (report for report in self._reports.values() if report.owner_id == owner_id),
            key=lambda report: report.generated_at,
            reverse=True,
        )
