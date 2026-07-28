from __future__ import annotations

from .models import AndroidProjectSummary


class AndroidProjectService:
    def __init__(self) -> None:
        self._projects: dict[tuple[str, str], AndroidProjectSummary] = {}

    def upsert(self, owner_id: str, summary: AndroidProjectSummary) -> AndroidProjectSummary:
        if not 0 <= summary.progress_percent <= 100:
            raise ValueError("progress_percent must be between 0 and 100")
        if summary.open_tasks < 0 or summary.open_incidents < 0:
            raise ValueError("project counters must be non-negative")
        self._projects[(owner_id, summary.project_id)] = summary
        return summary

    def get(self, owner_id: str, project_id: str) -> AndroidProjectSummary:
        try:
            return self._projects[(owner_id, project_id)]
        except KeyError as exc:
            raise KeyError(f"unknown project for owner: {project_id}") from exc

    def list_for_owner(self, owner_id: str) -> list[AndroidProjectSummary]:
        return sorted(
            (
                summary
                for (stored_owner_id, _), summary in self._projects.items()
                if stored_owner_id == owner_id
            ),
            key=lambda summary: summary.updated_at,
            reverse=True,
        )
