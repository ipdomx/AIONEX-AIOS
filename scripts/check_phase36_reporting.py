#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aios.phase36_program import phase36_reporting_violation  # noqa: E402


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )


def _changed_from_git(base: str | None) -> list[str]:
    normalized = (base or "").strip()
    if normalized and set(normalized) != {"0"}:
        result = _git("diff", "--name-only", f"{normalized}...HEAD")
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        result = _git("diff", "--name-only", f"{normalized}..HEAD")
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    result = _git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "unable to determine changed paths")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce Phase 36 reporting evidence")
    parser.add_argument("--base", default=os.getenv("PHASE36_BASE_SHA") or "")
    parser.add_argument("--files", nargs="*")
    args = parser.parse_args()
    paths = list(args.files) if args.files is not None else _changed_from_git(args.base)
    violations = phase36_reporting_violation(paths)
    if not violations:
        print(f"PHASE36_REPORTING_OK changed_paths={len(paths)}")
        return 0
    print("PHASE36_REPORTING_MISSING", file=sys.stderr)
    print(
        "Phase 36-owned product paths changed without updating the master roadmap, "
        "a Phase 36 receipt, or a documented exemption:",
        file=sys.stderr,
    )
    for path in violations:
        print(f"- {path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
