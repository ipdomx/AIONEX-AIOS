from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable

from .db import Database


class RiskLevel(str, Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


class ExecutionMode(str, Enum):
    DRY_RUN = 'dry-run'
    APPLY = 'apply'


@dataclass(frozen=True)
class ExecutionPolicy:
    production: bool = False
    require_human_approval: bool = True
    allow_network: bool = False
    allow_destructive: bool = False
    allowed_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    action_id: str
    project: str | None
    summary: str
    commands: tuple[str, ...]
    touched_paths: tuple[str, ...]
    risk: RiskLevel
    destructive: bool
    network_required: bool
    rollback_steps: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ExecutionResult:
    action_id: str
    status: str
    mode: ExecutionMode
    evidence: dict
    rollback_available: bool


class PolicyViolation(RuntimeError):
    pass


class ExecutionSafetyLayer:
    """Policy-first execution with dry-run, backups, audit evidence and rollback metadata."""

    DANGEROUS_MARKERS = (
        'rm -rf', 'mkfs', 'dd if=', ':(){', 'shutdown', 'reboot',
        'drop database', 'truncate table', 'git reset --hard', 'docker system prune',
    )

    def __init__(self, db: Database, backup_root: Path):
        self.db = db
        self.backup_root = backup_root
        self.backup_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fingerprint(summary: str, commands: Iterable[str], paths: Iterable[str]) -> str:
        raw = json.dumps(
            {'summary': summary, 'commands': list(commands), 'paths': sorted(paths)},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def plan(self, summary: str, commands: Iterable[str] = (), touched_paths: Iterable[str] = (),
             project: str | None = None, risk: RiskLevel = RiskLevel.MEDIUM,
             network_required: bool = False, rollback_steps: Iterable[str] = ()) -> ExecutionPlan:
        command_tuple = tuple(commands)
        path_tuple = tuple(touched_paths)
        lowered = ' '.join(command_tuple).lower()
        destructive = any(marker in lowered for marker in self.DANGEROUS_MARKERS)
        action_id = f'act-{uuid.uuid4().hex[:16]}'
        return ExecutionPlan(
            action_id=action_id,
            project=project,
            summary=summary,
            commands=command_tuple,
            touched_paths=path_tuple,
            risk=risk,
            destructive=destructive,
            network_required=network_required,
            rollback_steps=tuple(rollback_steps),
            fingerprint=self._fingerprint(summary, command_tuple, path_tuple),
        )

    def validate(self, plan: ExecutionPlan, policy: ExecutionPolicy,
                 approved: bool = False) -> list[str]:
        blockers: list[str] = []
        if plan.destructive and not policy.allow_destructive:
            blockers.append('destructive-action-blocked')
        if plan.network_required and not policy.allow_network:
            blockers.append('network-access-blocked')
        if policy.require_human_approval and not approved:
            blockers.append('human-approval-required')
        if policy.production and plan.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL} and not approved:
            blockers.append('production-high-risk-approval-required')
        if plan.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL} and not plan.rollback_steps:
            blockers.append('rollback-plan-required')
        if policy.allowed_roots:
            roots = tuple(root.resolve() for root in policy.allowed_roots)
            for raw in plan.touched_paths:
                path = Path(raw).resolve()
                if not any(path == root or root in path.parents for root in roots):
                    blockers.append(f'path-outside-allowed-roots:{raw}')
        return blockers

    def _snapshot(self, plan: ExecutionPlan) -> Path | None:
        existing = [Path(item) for item in plan.touched_paths if Path(item).exists()]
        if not existing:
            return None
        target = self.backup_root / plan.action_id
        target.mkdir(parents=True, exist_ok=False)
        manifest = []
        for index, source in enumerate(existing):
            destination = target / f'{index:04d}-{source.name}'
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            manifest.append({'source': str(source.resolve()), 'backup': destination.name})
        (target / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        return target

    def execute(self, plan: ExecutionPlan, function: Callable[[], object],
                policy: ExecutionPolicy, mode: ExecutionMode = ExecutionMode.DRY_RUN,
                approved: bool = False, experiment_verified: bool = False) -> ExecutionResult:
        blockers = self.validate(plan, policy, approved=approved)
        if mode is ExecutionMode.APPLY and not experiment_verified:
            blockers.append('experiment-verification-required')

        if mode is ExecutionMode.DRY_RUN:
            evidence = {'blockers': blockers, 'plan': self._serialize_plan(plan)}
            self._record(plan, mode, 'planned', evidence, None)
            return ExecutionResult(plan.action_id, 'planned', mode, evidence, False)

        if blockers:
            evidence = {'blockers': blockers, 'plan': self._serialize_plan(plan)}
            self._record(plan, mode, 'blocked', evidence, None)
            raise PolicyViolation(', '.join(blockers))

        backup = self._snapshot(plan)
        try:
            value = function()
            evidence = {'result': repr(value), 'fingerprint': plan.fingerprint}
            self._record(plan, mode, 'succeeded', evidence, backup)
            return ExecutionResult(plan.action_id, 'succeeded', mode, evidence, backup is not None)
        except Exception as exc:
            evidence = {'error_type': type(exc).__name__, 'message': str(exc)}
            self._record(plan, mode, 'failed', evidence, backup)
            raise

    @staticmethod
    def _serialize_plan(plan: ExecutionPlan) -> dict:
        return {
            'action_id': plan.action_id,
            'project': plan.project,
            'summary': plan.summary,
            'commands': list(plan.commands),
            'touched_paths': list(plan.touched_paths),
            'risk': plan.risk.value,
            'destructive': plan.destructive,
            'network_required': plan.network_required,
            'rollback_steps': list(plan.rollback_steps),
            'fingerprint': plan.fingerprint,
        }

    def _record(self, plan: ExecutionPlan, mode: ExecutionMode, status: str,
                evidence: dict, backup: Path | None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO execution_runs
                   (action_id, project, fingerprint, summary, mode, risk, status,
                    plan, evidence, backup_path, rollback_available)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    plan.action_id, plan.project, plan.fingerprint, plan.summary,
                    mode.value, plan.risk.value, status,
                    json.dumps(self._serialize_plan(plan), ensure_ascii=False),
                    json.dumps(evidence, ensure_ascii=False),
                    str(backup) if backup else None, int(backup is not None),
                ),
            )

    def history(self, project: str | None = None, limit: int = 50) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                '''SELECT action_id, project, fingerprint, summary, mode, risk, status,
                          backup_path, rollback_available, created_at
                   FROM execution_runs WHERE project IS ?
                   ORDER BY id DESC LIMIT ?''',
                (project, limit),
            ).fetchall()
        return [dict(row) for row in rows]
