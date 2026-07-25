from __future__ import annotations

from pathlib import Path
import json
import re

from .models import SecurityFinding, Severity


class DependencySecurityAnalyzer:
    """Offline manifest analysis. CVE lookup is delegated to signed provider plugins later."""

    MANIFESTS = {"requirements.txt", "package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "composer.json"}

    def analyze(self, root: str | Path) -> tuple[SecurityFinding, ...]:
        root_path = Path(root).resolve()
        findings: list[SecurityFinding] = []
        manifests = [p for p in root_path.rglob("*") if p.is_file() and p.name in self.MANIFESTS]
        for path in manifests:
            rel = str(path.relative_to(root_path))
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.name == "requirements.txt":
                for line in text.splitlines():
                    item = line.strip()
                    if item and not item.startswith("#") and not re.search(r"(?:==|===|@\s+https?://)", item):
                        findings.append(self._unpinned(rel, item))
            elif path.name == "package.json":
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    findings.append(SecurityFinding("Invalid dependency manifest", "supply-chain", Severity.HIGH, rel,
                        "package.json could not be parsed.", ("Correct the manifest syntax.",), ("Parse the manifest and run package-manager validation.",), 1.0))
                    continue
                for section in ("dependencies", "devDependencies", "optionalDependencies"):
                    for name, version in payload.get(section, {}).items():
                        if isinstance(version, str) and (version in {"*", "latest"} or version.startswith(("git+", "http://"))):
                            findings.append(self._unpinned(rel, f"{name}@{version}"))
            if not self._has_lockfile(path.parent):
                findings.append(SecurityFinding("Dependency lock file missing", "supply-chain", Severity.MEDIUM, rel,
                    "A dependency manifest exists without a recognized lock file in the same directory.",
                    ("Generate and commit the package-manager lock file.",),
                    ("Perform a clean reproducible install and compare dependency resolution.",), 0.9))
        return tuple(findings)

    @staticmethod
    def _has_lockfile(directory: Path) -> bool:
        return any((directory / name).exists() for name in (
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
            "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock", "gradle.lockfile",
        ))

    @staticmethod
    def _unpinned(location: str, dependency: str) -> SecurityFinding:
        return SecurityFinding("Unpinned dependency", "supply-chain", Severity.MEDIUM, location,
            f"Dependency is not fixed to a reproducible version: {dependency}",
            ("Pin the dependency to an approved version and generate a lock file.",),
            ("Perform a clean install twice and verify identical resolved versions.",), 0.9,
            {"dependency": dependency})
