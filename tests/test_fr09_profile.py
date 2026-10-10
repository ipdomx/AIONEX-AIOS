from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

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

    assert profile.authenticated_active_users == 5000
    assert profile.projects_per_user_min == 3
    assert profile.conversations_per_user_min == 3
    assert profile.total_projects == 15000
    assert profile.total_conversations == 15000
    assert profile.durable_jobs_min == 15000
    assert profile.steady_state_minutes_min == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated_active_users", 4999),
        ("projects_per_user_min", 2),
        ("conversations_per_user_min", 2),
        ("durable_jobs_min", 14999),
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

    assert [step.users for step in steps] == [25, 100, 250, 500, 1000, 2500, 5000]
    final = steps[-1]
    assert final.projects == 15000
    assert final.conversations == 15000
    assert final.durable_jobs == 15000
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
        "Docker runtime filesystem capacity is not independently measured",
    ]


def test_only_current_dependency_and_capacity_can_open_heavy_gate() -> None:
    profile = module.CapacityProfile.from_plan(canonical_plan())
    result = module.build_preflight(
        profile,
        fr08_accepted=True,
        free_bytes=40 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
        measured_storage={
            "runtime_fs_separate_from_root": True,
            "runtime_min_free_bytes": 45 * module.GIB,
        },
    )

    assert result["execution"]["load_test_authorized"] is False
    assert result["execution"]["heavy_work_permitted"] is True
    assert result["execution"]["blockers"] == []



def test_large_root_does_not_hide_small_encrypted_docker_runtime(monkeypatch) -> None:
    free_by_path = {
        "/var/lib/docker": 23 * module.GIB,
        "/var/lib/containerd": 23 * module.GIB,
    }
    monkeypatch.setattr(
        module.shutil, "disk_usage",
        lambda path: SimpleNamespace(free=free_by_path[str(path)]),
    )
    monkeypatch.setattr(module, "_fs_device", lambda path: 1 if str(path) == "/" else 2)
    measured = module.measure_runtime_free_space()

    assert measured["docker_containerd_share_filesystem"] is True
    assert measured["runtime_fs_separate_from_root"] is True
    assert measured["runtime_min_free_bytes"] == 23 * module.GIB
    result = module.build_preflight(
        module.CapacityProfile.from_plan(canonical_plan()),
        fr08_accepted=True,
        free_bytes=3 * 1024**4,
        heavy_min_free_bytes=40 * module.GIB,
        measured_storage=measured,
    )
    assert result["execution"]["heavy_work_permitted"] is False
    assert "Docker/containerd runtime free space is below the heavy-work gate" in result["execution"]["blockers"]


def test_unmounted_docker_runtime_on_root_never_counts_as_verified(monkeypatch) -> None:
    monkeypatch.setattr(
        module.shutil, "disk_usage",
        lambda path: SimpleNamespace(free=300 * module.GIB),
    )
    monkeypatch.setattr(module, "_fs_device", lambda path: 1)
    measured = module.measure_runtime_free_space()
    assert measured["runtime_fs_separate_from_root"] is False
    result = module.build_preflight(
        module.CapacityProfile.from_plan(canonical_plan()),
        fr08_accepted=True,
        free_bytes=300 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
        measured_storage=measured,
    )
    assert result["execution"]["heavy_work_permitted"] is False
    assert "Docker/containerd runtime filesystem identity is not verified" in result["execution"]["blockers"]


def test_missing_runtime_measurement_never_claims_heavy_gate() -> None:
    result = module.build_preflight(
        module.CapacityProfile.from_plan(canonical_plan()),
        fr08_accepted=True,
        free_bytes=300 * module.GIB,
        heavy_min_free_bytes=40 * module.GIB,
        measured_storage=None,
    )
    assert result["execution"]["heavy_work_permitted"] is False
    assert result["execution"]["load_test_authorized"] is False


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


def test_historical_1000_user_profile_is_not_a_5000_user_release_gate():
    historic = copy.deepcopy(canonical_plan())
    historic["capacity_acceptance"]["authenticated_active_users"] = 1000
    historic["capacity_acceptance"]["durable_jobs_min"] = 3000
    with pytest.raises(module.CapacityProfileError, match="5000 users"):
        module.CapacityProfile.from_plan(historic)


def test_durable_jobs_scale_with_users_and_cannot_be_understated():
    plan = copy.deepcopy(canonical_plan())
    plan["capacity_acceptance"]["authenticated_active_users"] = 6000
    plan["capacity_acceptance"]["durable_jobs_min"] = 15000
    with pytest.raises(module.CapacityProfileError, match="3 durable jobs per user"):
        module.CapacityProfile.from_plan(plan)


def test_5000_intermediate_ramp_is_present_for_higher_capacity():
    plan = copy.deepcopy(canonical_plan())
    plan["capacity_acceptance"]["authenticated_active_users"] = 6000
    plan["capacity_acceptance"]["durable_jobs_min"] = 18000
    profile = module.CapacityProfile.from_plan(plan)
    assert [step.users for step in module.build_ramp(profile)] == [25, 100, 250, 500, 1000, 2500, 5000, 6000]
