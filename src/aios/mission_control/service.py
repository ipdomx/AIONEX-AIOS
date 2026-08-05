from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Iterable

from .domain import (
    ApprovalRequest,
    CommandRecord,
    CommandStatus,
    IncidentSnapshot,
    MissionControlSnapshot,
    OwnerCommand,
    OwnerScope,
    ProjectSnapshot,
)


class AuthorizationError(PermissionError):
    pass


class CommandConflictError(RuntimeError):
    pass


class MissionControlService:
    def __init__(self) -> None:
        self._commands: dict[str, CommandRecord] = {}
        self._lock = RLock()

    def submit_command(self, scope: OwnerScope, command: OwnerCommand) -> CommandRecord:
        if command.owner_id != scope.owner_id:
            raise AuthorizationError("owner identity does not match scope")
        self._authorize_target(scope, command.target_type, command.target_id)
        with self._lock:
            if command.command_id in self._commands:
                raise CommandConflictError(f"command already exists: {command.command_id}")
            record = CommandRecord(command=command)
            self._commands[command.command_id] = record
            return replace(record)

    def approve_command(self, scope: OwnerScope, command_id: str, actor_id: str) -> CommandRecord:
        if actor_id != scope.owner_id and not scope.can_override_approvals:
            raise AuthorizationError("actor cannot approve owner commands")
        with self._lock:
            record = self._require_command(command_id)
            if record.status is not CommandStatus.PENDING:
                raise CommandConflictError("only pending commands can be approved")
            record.status = CommandStatus.APPROVED
            record.approved_by = actor_id
            record.updated_at = datetime.now(timezone.utc)
            return replace(record)

    def reject_command(
        self,
        scope: OwnerScope,
        command_id: str,
        actor_id: str,
        reason: str,
    ) -> CommandRecord:
        if actor_id != scope.owner_id and not scope.can_override_approvals:
            raise AuthorizationError("actor cannot reject owner commands")
        if not reason.strip():
            raise ValueError("rejection reason is required")
        with self._lock:
            record = self._require_command(command_id)
            if record.status is not CommandStatus.PENDING:
                raise CommandConflictError("only pending commands can be rejected")
            record.status = CommandStatus.REJECTED
            record.rejection_reason = reason.strip()
            record.updated_at = datetime.now(timezone.utc)
            return replace(record)

    def start_command(self, command_id: str) -> CommandRecord:
        with self._lock:
            record = self._require_command(command_id)
            if record.status is not CommandStatus.APPROVED:
                raise CommandConflictError("command must be approved before execution")
            record.status = CommandStatus.EXECUTING
            record.updated_at = datetime.now(timezone.utc)
            return replace(record)

    def complete_command(self, command_id: str, result: dict) -> CommandRecord:
        with self._lock:
            record = self._require_command(command_id)
            if record.status is not CommandStatus.EXECUTING:
                raise CommandConflictError("only executing commands can complete")
            record.status = CommandStatus.COMPLETED
            record.result = dict(result)
            record.updated_at = datetime.now(timezone.utc)
            return replace(record)

    def fail_command(self, command_id: str, result: dict) -> CommandRecord:
        with self._lock:
            record = self._require_command(command_id)
            if record.status is not CommandStatus.EXECUTING:
                raise CommandConflictError("only executing commands can fail")
            record.status = CommandStatus.FAILED
            record.result = dict(result)
            record.updated_at = datetime.now(timezone.utc)
            return replace(record)

    def get_command(self, command_id: str) -> CommandRecord:
        with self._lock:
            return replace(self._require_command(command_id))

    @staticmethod
    def build_snapshot(
        scope: OwnerScope,
        projects: Iterable[ProjectSnapshot],
        incidents: Iterable[IncidentSnapshot],
        approvals: Iterable[ApprovalRequest],
        *,
        active_workers: int,
        unhealthy_workers: int,
        queued_tasks: int,
        running_tasks: int,
        completed_tasks_24h: int,
        failed_tasks_24h: int,
    ) -> MissionControlSnapshot:
        visible_projects = tuple(
            project
            for project in projects
            if project.project_id in scope.project_ids
            or project.organization_id in scope.organization_ids
        )
        visible_project_ids = {project.project_id for project in visible_projects}
        visible_incidents = tuple(
            incident
            for incident in incidents
            if scope.can_view_all_incidents
            or incident.project_id is None
            or incident.project_id in visible_project_ids
        )
        visible_approvals = tuple(
            approval
            for approval in approvals
            if approval.subject_type != "project"
            or approval.subject_id in visible_project_ids
        )
        return MissionControlSnapshot(
            generated_at=datetime.now(timezone.utc),
            projects=visible_projects,
            incidents=visible_incidents,
            pending_approvals=visible_approvals,
            active_workers=max(active_workers, 0),
            unhealthy_workers=max(unhealthy_workers, 0),
            queued_tasks=max(queued_tasks, 0),
            running_tasks=max(running_tasks, 0),
            completed_tasks_24h=max(completed_tasks_24h, 0),
            failed_tasks_24h=max(failed_tasks_24h, 0),
        )

    @staticmethod
    def _authorize_target(scope: OwnerScope, target_type: str, target_id: str) -> None:
        if target_type == "project" and target_id not in scope.project_ids:
            raise AuthorizationError("project is outside owner scope")
        if target_type == "organization" and target_id not in scope.organization_ids:
            raise AuthorizationError("organization is outside owner scope")

    def _require_command(self, command_id: str) -> CommandRecord:
        try:
            return self._commands[command_id]
        except KeyError as exc:
            raise KeyError(f"unknown command: {command_id}") from exc
