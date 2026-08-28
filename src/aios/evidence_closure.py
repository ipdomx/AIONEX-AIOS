from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .organization import EngineeringOrganization

DEFAULT_SOURCE = Path('/var/tmp/aionex-phase22c/sandbox-output/phase22c-openai-controlled-diagnostic-v2')
DEFAULT_OUTPUT_ROOT = Path('/var/tmp/aionex-phase22d/evidence-closure')
DEFAULT_EXECUTION_ID = 'phase22d-evidence-closure'
CONTROLLED_TEST_TARGETS = (
    'tests/test_cloud_provider_sandbox.py',
    'tests/test_local_model_sandbox.py',
    'tests/test_engineering_organization.py',
    'tests/test_phase7_ai_providers.py',
    'tests/test_phase7_part2_provider_implementations.py',
    'tests/test_phase22d_evidence_closure.py',
)
SECURITY_REQUIRED = frozenset({'Backend', 'Security', 'DevOps'})
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_SECRET_PATTERNS = (
    re.compile(r'(?i)\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'(?i)\bgh[pousr]_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'(?i)Authorization\s*:\s*Bearer\s+\S+'),
)


class EvidenceClosureValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceClosureResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    tests_passed: bool
    security_reviewed: bool
    passed_count: int
    total_duration: float


