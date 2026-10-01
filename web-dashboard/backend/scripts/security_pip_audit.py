#!/opt/venv/bin/python
"""AIONEX entrypoint: pip-audit uses the image's pinned pip for temporary resolution.

Upstream pip-audit 2.10.1 bootstraps and upgrades another pip inside each temporary
venv. That would discard this image's reviewed vendored-library refresh. This
explicit adapter keeps its venv, input parsing, indexes, resolver and vulnerability
logic, but uses pip's --python option rather than installing another installer.
No audit exclusion, --no-deps override, network allowlist change or result filtering.
"""
from __future__ import annotations

import importlib.metadata
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def pip_command(executable: str, report: str, indexes: list[str], arguments: list[str]) -> list[str]:
    return [sys.executable, "-m", "pip", "--python", executable, "install", "--no-input",
            "--keyring-provider=subprocess", *indexes, "--dry-run", "--report", report, *arguments]


def configure() -> type[Any]:
    """Reject dependency drift; configure both upstream venv consumers identically."""
    import pip
    from packaging.version import Version
    # Upstream pip-audit 2.10.1 is annotated but does not ship a py.typed marker.
    from pip_audit import _virtual_env  # type: ignore[import-untyped]
    from pip_audit._dependency_source import pyproject, requirement  # type: ignore[import-untyped]
    from pip_audit._subprocess import CalledProcessError, run  # type: ignore[import-untyped]

    if pip.__version__ != "26.2.1+aios.1" or importlib.metadata.version("pip-audit") != "2.10.1":
        raise RuntimeError("Unreviewed pip or pip-audit version; refuse compatibility adapter")
    if getattr(_virtual_env.VirtualEnv, "_aios_pinned_pip", False):
        return _virtual_env.VirtualEnv

    class PinnedPipVirtualEnv(_virtual_env.VirtualEnv):
        _aios_pinned_pip = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.with_pip = False

        def post_setup(self, context: SimpleNamespace) -> None:
            self._state.update_state("Resolving with AIONEX image-pinned pip in an isolated environment")
            with tempfile.TemporaryDirectory(prefix="aios-pip-report-") as directory:
                report = Path(directory) / "report.json"
                command = pip_command(context.env_exe, str(report), self._index_url_args, self._install_args)
                try:
                    run(command, log_stdout=True, state=self._state)
                except CalledProcessError as exc:
                    # Do not report partial/empty findings as successful resolution.
                    raise _virtual_env.VirtualEnvError("Pinned pip dependency resolution failed") from exc
                payload = json.loads(report.read_text())
                if payload.get("version") != "1" or not isinstance(payload.get("install"), list):
                    raise _virtual_env.VirtualEnvError("Unexpected pip install-report schema")
                self._packages = [(row["metadata"]["name"], Version(row["metadata"]["version"])) for row in payload["install"]]

    for consumer in (_virtual_env, requirement, pyproject):
        setattr(consumer, "VirtualEnv", PinnedPipVirtualEnv)
    return PinnedPipVirtualEnv


def main() -> None:
    configure()
    from pip_audit._cli import audit  # type: ignore[import-untyped]

    audit()


if __name__ == "__main__":
    main()
