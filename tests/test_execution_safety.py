from pathlib import Path

import pytest

from aios.db import Database
from aios.execution import (
    ExecutionMode, ExecutionPolicy, ExecutionSafetyLayer, PolicyViolation, RiskLevel,
)


def layer(tmp_path):
    db = Database(tmp_path / 'aios.db')
    db.initialize()
    return ExecutionSafetyLayer(db, tmp_path / 'backups')


def test_dry_run_never_executes(tmp_path):
    safety = layer(tmp_path)
    marker = tmp_path / 'marker'
    plan = safety.plan('create marker', touched_paths=[str(marker)], risk=RiskLevel.LOW)
    result = safety.execute(plan, lambda: marker.write_text('x'), ExecutionPolicy(), ExecutionMode.DRY_RUN)
    assert result.status == 'planned'
    assert not marker.exists()


def test_apply_requires_experiment_verification(tmp_path):
    safety = layer(tmp_path)
    plan = safety.plan('safe operation', risk=RiskLevel.LOW)
    with pytest.raises(PolicyViolation, match='experiment-verification-required'):
        safety.execute(plan, lambda: True, ExecutionPolicy(require_human_approval=False),
                       ExecutionMode.APPLY)


def test_destructive_command_is_blocked(tmp_path):
    safety = layer(tmp_path)
    plan = safety.plan('danger', commands=['rm -rf /tmp/example'], risk=RiskLevel.CRITICAL,
                       rollback_steps=['restore snapshot'])
    blockers = safety.validate(plan, ExecutionPolicy(require_human_approval=False))
    assert 'destructive-action-blocked' in blockers


def test_successful_apply_creates_backup_and_history(tmp_path):
    safety = layer(tmp_path)
    target = tmp_path / 'config.txt'
    target.write_text('old')
    plan = safety.plan('update config', touched_paths=[str(target)], risk=RiskLevel.HIGH,
                       rollback_steps=['restore config backup'])
    result = safety.execute(
        plan, lambda: target.write_text('new'),
        ExecutionPolicy(require_human_approval=True, allowed_roots=(tmp_path,)),
        ExecutionMode.APPLY, approved=True, experiment_verified=True,
    )
    assert result.status == 'succeeded'
    assert result.rollback_available
    assert target.read_text() == 'new'
    assert safety.history()[0]['status'] == 'succeeded'


def test_path_outside_allowed_root_is_blocked(tmp_path):
    safety = layer(tmp_path)
    plan = safety.plan('write elsewhere', touched_paths=['/etc/hosts'], risk=RiskLevel.MEDIUM)
    blockers = safety.validate(
        plan, ExecutionPolicy(require_human_approval=False, allowed_roots=(tmp_path,))
    )
    assert any(item.startswith('path-outside-allowed-roots:') for item in blockers)
