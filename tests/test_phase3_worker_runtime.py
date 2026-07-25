from pathlib import Path
import pytest

from aios.academy import Academy
from aios.hr import CareerSystem, EmployeeRecord, EmploymentState
from aios.workers import AssignmentState, WorkRequest, WorkerRuntime
from aios.workforce_health import OperationalHealthInstitute


def make_runtime(tmp_path: Path):
    careers = CareerSystem()
    careers.hire(EmployeeRecord('eng-1', 'engineer', 'engineering', skills={'python', 'testing'}))
    careers.hire(EmployeeRecord('eng-2', 'engineer', 'engineering', state=EmploymentState.SUSPENDED, skills={'python', 'testing'}))
    return careers, WorkerRuntime(careers, Academy(), OperationalHealthInstitute(), tmp_path / 'worker-ledger.jsonl')


def test_assigns_only_eligible_worker(tmp_path):
    careers, runtime = make_runtime(tmp_path)
    request = WorkRequest('p1', 'Build API', ('python', 'testing'), 'engineering', ('tests_pass', 'reviewed'))
    item = runtime.assign(request, reviewer_id='manager-1')
    assert item.employee_id == 'eng-1'
    assert item.state == AssignmentState.ASSIGNED


def test_requires_complete_evidence_before_approval(tmp_path):
    careers, runtime = make_runtime(tmp_path)
    request = WorkRequest('p1', 'Build API', ('python',), 'engineering', ('tests_pass', 'reviewed'))
    item = runtime.assign(request)
    runtime.start(item.request.id)
    runtime.submit(item.request.id, {'passed_criteria': ['tests_pass']})
    with pytest.raises(ValueError):
        runtime.review(item.request.id, approved=True)
    runtime.review(item.request.id, approved=False, defects=('missing peer review',))
    assert item.state == AssignmentState.REWORK
    assert careers.get('eng-1').failure_count == 1


def test_success_updates_career_and_ledger(tmp_path):
    careers, runtime = make_runtime(tmp_path)
    request = WorkRequest('p1', 'Build API', ('python',), 'engineering', ('tests_pass', 'reviewed'))
    item = runtime.assign(request)
    runtime.start(item.request.id)
    runtime.submit(item.request.id, {'passed_criteria': ['tests_pass', 'reviewed']})
    runtime.review(item.request.id, approved=True)
    assert item.state == AssignmentState.COMPLETED
    assert careers.get('eng-1').success_count == 1
    assert runtime.performance_for('eng-1')[0].outcome == 'success'
    assert (tmp_path / 'worker-ledger.jsonl').exists()


def test_no_eligible_worker_is_rejected(tmp_path):
    _, runtime = make_runtime(tmp_path)
    request = WorkRequest('p1', 'Rust core', ('rust',), 'engineering', ('compiled',))
    with pytest.raises(LookupError):
        runtime.assign(request)
