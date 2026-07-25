from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

from .db import Database

T = TypeVar('T')


def _fingerprint(*parts: str) -> str:
    value = '|'.join(part.strip().lower() for part in parts)
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class ErrorKnowledgeBase:
    """Persistent operational memory that turns failures into prevention rules."""

    def __init__(self, db: Database):
        self.db = db

    def record(self, operation: str, error: BaseException, project: str | None = None,
               context: dict | None = None) -> str:
        error_type = type(error).__name__
        message = str(error)
        fingerprint = _fingerprint(operation, error_type, message)
        payload = json.dumps(context or {}, ensure_ascii=False, sort_keys=True)
        with self.db.connect() as conn:
            row = conn.execute(
                'SELECT id FROM error_knowledge WHERE project IS ? AND fingerprint = ?',
                (project, fingerprint),
            ).fetchone()
            if row:
                conn.execute(
                    '''UPDATE error_knowledge SET occurrences = occurrences + 1,
                       last_seen = CURRENT_TIMESTAMP, context = ? WHERE id = ?''',
                    (payload, row['id']),
                )
            else:
                conn.execute(
                    '''INSERT INTO error_knowledge
                       (project, fingerprint, operation, error_type, message, context)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (project, fingerprint, operation, error_type, message, payload),
                )
        return fingerprint

    def resolve(self, fingerprint: str, resolution: str, prevention_rule: str,
                root_cause: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                '''UPDATE error_knowledge SET successful_resolution = ?, prevention_rule = ?,
                   root_cause = ?, status = 'resolved', last_seen = CURRENT_TIMESTAMP
                   WHERE fingerprint = ?''',
                (resolution, prevention_rule, root_cause, fingerprint),
            )

    def guard(self, operation: str, project: str | None = None) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                '''SELECT fingerprint, message, prevention_rule, successful_resolution, occurrences
                   FROM error_knowledge WHERE project IS ? AND operation = ?
                   ORDER BY occurrences DESC, last_seen DESC''',
                (project, operation),
            ).fetchall()
        return [dict(row) for row in rows]


@dataclass(frozen=True)
class ExperimentResult:
    success: bool
    attempts: int
    strategy: str
    value: object | None
    evidence: list[dict]


class ExperimentGate:
    """Requires reproducible success before an action is declared ready."""

    def __init__(self, db: Database, minimum_successes: int = 2, maximum_attempts: int = 5):
        if minimum_successes < 1 or maximum_attempts < minimum_successes:
            raise ValueError('Invalid experiment policy')
        self.db = db
        self.minimum_successes = minimum_successes
        self.maximum_attempts = maximum_attempts

    def validate(self, action_name: str, strategies: Iterable[tuple[str, Callable[[], T]]],
                 project: str | None = None) -> ExperimentResult:
        action_fp = _fingerprint(project or '', action_name)
        evidence: list[dict] = []
        successes = 0
        attempts = 0
        last_value: T | None = None
        chosen = ''
        strategy_list = list(strategies)
        if not strategy_list:
            raise ValueError('At least one strategy is required')

        while attempts < self.maximum_attempts and successes < self.minimum_successes:
            name, function = strategy_list[attempts % len(strategy_list)]
            attempts += 1
            try:
                last_value = function()
                ok = bool(last_value) if isinstance(last_value, bool) else last_value is not None
                detail = {'attempt': attempts, 'strategy': name, 'success': ok}
                successes = successes + 1 if ok else 0
                chosen = name if ok else chosen
            except Exception as exc:  # evidence is persisted; caller gets a safe failure
                successes = 0
                detail = {
                    'attempt': attempts,
                    'strategy': name,
                    'success': False,
                    'error_type': type(exc).__name__,
                    'message': str(exc),
                    'trace': traceback.format_exc(limit=2),
                }
            evidence.append(detail)
            with self.db.connect() as conn:
                conn.execute(
                    '''INSERT INTO experiment_runs
                       (project, action_fingerprint, action_name, strategy, attempt, success, evidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (project, action_fp, action_name, name, attempts, int(detail['success']),
                     json.dumps(detail, ensure_ascii=False)),
                )

        return ExperimentResult(
            success=successes >= self.minimum_successes,
            attempts=attempts,
            strategy=chosen,
            value=last_value if successes >= self.minimum_successes else None,
            evidence=evidence,
        )
