from pathlib import Path

from aios.connectors import ConnectorRegistry
from aios.db import Database
from aios.durable_memory import DurableMemory
from aios.reliability import ErrorKnowledgeBase, ExperimentGate


def make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / 'test.db')
    db.initialize()
    return db


def test_durable_memory_deduplicates_and_revises(tmp_path):
    memory = DurableMemory(make_db(tmp_path))
    first = memory.remember_once('Never deploy without tests', project='alpha')
    second = memory.remember_once('Never deploy without tests', project='alpha')
    assert first == second
    memory.revise(first, 'Never deploy without passing tests', 'clarification')


def test_error_knowledge_accumulates_and_resolves(tmp_path):
    errors = ErrorKnowledgeBase(make_db(tmp_path))
    fingerprint = errors.record('deploy', RuntimeError('port busy'), project='alpha')
    errors.record('deploy', RuntimeError('port busy'), project='alpha')
    rows = errors.guard('deploy', 'alpha')
    assert rows[0]['occurrences'] == 2
    errors.resolve(fingerprint, 'use an available port', 'check port before deploy')
    assert errors.guard('deploy', 'alpha')[0]['prevention_rule'] == 'check port before deploy'


def test_experiment_gate_requires_repeatable_success(tmp_path):
    gate = ExperimentGate(make_db(tmp_path), minimum_successes=2, maximum_attempts=4)
    result = gate.validate('health-check', [('primary', lambda: True)], project='alpha')
    assert result.success is True
    assert result.attempts == 2


def test_experiment_gate_rejects_unproven_action(tmp_path):
    gate = ExperimentGate(make_db(tmp_path), minimum_successes=2, maximum_attempts=3)
    result = gate.validate('unsafe-change', [('bad', lambda: False)], project='alpha')
    assert result.success is False
    assert result.value is None


def test_connector_validation_and_registry(tmp_path):
    connectors = ConnectorRegistry(make_db(tmp_path))
    connectors.register('alpha', 'api', 'http', 'https://example.com/health')
    connectors.register('alpha', 'ssh-port', 'tcp', 'example.com:22')
    assert len(connectors.list('alpha')) == 2
