from __future__ import annotations

from pathlib import Path

from aios.db import Database
from aios.intelligence import (
    ConstitutionEngine, KnowledgeGraph, ProjectDigitalTwin, WisdomEngine, Strategy,
    DefenseIntelligenceCenter, ConcurrentTaskOrchestrator, TaskSpec,
)


def test_constitution_blocks_unauthorized_and_known_failure():
    verdict = ConstitutionEngine().evaluate(
        'change production', authorization=False, known_failure_unchanged=True,
        environment='production', destructive=True,
    )
    assert verdict.allowed is False
    assert verdict.requires_human_approval is True
    assert len(verdict.violations) == 2


def test_constitution_allows_safe_verified_development_action():
    verdict = ConstitutionEngine().evaluate(
        'add docs', authorization=True, evidence=['tests passed'], dry_run_passed=True,
        rollback_available=False, environment='development',
    )
    assert verdict.allowed is True
    assert verdict.violations == ()


def test_digital_twin_and_graph_index_project(tmp_path):
    (tmp_path / 'a.py').write_text('import json\nfrom b import run\n')
    (tmp_path / 'b.py').write_text('def run():\n    return 1\n')
    db = Database(tmp_path / 'db.sqlite3')
    db.initialize()
    graph = KnowledgeGraph(db)
    twin = ProjectDigitalTwin(graph).build(tmp_path, 'demo')
    assert len(twin.files) >= 2
    assert twin.languages['python'] == 2
    project_key = graph.key('project', 'demo')
    assert len(graph.neighbors(project_key, 'contains')) >= 2


def test_defense_center_requires_authorization(tmp_path):
    (tmp_path / 'app.py').write_text('API_KEY="abcdefgh12345678"\n')
    twin = ProjectDigitalTwin().build(tmp_path, 'demo')
    center = DefenseIntelligenceCenter()
    try:
        center.audit(twin, authorization=False)
    except PermissionError:
        pass
    else:
        raise AssertionError('authorization must be required')
    findings = center.audit(twin, authorization=True)
    assert any(item.category == 'secrets' for item in findings)


def test_wisdom_abstains_without_evidence_and_selects_long_term_value():
    engine = WisdomEngine()
    weak = Strategy('fast patch', .8, .3, .2, .3, .4, .2, .2, .2)
    assert engine.decide([weak]).abstained is True
    durable = Strategy('durable design', .8, .9, .9, .9, .9, .5, .5, .95)
    shortcut = Strategy('shortcut', .9, .7, .2, .2, .3, .1, .1, .1)
    decision = engine.decide([shortcut, durable])
    assert decision.selected is durable


def test_concurrent_orchestrator_isolates_failures():
    runner = ConcurrentTaskOrchestrator(max_workers=2)
    def fail():
        raise RuntimeError('boom')
    results = runner.run([
        TaskSpec('one', 'research', lambda: 7),
        TaskSpec('two', 'audit', fail),
    ])
    assert results[0].success is True and results[0].value == 7
    assert results[1].success is False and results[1].error == 'boom'
