"""Required CI must include the canonical stacked review queue, without widening pushes.

These source configuration regressions do not make manually dispatched checks
eligible for branch protection and do not authorize a merge or deployment.
"""
from pathlib import Path
import fnmatch
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ("final-validation.yml", "codeql.yml", "phase34e-container-security.yml")


def block(name, event):
    text = (ROOT / ".github/workflows" / name).read_text()
    match = re.search(r"(?m)^  " + re.escape(event) + r":\n((?:^    .*\n)+)", text)
    assert match is not None, f"missing {event} event in {name}"
    return match.group(1)


def branches(name, event):
    match = re.fullmatch(r"    branches: \[(.+)\]\n", block(name, event))
    assert match is not None, "required events must not gain path/type skip filters"
    return [x.strip().strip("\"'") for x in match.group(1).split(",")]


@pytest.mark.parametrize("name", WORKFLOWS)
def test_current_review_queue_is_included(name):
    assert branches(name, "pull_request") == ["main", "fix/fr06-source-rollup-*"]


@pytest.mark.parametrize("name", WORKFLOWS)
def test_push_scope_remains_main_only(name):
    assert branches(name, "push") == ["main"]


@pytest.mark.parametrize("name", WORKFLOWS)
def test_stacked_pull_request_scope_is_precise(name):
    patterns = branches(name, "pull_request")
    for target in ("main", "fix/fr06-source-rollup-20261001T1126", "fix/fr06-source-rollup-next"):
        assert any(fnmatch.fnmatchcase(target, pattern) for pattern in patterns)
    for target in ("main/other", "release/unrelated", "fix/unrelated", "", "fix/fr06-native-install-other"):
        assert not any(fnmatch.fnmatchcase(target, pattern) for pattern in patterns)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_manual_diagnostic_entry_is_retained_without_replacing_pr_event(name):
    text = (ROOT / ".github/workflows" / name).read_text()
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", text)
    assert "  pull_request_target:" not in text
    assert "  contents: read\n" in text
    assert "jobs:\n" in text
