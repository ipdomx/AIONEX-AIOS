from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import ChiefReview, Deliverable, DepartmentDecision, RoleLevel, WorkStatus
from .workforce import WorkforceRegistry


@dataclass(slots=True, frozen=True)
class ProjectBlueprint:
    project: str
    objective: str
    departments: tuple[str, ...]
    deliverables: tuple[Deliverable, ...]


class EngineeringOrganization:
    """Runs a project through specialist, engineer, manager and chief-engineer gates."""

    DEFAULT_DEPARTMENTS = ('Architecture', 'Backend', 'Frontend', 'Security', 'Quality', 'DevOps')

    def __init__(self, workforce: WorkforceRegistry | None = None) -> None:
        self.workforce = workforce or WorkforceRegistry()

    def plan(self, project: str, objective: str, *, departments: Iterable[str] | None = None) -> ProjectBlueprint:
        selected = tuple(dict.fromkeys(departments or self.DEFAULT_DEPARTMENTS))
        deliverables = tuple(self._default_deliverable(dep) for dep in selected)
        for item in deliverables:
            specialist = self.workforce.best_match(item.department, (item.department.lower(),), RoleLevel.SPECIALIST)
            engineer = self.workforce.best_match(item.department, (item.department.lower(),), RoleLevel.ENGINEER)
            item.owner_id = specialist.worker_id
            item.reviewer_id = engineer.worker_id
        return ProjectBlueprint(project, objective, selected, deliverables)

    def department_review(self, deliverable: Deliverable) -> DepartmentDecision:
        manager = self.workforce.best_match(deliverable.department, (deliverable.department.lower(),), RoleLevel.MANAGER)
        findings: list[str] = list(deliverable.defects)
        required: list[str] = []
        if deliverable.completeness < 1.0:
            findings.append('acceptance criteria are not fully proven')
            required.append('supply evidence for every acceptance criterion')
        if not deliverable.evidence.get('tests_passed', False):
            findings.append('tests have not passed')
            required.append('pass the department test plan')
        if deliverable.department in {'Security', 'Backend', 'DevOps'} and not deliverable.evidence.get('security_reviewed', False):
            findings.append('security review is missing')
            required.append('complete security review')
        score = max(0.0, min(1.0, deliverable.completeness - 0.12 * len(set(findings))))
        approved = score >= .85 and not findings
        deliverable.status = WorkStatus.COMPLETE if approved else WorkStatus.REWORK
        return DepartmentDecision(deliverable.department, approved, round(score, 4), tuple(dict.fromkeys(findings)), tuple(dict.fromkeys(required)), manager.worker_id)

    def chief_review(self, blueprint: ProjectBlueprint) -> ChiefReview:
        decisions = tuple(self.department_review(d) for d in blueprint.deliverables)
        blocking = tuple(f'{d.department}: {finding}' for d in decisions for finding in d.findings)
        approved = all(d.approved for d in decisions) and bool(decisions)
        readiness = round(sum(d.score for d in decisions) / len(decisions), 4) if decisions else 0.0
        rework = tuple(f'{d.department}: {action}' for d in decisions for action in d.required_actions)
        rationale = (
            'All departments passed their acceptance, test and review gates.'
            if approved else
            'Release withheld by the Chief Project Engineer until every blocking finding is resolved and re-reviewed.'
        )
        return ChiefReview(blueprint.project, approved, readiness, decisions, blocking, rework, rationale)

    @staticmethod
    def _default_deliverable(department: str) -> Deliverable:
        criteria = {
            'Architecture': ('architecture documented', 'dependencies mapped', 'failure modes reviewed'),
            'Backend': ('interfaces implemented', 'data integrity verified', 'performance tested'),
            'Frontend': ('user flows complete', 'accessibility checked', 'rendering performance tested'),
            'Security': ('threat model complete', 'critical findings resolved', 'controls verified'),
            'Quality': ('test plan complete', 'regression suite passed', 'evidence archived'),
            'DevOps': ('deployment reproducible', 'rollback tested', 'observability enabled'),
            'Data': ('schemas validated', 'migration tested', 'retention defined'),
            'Research': ('sources verified', 'experiments reproducible', 'uncertainty documented'),
        }.get(department, ('scope complete', 'tests passed', 'evidence archived'))
        return Deliverable(f'{department} delivery', department, criteria)
