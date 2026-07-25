from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True, frozen=True)
class ConstitutionalVerdict:
    allowed: bool
    requires_human_approval: bool
    violations: tuple[str, ...]
    conditions: tuple[str, ...]
    rationale: str


class ConstitutionEngine:
    """Stable, provider-independent rules governing every significant AIOS action."""

    PRINCIPLES = (
        'Evidence before execution',
        'Accuracy before speed',
        'Dry-run and reproducible tests before mutation',
        'Rollback before high-risk change',
        'Never repeat a known failure under unchanged conditions',
        'Least privilege and explicit authorization',
        'Human approval for production, destructive, security-sensitive, or self-modifying actions',
        'Preserve an auditable history of knowledge and decisions',
        'Prefer durable value over novelty',
    )

    def evaluate(
        self,
        action: str,
        *,
        evidence: Iterable[str] = (),
        dry_run_passed: bool = False,
        rollback_available: bool = False,
        authorization: bool = False,
        known_failure_unchanged: bool = False,
        environment: str = 'development',
        destructive: bool = False,
        self_modifying: bool = False,
        security_sensitive: bool = False,
    ) -> ConstitutionalVerdict:
        evidence = tuple(item for item in evidence if str(item).strip())
        violations: list[str] = []
        conditions: list[str] = []
        high_risk = destructive or self_modifying or security_sensitive or environment == 'production'

        if not authorization:
            violations.append('Explicit authorization is required')
        if known_failure_unchanged:
            violations.append('A known failure would be repeated under unchanged conditions')
        if not evidence:
            conditions.append('Attach verifiable evidence')
        if not dry_run_passed:
            conditions.append('Pass a dry run')
        if high_risk and not rollback_available:
            conditions.append('Create and verify a rollback plan')

        requires_human = high_risk
        allowed = not violations and not conditions and (not requires_human)
        if not violations and not conditions and requires_human:
            rationale = 'Technically eligible, but constitutional policy requires human approval'
        elif violations:
            rationale = 'Blocked by constitutional violations'
        elif conditions:
            rationale = 'Not yet eligible; mandatory evidence or safety conditions remain'
        else:
            rationale = 'Constitutional requirements satisfied'
        return ConstitutionalVerdict(allowed, requires_human, tuple(violations), tuple(conditions), rationale)
