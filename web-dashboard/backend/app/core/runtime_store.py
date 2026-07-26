"""Shared in-memory operational store for dashboard runtime entities.

This module centralizes non-identity dashboard state so endpoints expose consistent,
scoped, mutable data instead of independent mock payloads.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_urlsafe(8)}"


@dataclass
class RuntimeStore:
    workspaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    workflows: dict[str, dict[str, Any]] = field(default_factory=dict)
    meetings: dict[str, dict[str, Any]] = field(default_factory=dict)
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    activities: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.workspaces:
            return
        self._bootstrap()

    def _bootstrap(self) -> None:
        workspace_id = "workspace-engineering"
        self.workspaces[workspace_id] = {
            "id": workspace_id,
            "name": "Engineering",
            "slug": "engineering",
            "organization_id": "aionex-org",
            "description": "Core engineering workspace",
            "status": "active",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }

        project_id = "project-aios-runtime"
        self.projects[project_id] = {
            "id": project_id,
            "name": "AIOS Runtime Consolidation",
            "slug": "aios-runtime-consolidation",
            "description": "Production runtime integration across dashboard modules.",
            "status": "active",
            "priority": "critical",
            "progress": 72,
            "workspace_id": workspace_id,
            "workspace": "Engineering",
            "organization_id": "aionex-org",
            "organization": "AIONEX Corp",
            "owner_id": "owner-1",
            "owner": "AIONEX Owner",
            "team": [{"id": "owner-1", "name": "AIONEX Owner", "role": "Super Owner"}],
            "team_count": 1,
            "task_count": 2,
            "start_date": utcnow(),
            "end_date": None,
            "tags": ["runtime", "dashboard", "production"],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "deleted": False,
        }

        task_one = "task-runtime-api"
        task_two = "task-runtime-ui"
        self.tasks[task_one] = {
            "id": task_one,
            "title": "Complete runtime API integration",
            "description": "Replace isolated mock endpoints with shared operational state.",
            "status": "in_progress",
            "priority": "critical",
            "assignee_id": "owner-1",
            "assignee": "AIONEX Owner",
            "project_id": project_id,
            "project": "AIOS Runtime Consolidation",
            "workspace_id": workspace_id,
            "organization_id": "aionex-org",
            "due_date": None,
            "tags": ["backend", "api"],
            "comments": [],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "deleted": False,
        }
        self.tasks[task_two] = {
            "id": task_two,
            "title": "Connect operational dashboard pages",
            "description": "Expose consistent live data to dashboard views.",
            "status": "todo",
            "priority": "high",
            "assignee_id": "owner-1",
            "assignee": "AIONEX Owner",
            "project_id": project_id,
            "project": "AIOS Runtime Consolidation",
            "workspace_id": workspace_id,
            "organization_id": "aionex-org",
            "due_date": None,
            "tags": ["frontend", "dashboard"],
            "comments": [],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "deleted": False,
        }

        workflow_id = "workflow-release-gate"
        self.workflows[workflow_id] = {
            "id": workflow_id,
            "name": "Release Quality Gate",
            "description": "Runs validation, approval, and release readiness checks.",
            "status": "active",
            "organization_id": "aionex-org",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "trigger": "manual",
            "steps": [
                {"id": "validate", "name": "Validate", "type": "validation", "status": "ready"},
                {"id": "approve", "name": "Owner approval", "type": "approval", "status": "pending"},
                {"id": "release", "name": "Release", "type": "deployment", "status": "blocked"},
            ],
            "run_count": 0,
            "last_run_at": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "deleted": False,
        }

        meeting_id = "meeting-runtime-review"
        self.meetings[meeting_id] = {
            "id": meeting_id,
            "title": "Runtime Review",
            "description": "Owner review of runtime integration readiness.",
            "status": "scheduled",
            "organization_id": "aionex-org",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "organizer_id": "owner-1",
            "organizer": "AIONEX Owner",
            "attendee_ids": ["owner-1"],
            "start_time": utcnow(),
            "end_time": None,
            "location": "AIOS Control Center",
            "approved_by_owner": True,
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "deleted": False,
        }

        report_id = "report-runtime-status"
        self.reports[report_id] = {
            "id": report_id,
            "name": "Runtime Status Report",
            "type": "operations",
            "organization_id": "aionex-org",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "status": "ready",
            "generated_by": "owner-1",
            "summary": "Runtime integration is active and progressing through consolidated batches.",
            "metrics": {"progress": 72, "open_tasks": 2, "active_workflows": 1},
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }

        self.add_activity("system", "Runtime data initialized", "Operational store bootstrapped.", "owner-1")

    def add_activity(self, activity_type: str, title: str, description: str, user_id: str) -> dict[str, Any]:
        item = {
            "id": new_id("activity"),
            "type": activity_type,
            "title": title,
            "description": description,
            "user_id": user_id,
            "user": "AIONEX Owner" if user_id == "owner-1" else user_id,
            "timestamp": utcnow(),
        }
        self.activities.insert(0, item)
        return item


runtime_store = RuntimeStore()
