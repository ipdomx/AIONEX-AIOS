from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "capacity" / "fr09_profile.py"
SPEC = importlib.util.spec_from_file_location("fr09_profile", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def canonical_plan() -> dict:
    return json.loads((ROOT / "docs" / "project" / "PLAN.json").read_text())


def test_canonical_expanded_profile_matches_required_topology() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())

    assert profile.authenticated_active_users == 1000
    assert profile.projects_per_user_min == 3
    assert profile.conversations_per_user_min == 3
    assert profile.total_projects == 3000
    assert profile.total_conversations == 3000
    assert profile.durable_jobs_min == 3000
    assert profile.steady_state_minutes_min == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated_active_users", 999),
        ("projects_per_user_min", 2),
        ("conversations_per_user_min", 2),
        ("durable_jobs_min", 2999),
        ("steady_state_minutes_min", 14),
        ("ordinary_read_p95_ms_max", 501),
        ("durable_enqueue_p95_ms_max", 1001),
        ("unexpected_error_rate_max", 0.006),
        ("tenant_leaks_max", 1),
        ("lost_jobs_max", 1),
        ("duplicate_terminal_executions_max", 1),
    ],
)
def test_weakened_expanded_profile_is_rejected(field: str, value: object) -> None:
    plan = copy.deepcopy(canonical_plan())
    plan["capacity_acceptance"][field] = value

    with pytest.raises(module.CapacityProfileError):
        module.CapacityProfile.from_plan(plan)


def test_ramp_finishes_at_full_profile_without_inventing_extra_conversations() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())
    steps = module.build_ramp(profile)

    assert [step.users for step in steps] == [25, 100, 250, 500, 1000]
    final = steps[-1]
    assert final.projects == 3000
    assert final.conversations == 3000
    assert final.durable_jobs == 3000
    assert final.steady_state_minutes == 15


def test_dependency_and_disk_gate_block_heavy_execution() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())
    result = module.build_preflight(
        profile,
        fr08_accepted=False,
        free_bytes=31 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
    )

    assert result["execution"]["load_test_started"] is False
    assert result["execution"]["production_targeted"] is False
    assert result["execution"]["provider_calls"] is False
    assert result["execution"]["heavy_work_permitted"] is False
    assert result["execution"]["blockers"] == [
        "FR-08 dependency is not accepted",
        "free disk is below the configured heavy-work capacity gate",
    ]


def test_only_current_dependency_and_capacity_can_open_heavy_gate() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())
    result = module.build_preflight(
        profile,
        fr08_accepted=True,
        free_bytes=40 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
    )

    assert result["execution"]["heavy_work_permitted"] is True
    assert result["execution"]["blockers"] == []


def test_historical_evidence_is_retained_as_baseline_not_acceptance() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())
    result = module.build_preflight(
        profile,
        fr08_accepted=False,
        free_bytes=31 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
    )

    assert len(result["historical_receipts"]) == 4
    assert "baseline only" in result["historical_evidence_boundary"]
    assert "expanded-profile acceptance" in result["historical_evidence_boundary"]
