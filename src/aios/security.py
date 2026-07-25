from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .db import Database
from .projects import ProjectRegistry


@dataclass(slots=True)
class Finding:
    severity: str
    confidence: float
    title: str
    evidence: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


class SecurityAnalyzer:
    TEXT_EXTENSIONS = {'.py', '.js', '.ts', '.php', '.java', '.go', '.rs', '.json', '.yaml', '.yml', '.toml', '.env', '.ini', '.conf'}
    RULES = (
        ('critical', 0.99, 'Possible private key',
         re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
         'Remove and rotate the key, then use a secrets manager.'),
        ('high', 0.85, 'Hard-coded secret',
         re.compile(r'''(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['"][^'"]{8,}['"]'''),
         'Move the secret to protected configuration and rotate exposed values.'),
        ('high', 0.85, 'Dangerous dynamic execution',
         re.compile(r'\b(eval|exec)\s*\('),
         'Remove dynamic execution or strictly isolate validated input.'),
        ('medium', 0.80, 'Shell execution enabled',
         re.compile(r'shell\s*=\s*True'),
         'Avoid shell=True and pass arguments as an array.'),
        ('medium', 0.75, 'Potentially weak hash',
         re.compile(r'\b(md5|sha1)\s*\(', re.IGNORECASE),
         'Use an appropriate modern algorithm.'),
        ('low', 0.80, 'Debug mode enabled',
         re.compile(r'(?i)\bdebug\s*=\s*(true|1)'),
         'Disable debug mode in production.'),
    )

    def __init__(self, db: Database, projects: ProjectRegistry):
        self.db = db
        self.projects = projects

    def scan(self, project_name: str) -> list[Finding]:
        project = self.projects.get(project_name)
        root = Path(project['path'])
        findings: list[Finding] = []
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in self.TEXT_EXTENSIONS:
                continue
            if any(part in {'.git', '.venv', 'node_modules', 'dist', 'build'} for part in path.parts):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            relative = path.relative_to(root)
            for severity, confidence, title, pattern, recommendation in self.RULES:
                for match in pattern.finditer(text):
                    line = text.count('\n', 0, match.start()) + 1
                    finding = Finding(severity, confidence, title, f'{relative}:{line}', recommendation)
                    findings.append(finding)
                    with self.db.connect() as conn:
                        conn.execute(
                            '''INSERT INTO findings(project, severity, confidence, title, evidence, recommendation)
                               VALUES (?, ?, ?, ?, ?, ?)''',
                            (project_name, severity, confidence, title, finding.evidence, recommendation),
                        )
        order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        return sorted(findings, key=lambda item: order.get(item.severity, 9))
