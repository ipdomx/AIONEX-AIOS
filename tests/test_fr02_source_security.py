"""Negative tests for the source audit batch; no production/SSH/provider calls."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from aios.academy import Academy
from aios.hr import CareerSystem, EmployeeRecord
from aios.workers import WorkRequest, WorkerRuntime
from aios.workforce_health import OperationalHealthInstitute

ROOT = Path(__file__).resolve().parents[1]


def deployment_module():
    spec = importlib.util.spec_from_file_location('fr02_deploy_inventory', ROOT / 'scripts/phase24b/deploy_inventory.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_runtime(path):
    careers = CareerSystem()
    careers.hire(EmployeeRecord('sensitive-worker-reference', 'engineer', 'engineering', skills={'python'}))
    return WorkerRuntime(careers, Academy(), OperationalHealthInstitute(), path)


def test_audit_omits_free_text_and_raw_identifiers_but_preserves_runtime(tmp_path):
    path = tmp_path / 'worker.jsonl'
    runtime = make_runtime(path)
    item = runtime.assign(WorkRequest('sensitive-project-reference', 'private title', ('python',), 'engineering', ('test',), id='sensitive-assignment-reference'))
    runtime.start(item.request.id)
    runtime.submit(item.request.id, {'passed_criteria': ['test']})
    runtime.review(item.request.id, approved=False, defects=('synthetic-secret-in-review-notes',))
    assert runtime.performance_for('sensitive-worker-reference')[0].notes == 'synthetic-secret-in-review-notes'
    text = path.read_text()
    for value in ['sensitive-project-reference', 'sensitive-worker-reference', 'sensitive-assignment-reference', 'synthetic-secret-in-review-notes', 'private title']:
        assert value not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert len(records) == 5
    assert records[-2]['defect_count'] == 1
    assert all(len(record['assignment_ref']) == 64 for record in records)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('link_type', ['symlink', 'hardlink', 'fifo'])
def test_audit_rejects_linked_or_nonregular_target(tmp_path, link_type):
    target = tmp_path / 'target'
    target.write_text('must remain unchanged')
    path = tmp_path / 'worker.jsonl'
    if link_type == 'symlink':
        path.symlink_to(target)
    elif link_type == 'hardlink':
        os.link(target, path)
    else:
        os.mkfifo(path)
    runtime = make_runtime(path)
    with pytest.raises(OSError):
        runtime._append_audit({'type': 'isolated-test'})
    assert target.read_text() == 'must remain unchanged'


def test_concurrent_audit_records_are_whole_and_private(tmp_path):
    path = tmp_path / 'worker.jsonl'
    path.touch(mode=0o644)
    runtime = make_runtime(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: runtime._append_audit({'type': 'test', 'sequence': i}), range(80)))
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 80
    assert {r['sequence'] for r in records} == set(range(80))
    assert path.stat().st_mode & 0o777 == 0o600


def test_process_error_does_not_disclose_arguments_or_output(monkeypatch):
    module = deployment_module()
    secret = 'synthetic-private-test-value'
    monkeypatch.setattr(module.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess(['ssh'], 1, secret, secret)))
    with pytest.raises(RuntimeError) as error:
        module.run(['ssh', secret])
    assert secret not in str(error.value)
    assert 'exit code 1' in str(error.value)


def test_real_command_builders_keep_strict_ssh_and_dry_run(tmp_path, monkeypatch):
    module = deployment_module()
    call = Mock(side_effect=AssertionError('dry-run must not execute'))
    monkeypatch.setattr(module, 'run', call)
    for role in ['control-plane', 'agent']:
        target = module.InventoryTarget(role, 'host-a', 'root@host.example', tmp_path / role)
        commands = module.deploy_target(target, tmp_path / 'source.tar.gz', tmp_path, apply=False)
        assert all('StrictHostKeyChecking=yes' in command for command in commands)
        assert all('BatchMode=yes' in command for command in commands)
        assert f'systemctl enable --now aionex-phase24b-{role}.service' in commands[-1][-1]
    call.assert_not_called()


@pytest.mark.parametrize('bundle,valid', [
    ('const api="https://api.vip-e.net/api/v1";', True),
    ("const api='https://api.vip-e.net/api/v1';", True),
    ('const api=`https://api.vip-e.net/api/v1`;', True),
    ('const api="https://api.vip-e.net:443/api/v1";', True),
    ('const api="https://api.vip-e.net.evil.example/api/v1";', False),
    ('const api="https://api.vip-e.net/api/v1/evil";', False),
    ('const api="https://api.vip-e.net/api/v1?redirect=evil";', False),
    ('const api="https://api.vip-e.net/api/v1#evil";', False),
    ('const api="https://api.vip-e.net@evil.example/api/v1";', False),
    ('const api="https://user@api.vip-e.net/api/v1";', False),
    ('const api="http://api.vip-e.net/api/v1";', False),
    ('const api="https://api.vip-e.net:444/api/v1";', False),
    ('const api="https://api.vip-e.net/api/v1"; const rejected="https://api.ai.vip-e.net/api";', False),
    ('const api="https://api.vip-e.net/api/v1"; const rejected="https://API.AI.VIP-E.NET./api";', False),
    ('const unrelated="https://evil.example?next=https://api.vip-e.net/api/v1";', False),
])
def test_api_bundle_policy_parses_full_url_not_substring(bundle, valid):
    module_uri = (ROOT / 'vip-frontend/scripts/production-api-bundle-policy.mjs').as_uri()
    program = f'import {{assertProductionApiBundle as verify}} from {json.dumps(module_uri)}; try {{verify({json.dumps(bundle)}); process.stdout.write("PASS");}} catch {{process.stdout.write("REJECT");}}'
    result = subprocess.run(['node', '--input-type=module', '-e', program], text=True, capture_output=True, check=True, timeout=10)
    assert result.stdout == ('PASS' if valid else 'REJECT')
