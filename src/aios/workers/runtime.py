from __future__ import annotations

import json
import fcntl
import hashlib
import os
import stat
from pathlib import Path

from aios.academy import Academy
from aios.hr import CareerSystem, EmploymentState
from aios.workforce_health import OperationalHealthInstitute

from .models import Assignment, AssignmentState, PerformanceEvent, WorkRequest


class WorkerRuntime:
    """Assigns and supervises digital workers without bypassing career, training, or health gates."""

    def __init__(
        self,
        careers: CareerSystem,
        academy: Academy,
        health: OperationalHealthInstitute,
        ledger_path: str | Path | None = None,
    ) -> None:
        self.careers = careers
        self.academy = academy
        self.health = health
        self._assignments: dict[str, Assignment] = {}
        self._events: list[PerformanceEvent] = []
        self.ledger_path = Path(ledger_path) if ledger_path else None
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def eligible_workers(self, request: WorkRequest) -> tuple[str, ...]:
        matches: list[tuple[int, int, str]] = []
        needed = set(request.required_skills)
        for record in self.careers.list():
            if record.ministry_id != request.ministry_id:
                continue
            if record.state not in {EmploymentState.ACTIVE, EmploymentState.SUPERVISED}:
                continue
            if not needed.issubset(record.skills):
                continue
            report = self.health.latest_report(record.employee_id)
            latest_health = report.operational_health if report is not None else 100.0
            matches.append((record.success_count - record.failure_count, int(latest_health), record.employee_id))
        matches.sort(reverse=True)
        return tuple(item[2] for item in matches)

    def assign(self, request: WorkRequest, *, reviewer_id: str | None = None) -> Assignment:
        eligible = self.eligible_workers(request)
        if not eligible:
            raise LookupError('no eligible certified worker satisfies the request')
        assignment = Assignment(request=request, employee_id=eligible[0], reviewer_id=reviewer_id)
        self._assignments[request.id] = assignment
        self._write('assignment.created', assignment)
        return assignment

    def start(self, assignment_id: str) -> Assignment:
        item = self.get(assignment_id)
        if item.state not in {AssignmentState.ASSIGNED, AssignmentState.REWORK}:
            raise ValueError(f'assignment cannot start from {item.state}')
        item.state = AssignmentState.IN_PROGRESS
        item.attempts += 1
        from datetime import UTC, datetime
        item.started_at = datetime.now(UTC).isoformat()
        self._write('assignment.started', item)
        return item

    def submit(self, assignment_id: str, evidence: dict) -> Assignment:
        item = self.get(assignment_id)
        if item.state != AssignmentState.IN_PROGRESS:
            raise ValueError('assignment must be in progress before submission')
        item.evidence.update(evidence)
        item.state = AssignmentState.REVIEW
        self._write('assignment.submitted', item)
        return item

    def review(self, assignment_id: str, *, approved: bool, defects: tuple[str, ...] = ()) -> Assignment:
        item = self.get(assignment_id)
        if item.state != AssignmentState.REVIEW:
            raise ValueError('assignment is not ready for review')
        if approved and item.completeness < 1.0:
            raise ValueError('all acceptance criteria require evidence before approval')
        if approved:
            item.state = AssignmentState.COMPLETED
            from datetime import UTC, datetime
            item.completed_at = datetime.now(UTC).isoformat()
            self.careers.record_result(item.employee_id, True)
            self.record_performance(item, 'success', 100.0)
        else:
            item.state = AssignmentState.REWORK
            item.defects.extend(defects or ('review rejected without defect details',))
            self.careers.record_result(item.employee_id, False)
            self.record_performance(item, 'rework', max(0.0, item.completeness * 100))
        self._write('assignment.reviewed', item)
        return item

    def block(self, assignment_id: str, reason: str) -> Assignment:
        item = self.get(assignment_id)
        item.state = AssignmentState.BLOCKED
        item.defects.append(reason)
        self._write('assignment.blocked', item)
        return item

    def record_performance(self, assignment: Assignment, outcome: str, quality_score: float) -> PerformanceEvent:
        event = PerformanceEvent(
            employee_id=assignment.employee_id,
            assignment_id=assignment.request.id,
            outcome=outcome,
            quality_score=round(max(0.0, min(100.0, quality_score)), 2),
            notes='; '.join(assignment.defects[-3:]),
        )
        self._events.append(event)
        # Free-form review notes remain in the authorized runtime, never in the
        # operational file. References are pseudonyms, not encryption/anonymity.
        self._append_audit({
            'type': 'performance',
            'employee_ref': self._audit_reference(event.employee_id),
            'assignment_ref': self._audit_reference(event.assignment_id),
            'outcome': event.outcome if event.outcome in {'success', 'rework', 'failure'} else 'other',
            'quality_score': event.quality_score,
            'defect_count': len(assignment.defects),
            'recorded_at': event.recorded_at,
        })
        return event

    def get(self, assignment_id: str) -> Assignment:
        return self._assignments[assignment_id]

    def assignments_for(self, employee_id: str) -> tuple[Assignment, ...]:
        return tuple(item for item in self._assignments.values() if item.employee_id == employee_id)

    def performance_for(self, employee_id: str) -> tuple[PerformanceEvent, ...]:
        return tuple(item for item in self._events if item.employee_id == employee_id)

    def _write(self, event_type: str, assignment: Assignment) -> None:
        if not self.ledger_path:
            return
        payload = {
            'type': event_type,
            'assignment_ref': self._audit_reference(assignment.request.id),
            'project_ref': self._audit_reference(assignment.request.project_id),
            'employee_ref': self._audit_reference(assignment.employee_id),
            'state': assignment.state.value,
            'attempts': assignment.attempts,
            'completeness': assignment.completeness,
        }
        self._append_audit(payload)

    @staticmethod
    def _audit_reference(value: str) -> str:
        return hashlib.sha256(b'aionex-worker-audit-v1\0' + value.encode('utf-8')).hexdigest()

    def _append_audit(self, payload: dict) -> None:
        if self.ledger_path is None:
            return
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(self.ledger_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise PermissionError('worker audit requires an owned regular file without links')
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            remaining = memoryview((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError('worker audit write failed')
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
