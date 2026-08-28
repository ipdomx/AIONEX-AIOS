import hashlib
import json
from pathlib import Path

import pytest

from aios.evidence_closure import EvidenceClosure, EvidenceClosureValidationError
from aios.organization import EngineeringOrganization


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')


def _source_execution(tmp_path: Path) -> Path:
    root = tmp_path / 'phase22c'
    artifacts = root / 'artifacts'
    artifacts.mkdir(parents=True)
    org = EngineeringOrganization()
    blueprint = org.plan('AIONEX-AIOS', 'Close truthful evidence blockers')
    records = []
    for item in blueprint.deliverables:
        payload = {
            'schema_version': 1,
            'execution_id': 'phase22c-source',
            'project': 'AIONEX-AIOS',
            'objective': 'Close truthful evidence blockers',
            'provider': 'openai',
            'model': 'gpt-5-mini',
            'department': item.department,
            'model_output': {
                'schema_version': 1,
                'department': item.department,
                'summary': 'truthful source artifact',
                'implementation_plan': ['one', 'two', 'three'],
                'technical_evidence': [
                    {'criterion': criterion, 'evidence': 'documented', 'verification': 'verify'}
                    for criterion in item.acceptance_criteria
                ],
                'risks': [{'risk': 'regression', 'mitigation': 'tests'}],
                'tests_passed': False,
                'security_reviewed': False,
            },
        }
        path = artifacts / f'{item.department.lower()}.json'
        _write_json(path, payload)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append({'department': item.department, 'path': f'artifacts/{path.name}', 'sha256': digest})
    manifest = {
        'execution_id': 'phase22c-source',
        'project': 'AIONEX-AIOS',
        'objective': 'Close truthful evidence blockers',
        'provider': 'openai',
        'model': 'gpt-5-mini',
        'artifacts': records,
        'review': {
            'approved': False,
            'readiness_score': 0.82,
            'blocking_findings': ['tests have not passed'],
        },
        'proof': {'fallback_used': False, 'production_modified': False},
    }
    _write_json(root / 'manifest.json', manifest)
    return root


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / 'project'
    (root / 'src/aios/organization').mkdir(parents=True)
    (root / 'src/aios/providers').mkdir(parents=True)
    (root / 'docs/phase-22c').mkdir(parents=True)
    source = '''
ALLOWED_OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
ALLOWED_OPENAI_MODELS_ENDPOINT = "https://api.openai.com/v1/models"
secret_path.is_symlink()
stat.S_IMODE(file_stat.st_mode) != 0o600
file_stat.st_uid != 0
{"OPENAI_API_KEY", "AIOS_PHASE22C_MODEL"}
api_key='[REDACTED]'
'''
    (root / 'src/aios/cloud_provider_sandbox.py').write_text(source, encoding='utf-8')
    (root / 'src/aios/local_model_sandbox.py').write_text('VALUE = 1\n', encoding='utf-8')
    (root / 'src/aios/organization/__init__.py').write_text('VALUE = 1\n', encoding='utf-8')
    (root / 'src/aios/providers/__init__.py').write_text('VALUE = 1\n', encoding='utf-8')
    (root / 'docs/phase-22c/README.md').write_text('safe evidence\n', encoding='utf-8')
    return root


class PassingClosure(EvidenceClosure):
    def _security_review(self, source):
        return {
            'schema_version': 1,
            'required_departments': ['Backend', 'DevOps', 'Security'],
            'checks': [{'name': 'fixed', 'passed': True}],
            'approved': True,
            'finding_count': 0,
            'network_used': False,
            'provider_key_read': False,
            'production_modified': False,
        }


def test_source_validation_rejects_tampered_artifact(tmp_path):
    source = _source_execution(tmp_path)
    artifact = next((source / 'artifacts').iterdir())
    artifact.write_text('{}', encoding='utf-8')
    closure = EvidenceClosure(_project_root(tmp_path))
    with pytest.raises(EvidenceClosureValidationError, match='hash mismatch'):
        closure._validate_source(source)


def test_security_review_is_offline_and_detects_required_controls(tmp_path):
    source = _source_execution(tmp_path)
    closure = EvidenceClosure(_project_root(tmp_path))
    review = closure._security_review(source)
    assert review['approved'] is True
    assert review['network_used'] is False
    assert review['provider_key_read'] is False
    assert review['production_modified'] is False
    assert {item['name'] for item in review['checks']} >= {
        'no-shell-or-cloud-fallback',
        'official-openai-endpoints-only',
        'external-secret-controls',
        'tracked-scope-credential-scan',
        'runtime-evidence-secret-scan',
        'controlled-python-source-compiles',
    }


def test_credential_scan_detects_secret_shaped_values(tmp_path):
    root = _project_root(tmp_path)
    bad = root / 'docs/phase-22c/bad.txt'
    bad.write_text('sk-proj-' + 'A' * 30, encoding='utf-8')
    closure = EvidenceClosure(root)
    hits = closure._credential_hits([root / 'docs/phase-22c'])
    assert str(bad) in hits


def test_execution_produces_hashed_department_receipts_and_approved_review(tmp_path, monkeypatch):
    source = _source_execution(tmp_path)
    root = _project_root(tmp_path)

    class Completed:
        returncode = 0
        stdout = '9 passed in 0.10s\n'
        stderr = ''

    monkeypatch.setattr('aios.evidence_closure.subprocess.run', lambda *args, **kwargs: Completed())
    closure = PassingClosure(root)
    result = closure.execute(
        execution_id='phase22d-test',
        output_root=tmp_path / 'output',
        source_execution_directory=source,
    )
    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.tests_passed is True
    assert result.security_reviewed is True
    assert result.passed_count == 9
    manifest = json.loads(result.manifest_path.read_text(encoding='utf-8'))
    assert manifest['proof']['network_used'] is False
    assert manifest['proof']['cloud_request_sent'] is False
    assert manifest['proof']['production_modified'] is False
    assert manifest['proof']['model_claims_used_as_execution_proof'] is False
    assert len(manifest['departments']) == 6
    for item in manifest['departments']:
        path = result.output_directory / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']


def test_existing_execution_is_not_replaced(tmp_path, monkeypatch):
    source = _source_execution(tmp_path)
    root = _project_root(tmp_path)

    class Completed:
        returncode = 0
        stdout = '1 passed in 0.01s\n'
        stderr = ''

    monkeypatch.setattr('aios.evidence_closure.subprocess.run', lambda *args, **kwargs: Completed())
    closure = PassingClosure(root)
    closure.execute(
        execution_id='duplicate',
        output_root=tmp_path / 'output',
        source_execution_directory=source,
    )
    with pytest.raises(FileExistsError):
        closure.execute(
            execution_id='duplicate',
            output_root=tmp_path / 'output',
            source_execution_directory=source,
        )


def test_output_root_and_execution_id_are_safely_validated(tmp_path):
    closure = EvidenceClosure(_project_root(tmp_path))
    with pytest.raises(ValueError, match='unsafe execution_id'):
        closure.execute(execution_id='../escape', output_root=tmp_path / 'out', source_execution_directory=_source_execution(tmp_path))
    with pytest.raises(ValueError, match='absolute'):
        closure.execute(execution_id='safe', output_root='relative', source_execution_directory=_source_execution(tmp_path / 'second'))
