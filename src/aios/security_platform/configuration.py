from __future__ import annotations

from pathlib import Path
import json
import re

from .models import SecurityFinding, Severity


class ConfigurationSecurityAnalyzer:
    def analyze(self, root: str | Path) -> tuple[SecurityFinding, ...]:
        root_path = Path(root).resolve()
        findings: list[SecurityFinding] = []
        for path in root_path.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            rel = str(path.relative_to(root_path))
            if path.name in {"Dockerfile", "Containerfile"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if not re.search(r"(?im)^\s*USER\s+[^\s]+", text) or re.search(r"(?im)^\s*USER\s+(?:root|0)\s*$", text):
                    findings.append(SecurityFinding("Container may run as root", "container-security", Severity.HIGH, rel,
                        "No non-root USER directive was detected, or root is explicitly selected.",
                        ("Create a dedicated unprivileged user and switch to it before runtime.",),
                        ("Inspect the running container UID and verify privileged operations fail.",), 0.93))
                if re.search(r"(?im)^\s*FROM\s+[^\s:]+(?::latest)?\s*$", text):
                    findings.append(SecurityFinding("Unpinned container base image", "supply-chain", Severity.MEDIUM, rel,
                        "The base image is untagged or uses latest.",
                        ("Pin the base image to an approved immutable digest.",),
                        ("Rebuild and verify the resolved image digest.",), 0.9))
                if re.search(r"(?im)^\s*(?:ADD|COPY)\s+\.\s+", text):
                    findings.append(SecurityFinding("Broad container build context", "container-security", Severity.LOW, rel,
                        "The full build context is copied, which may include unnecessary or sensitive files.",
                        ("Use a restrictive .dockerignore and copy only required paths.",),
                        ("Inspect the final image contents for excluded files.",), 0.78))
            elif path.name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "privileged: true" in text.lower():
                    findings.append(SecurityFinding("Privileged container enabled", "container-security", Severity.CRITICAL, rel,
                        "A compose service enables privileged mode.",
                        ("Remove privileged mode and grant only the exact capabilities required.",),
                        ("Run integration tests with the reduced capability set.",), 0.99))
                if re.search(r"(?m)^\s*network_mode:\s*host\s*$", text):
                    findings.append(SecurityFinding("Host network mode enabled", "network-security", Severity.HIGH, rel,
                        "A service shares the host network namespace.",
                        ("Use an isolated application network and expose only required ports.",),
                        ("Verify service reachability and blocked ports after isolation.",), 0.95))
            elif path.name.endswith((".tf", ".tf.json")):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r'0\.0\.0\.0/0', text) and re.search(r'(?i)(ingress|cidr_blocks)', text):
                    findings.append(SecurityFinding("Potentially public infrastructure rule", "cloud-security", Severity.HIGH, rel,
                        "An ingress-related rule references 0.0.0.0/0.",
                        ("Restrict source networks to approved CIDR ranges.", "Use a gateway or identity-aware proxy where appropriate."),
                        ("Validate the deployed rule and test access from unauthorized networks.",), 0.86))
            elif path.name == "package.json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                scripts = data.get("scripts", {})
                if any("--no-sandbox" in str(value) for value in scripts.values()):
                    findings.append(SecurityFinding("Browser sandbox disabled", "runtime-security", Severity.HIGH, rel,
                        "A package script disables the browser sandbox.",
                        ("Remove --no-sandbox and correct the runtime permissions or container configuration.",),
                        ("Run browser-based tests with the sandbox enabled.",), 0.94))
        return tuple(findings)
