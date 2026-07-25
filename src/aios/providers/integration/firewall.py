from __future__ import annotations

import re
from dataclasses import replace

from ..models import ModelRequest


class PromptContextFirewall:
    _secret_patterns = (
        re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    )
    _instruction_patterns = (
        re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"),
        re.compile(r"(?i)reveal\s+(the\s+)?system\s+prompt"),
    )

    def sanitize(self, request: ModelRequest) -> tuple[ModelRequest, tuple[str, ...]]:
        text = request.prompt
        findings: list[str] = []
        for pattern in self._secret_patterns:
            if pattern.search(text):
                text = pattern.sub("[REDACTED]", text)
                findings.append("secret-redacted")
        for pattern in self._instruction_patterns:
            if pattern.search(text):
                findings.append("untrusted-instruction-detected")
        metadata = dict(request.metadata)
        metadata["firewall_findings"] = tuple(findings)
        return replace(request, prompt=text, metadata=metadata), tuple(findings)
