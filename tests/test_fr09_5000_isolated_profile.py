"""FR09H 5000-authenticated mixed capacity profile; admission only, never production load."""
import json
from pathlib import Path
from scripts.capacity.fr09_profile import CapacityProfile, build_preflight, build_ramp, GIB

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "docs/project/capacity/FR-09H-5000-MIXED-PROFILE.json"

def test_5000_mixed_profile_preserves_strict_original_invariants():
    source = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = CapacityProfile.from_plan(source)
    assert source["capacity_acceptance"]["status"] == "NOT_RUN_OR_ACCEPTED"
    assert profile.authenticated_active_users == 5000
    assert profile.projects_per_user_min == profile.conversations_per_user_min == 3
    assert profile.total_projects == profile.total_conversations == 15000
    assert profile.durable_jobs_min == 15000
    assert profile.steady_state_minutes_min >= 15
    assert profile.ordinary_read_p95_ms_max <= 500
    assert profile.durable_enqueue_p95_ms_max <= 1000
    assert profile.unexpected_error_rate_max <= 0.005
    assert profile.tenant_leaks_max == profile.lost_jobs_max == profile.duplicate_terminal_executions_max == 0
    assert len(profile.required_evidence) >= 10

def test_5000_ramp_is_explicit_and_sustains_full_profile_only_at_final_step():
    profile = CapacityProfile.from_plan(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    ramp = build_ramp(profile)
    assert [step.users for step in ramp] == [25, 100, 250, 500, 5000]
    assert [step.steady_state_minutes for step in ramp] == [0, 0, 0, 0, 15]
    assert (ramp[-1].projects, ramp[-1].conversations, ramp[-1].durable_jobs) == (15000, 15000, 15000)

def test_not_allowed_to_run_on_current_encrypted_runtime_vault_or_without_fr08():
    doc = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = CapacityProfile.from_plan(doc)
    result = build_preflight(profile, fr08_accepted=False, free_bytes=23*GIB, heavy_min_free_bytes=40*GIB)
    assert result["execution"]["heavy_work_permitted"] is False
    assert result["execution"]["load_test_started"] is False
    assert result["execution"]["production_targeted"] is False
    assert result["execution"]["provider_calls"] is False
    assert result["execution"]["blockers"]
    assert doc["execution_guard"]["load_test_acceptance"] is False

def test_full_space_is_not_a_pass_without_fr08_and_must_not_pretend_execution():
    profile = CapacityProfile.from_plan(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    blocked = build_preflight(profile, fr08_accepted=False, free_bytes=100*GIB, heavy_min_free_bytes=40*GIB)
    assert blocked["execution"]["heavy_work_permitted"] is False
    assert "FR-08 dependency is not accepted" in blocked["execution"]["blockers"]
    admissible = build_preflight(profile, fr08_accepted=True, free_bytes=40*GIB, heavy_min_free_bytes=40*GIB)
    assert admissible["execution"]["heavy_work_permitted"] is True
    assert admissible["execution"]["load_test_started"] is False
    assert admissible["execution"]["production_targeted"] is False
    assert admissible["execution"]["provider_calls"] is False

def test_original_plan_baseline_remains_separate_from_5000_owner_acceptance():
    baseline = json.loads((ROOT / "docs/project/PLAN.json").read_text(encoding="utf-8"))
    target = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    original = CapacityProfile.from_plan(baseline)
    expanded = CapacityProfile.from_plan(target)
    assert original.authenticated_active_users <= expanded.authenticated_active_users
    assert original.total_projects <= expanded.total_projects
    assert original.total_conversations <= expanded.total_conversations
    assert original.durable_jobs_min <= expanded.durable_jobs_min
