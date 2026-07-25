from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .digital_twin import TwinSnapshot


@dataclass(slots=True, frozen=True)
class DefenseFinding:
    severity: str
    category: str
    title: str
    location: str
    evidence: str
    remediation: tuple[str, ...]
    test_plan: tuple[str, ...]
    confidence: float


class DefenseIntelligenceCenter:
    """Authorized, defensive project review. It identifies risks but does not exploit them."""

    SECRET_PATTERNS = (
        re.compile(r'(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*["\']?[^\s"\']{8,}'),
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    )

    def audit(self, snapshot: TwinSnapshot, *, authorization: bool) -> tuple[DefenseFinding, ...]:
        if not authorization:
            raise PermissionError('Recorded authorization is required before defensive analysis')
        root = Path(snapshot.root)
        findings: list[DefenseFinding] = []
        for record in snapshot.files:
            path = root / record.path
            if record.size > 1_000_000:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for pattern in self.SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append(DefenseFinding(
                        'critical', 'secrets', 'Possible embedded credential', record.path,
                        'A credential-like value appears in source-controlled content.',
                        ('Revoke and rotate the credential', 'Move it to a secret manager or environment variable',
                         'Add automated secret scanning to CI'),
                        ('Verify the old credential is revoked', 'Run a repository history scan',
                         'Confirm the application loads the replacement securely'), 0.92,
                    ))
                    break
            if 'subprocess' in text and ('shell=True' in text or 'os.system(' in text):
                findings.append(DefenseFinding(
                    'high', 'command-execution', 'Potential unsafe command execution', record.path,
                    'Dynamic shell execution can permit command injection if input is not strictly controlled.',
                    ('Use argument arrays without a shell', 'Apply strict allowlists', 'Run with least privilege'),
                    ('Add malicious-input unit tests', 'Run static analysis', 'Verify commands in a sandbox'), 0.88,
                ))
            if record.language == 'python' and ('verify=False' in text or 'CERT_NONE' in text):
                findings.append(DefenseFinding(
                    'high', 'transport-security', 'TLS verification appears disabled', record.path,
                    'Disabling certificate verification weakens authenticity and confidentiality guarantees.',
                    ('Restore certificate verification', 'Install the correct CA chain', 'Fail closed on TLS errors'),
                    ('Connect with a valid certificate', 'Confirm invalid certificates are rejected'), 0.95,
                ))
        if not any(path.name.lower().startswith(('test_', 'spec')) for path in root.rglob('*') if path.is_file()):
            findings.append(DefenseFinding(
                'medium', 'quality', 'No automated tests detected', snapshot.root,
                'The project scan did not find conventional automated test files.',
                ('Create risk-based unit and integration tests', 'Add tests to CI'),
                ('Introduce a known defect and confirm the test suite catches it',), 0.75,
            ))
        return tuple(findings)