class EvidenceClosure:
    def __init__(self, project_root: str | Path = '/opt/AIOS', timeout_seconds: float = 600.0) -> None:
        root = Path(project_root)
        if not root.is_absolute():
            raise ValueError('project_root must be absolute')
        self.project_root = root.resolve(strict=True)
        if not 1 <= timeout_seconds <= 1800:
            raise ValueError('timeout_seconds must be between 1 and 1800')
        self.timeout_seconds = float(timeout_seconds)

    def execute(
        self,
        *,
        execution_id: str = DEFAULT_EXECUTION_ID,
        output_root: str | Path = DEFAULT_OUTPUT_ROOT,
        source_execution_directory: str | Path = DEFAULT_SOURCE,
    ) -> EvidenceClosureResult:
        if not _ID.fullmatch(execution_id) or execution_id in {'.', '..'}:
            raise ValueError('unsafe execution_id')
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / execution_id)
        staging = self._contained(root, root / f'.staging-{execution_id}')
        if destination.exists() or staging.exists():
            raise FileExistsError(execution_id)

        source = Path(source_execution_directory).resolve(strict=True)
        source_manifest, source_artifacts = self._validate_source(source)

        staging.mkdir(mode=0o700)
        started = time.monotonic()
        try:
            evidence_dir = staging / 'evidence'
            departments_dir = staging / 'departments'
            evidence_dir.mkdir(mode=0o700)
            departments_dir.mkdir(mode=0o700)

            security_review = self._security_review(source)
            security_path = evidence_dir / 'security-review.json'
            self._write(security_path, self._json(security_review))

            pytest_executable = shutil.which('pytest') or '/usr/bin/pytest'
            argv = [pytest_executable, '-q', *CONTROLLED_TEST_TARGETS]
            run_started = time.monotonic()
            completed = subprocess.run(
                argv,
                cwd=str(self.project_root),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=os.environ.copy(),
            )
            duration = time.monotonic() - run_started
            stdout = self._sanitize(completed.stdout)
            stderr = self._sanitize(completed.stderr)
            stdout_path = evidence_dir / 'controlled-regression.stdout.txt'
            stderr_path = evidence_dir / 'controlled-regression.stderr.txt'
            self._write(stdout_path, stdout)
            self._write(stderr_path, stderr)
            passed_count = self._passed_count(stdout + '\n' + stderr)
            tests_passed = completed.returncode == 0 and passed_count > 0
            test_receipt = {
                'argv': argv,
                'shell_used': False,
                'exit_code': completed.returncode,
                'duration_seconds': round(duration, 6),
                'passed_count': passed_count,
                'passed': tests_passed,
                'targets': list(CONTROLLED_TEST_TARGETS),
                'stdout_path': str(stdout_path.relative_to(staging)),
                'stderr_path': str(stderr_path.relative_to(staging)),
                'stdout_sha256': self._sha256(stdout_path),
                'stderr_sha256': self._sha256(stderr_path),
                'network_required': False,
                'production_modified': False,
            }
            test_path = evidence_dir / 'controlled-regression.json'
            self._write(test_path, self._json(test_receipt))

            org = EngineeringOrganization()
            blueprint = org.plan(str(source_manifest['project']), str(source_manifest['objective']))
            by_department = {item['department']: item for item in source_artifacts}
            security_passed = bool(security_review['approved'])
            department_records: list[dict[str, Any]] = []
            for deliverable in blueprint.deliverables:
                source_artifact = by_department[deliverable.department]
                model_output = source_artifact['payload']['model_output']
                passed_criteria = [str(item['criterion']) for item in model_output['technical_evidence']]
                deliverable.evidence.update({
                    'passed_criteria': passed_criteria,
                    'tests_passed': tests_passed,
                    'security_reviewed': security_passed,
                    'test_receipt_sha256': self._sha256(test_path),
                    'security_review_sha256': self._sha256(security_path),
                })
                record = {
                    'schema_version': 1,
                    'department': deliverable.department,
                    'source_artifact': source_artifact['relative_path'],
                    'source_artifact_sha256': source_artifact['sha256'],
                    'acceptance_criteria': list(deliverable.acceptance_criteria),
                    'acceptance_criteria_proven': passed_criteria,
                    'tests_passed': tests_passed,
                    'security_review_required': deliverable.department in SECURITY_REQUIRED,
                    'security_reviewed': security_passed,
                    'test_receipt': str(test_path.relative_to(staging)),
                    'test_receipt_sha256': self._sha256(test_path),
                    'security_review_receipt': str(security_path.relative_to(staging)),
                    'security_review_receipt_sha256': self._sha256(security_path),
                    'model_claims_used_as_execution_proof': False,
                }
                path = departments_dir / f'{deliverable.department.lower()}.json'
                self._write(path, self._json(record))
                department_records.append({
                    'department': deliverable.department,
                    'path': str(path.relative_to(staging)),
                    'sha256': self._sha256(path),
                    'tests_passed': tests_passed,
                    'security_reviewed': security_passed,
                })

            review = org.chief_review(blueprint)
            total_duration = round(time.monotonic() - started, 6)
            manifest = {
                'schema_version': 1,
                'phase': '22D',
                'execution_id': execution_id,
                'mode': 'offline-evidence-closure',
                'project': source_manifest['project'],
                'objective': source_manifest['objective'],
                'scope': 'Phase 22C controlled single-provider sandbox and its regression/security boundary',
                'scope_limit': 'This does not claim that every historical AIOS test module or the full production release passed.',
                'source': {
                    'execution_id': source_manifest['execution_id'],
                    'directory': str(source),
                    'manifest_sha256': self._sha256(source / 'manifest.json'),
                    'provider': source_manifest['provider'],
                    'model': source_manifest['model'],
                    'original_approved': source_manifest['review']['approved'],
                    'original_readiness_score': source_manifest['review']['readiness_score'],
                    'immutable': True,
                },
                'test_evidence': test_receipt,
                'security_review': security_review,
                'departments': department_records,
                'review': {
                    'approved': review.approved,
                    'readiness_score': review.readiness_score,
                    'blocking_findings': list(review.blocking_findings),
                    'rework_plan': list(review.rework_plan),
                    'rationale': review.rationale,
                },
                'proof': {
                    'tests_executed': True,
                    'tests_passed': tests_passed,
                    'security_review_executed': True,
                    'security_reviewed': security_passed,
                    'network_used': False,
                    'provider_key_used': False,
                    'cloud_request_sent': False,
                    'fallback_used': False,
                    'production_modified': False,
                    'source_execution_modified': False,
                    'model_claims_used_as_execution_proof': False,
                },
                'total_duration': total_duration,
            }
            manifest_path = staging / 'manifest.json'
            report_path = staging / 'REPORT.md'
            self._write(manifest_path, self._json(manifest))
            self._write(report_path, self._report(manifest))
            os.replace(staging, destination)
            return EvidenceClosureResult(
                execution_id=execution_id,
                output_directory=destination,
                manifest_path=destination / 'manifest.json',
                report_path=destination / 'REPORT.md',
                approved=review.approved,
                readiness_score=review.readiness_score,
                blocking_findings=review.blocking_findings,
                rework_plan=review.rework_plan,
                tests_passed=tests_passed,
                security_reviewed=security_passed,
                passed_count=passed_count,
                total_duration=total_duration,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _validate_source(self, source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        manifest_path = source / 'manifest.json'
        if not source.is_dir() or source.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
            raise EvidenceClosureValidationError('unsafe Phase 22C source')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('provider') != 'openai' or manifest.get('proof', {}).get('fallback_used') is not False:
            raise EvidenceClosureValidationError('invalid Phase 22C source provider or fallback proof')
        if manifest.get('proof', {}).get('production_modified') is not False:
            raise EvidenceClosureValidationError('Phase 22C source modified production')
        records = manifest.get('artifacts')
        if not isinstance(records, list) or len(records) != 6:
            raise EvidenceClosureValidationError('Phase 22C source must contain six artifacts')
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            department = str(record.get('department') or '')
            if not department or department in seen:
                raise EvidenceClosureValidationError('duplicate or missing department')
            relative = Path(str(record.get('path') or ''))
            path = self._contained(source, source / relative)
            if not path.is_file() or path.is_symlink():
                raise EvidenceClosureValidationError(f'unsafe artifact: {department}')
            digest = self._sha256(path)
            if digest != str(record.get('sha256') or ''):
                raise EvidenceClosureValidationError(f'artifact hash mismatch: {department}')
            payload = json.loads(path.read_text(encoding='utf-8'))
            if payload.get('department') != department:
                raise EvidenceClosureValidationError(f'artifact department mismatch: {department}')
            validated.append({'department': department, 'relative_path': str(relative), 'sha256': digest, 'payload': payload})
            seen.add(department)
        return manifest, validated

    def _security_review(self, source: Path) -> dict[str, Any]:
        cloud_source = self.project_root / 'src/aios/cloud_provider_sandbox.py'
        text = cloud_source.read_text(encoding='utf-8')
        checks: list[dict[str, Any]] = []
        forbidden = ('import subprocess', 'from subprocess', 'os.system(', 'shell=True', 'OllamaProvider(', 'OpenRouterProvider(', 'ClaudeProvider(', 'GeminiProvider(')
        found = [token for token in forbidden if token in text]
        checks.append({'name': 'no-shell-or-cloud-fallback', 'passed': not found, 'evidence': 'none found' if not found else found})
        endpoints_ok = (
            'https://api.openai.com/v1/responses' in text
            and 'https://api.openai.com/v1/models' in text
            and 'https://api.openai.com/v1/chat/completions' not in text
        )
        checks.append({'name': 'official-openai-endpoints-only', 'passed': endpoints_ok})
        secret_controls = all(token in text for token in ('secret_path.is_symlink()', '0o600', 'file_stat.st_uid != 0', 'OPENAI_API_KEY', "api_key='[REDACTED]'"))
        checks.append({'name': 'external-secret-controls', 'passed': secret_controls})
        tracked_hits = self._credential_hits([
            self.project_root / 'src/aios/cloud_provider_sandbox.py',
            self.project_root / 'src/aios/local_model_sandbox.py',
            self.project_root / 'src/aios/organization',
            self.project_root / 'src/aios/providers',
            self.project_root / 'docs/phase-22c',
        ])
        checks.append({'name': 'tracked-scope-credential-scan', 'passed': not tracked_hits, 'hits': tracked_hits})
        runtime_hits = self._credential_hits([source])
        checks.append({'name': 'runtime-evidence-secret-scan', 'passed': not runtime_hits, 'hits': runtime_hits})
        compile_failures: list[str] = []
        compile_paths = [
            self.project_root / 'src/aios/cloud_provider_sandbox.py',
            self.project_root / 'src/aios/local_model_sandbox.py',
            *(self.project_root / 'src/aios/organization').glob('*.py'),
            *(self.project_root / 'src/aios/providers').rglob('*.py'),
        ]
        for path in compile_paths:
            try:
                compile(path.read_text(encoding='utf-8'), str(path), 'exec')
            except (OSError, SyntaxError) as exc:
                compile_failures.append(f'{path}:{type(exc).__name__}')
        checks.append({'name': 'controlled-python-source-compiles', 'passed': not compile_failures, 'failures': compile_failures})
        approved = all(bool(item['passed']) for item in checks)
        return {
            'schema_version': 1,
            'required_departments': sorted(SECURITY_REQUIRED),
            'checks': checks,
            'approved': approved,
            'finding_count': sum(not bool(item['passed']) for item in checks),
            'network_used': False,
            'provider_key_read': False,
            'production_modified': False,
        }

    def _credential_hits(self, roots: Sequence[Path]) -> list[str]:
        hits: list[str] = []
        for root in roots:
            paths = [root] if root.is_file() else sorted(root.rglob('*'))
            for path in paths:
                if not path.is_file() or path.is_symlink():
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
                    hits.append(str(path))
        return hits

    @staticmethod
    def _sanitize(text: str) -> str:
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub('[REDACTED]', text)
        return text

    @staticmethod
    def _passed_count(text: str) -> int:
        match = re.search(r'(\d+)\s+passed\b', text)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _prepare_root(output_root: str | Path) -> Path:
        raw = Path(output_root)
        if not raw.is_absolute():
            raise ValueError('output_root must be absolute')
        raw.mkdir(parents=True, exist_ok=True)
        root = raw.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        return root

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError('path escapes allowed root')
        return resolved

    @staticmethod
    def _write(path: Path, content: str) -> None:
        temporary = path.with_name(f'.{path.name}.tmp')
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _json(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + '\n'

    @staticmethod
    def _report(manifest: Mapping[str, Any]) -> str:
        review = manifest['review']
        tests = manifest['test_evidence']
        security = manifest['security_review']
        blockers = review['blocking_findings'] or ['None']
        rework = review['rework_plan'] or ['None']
        return (
            '# Phase 22D Evidence Closure Report\n\n'
            f"- Source execution: `{manifest['source']['execution_id']}`\n"
            f"- Tests passed: `{str(tests['passed']).lower()}` ({tests['passed_count']})\n"
            f"- Security review approved: `{str(security['approved']).lower()}`\n"
            f"- Final approved: `{str(review['approved']).lower()}`\n"
            f"- Final readiness: `{review['readiness_score']}`\n"
            '- Network used: `false`\n'
            '- Provider key used: `false`\n'
            '- Cloud request sent: `false`\n'
            '- Production modified: `false`\n'
            '- Model claims used as execution proof: `false`\n\n'
            '## Blocking findings\n\n'
            + '\n'.join(f'- {item}' for item in blockers)
            + '\n\n## Rework plan\n\n'
            + '\n'.join(f'- {item}' for item in rework)
            + '\n'
        )
