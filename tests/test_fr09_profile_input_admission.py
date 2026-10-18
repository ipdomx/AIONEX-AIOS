from __future__ import annotations

import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "capacity" / "fr09_profile.py"
SPEC = importlib.util.spec_from_file_location("fr09_profile_inputs", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def canonical_plan() -> dict:
    return json.loads(
        (ROOT / "docs" / "project" / "PLAN.json").read_text(encoding="utf-8")
    )


def test_direct_profile_validation_rejects_string_evidence() -> None:
    valid = module.CapacityProfile.from_plan(canonical_plan())
    altered = replace(valid, required_evidence="receipt")

    with pytest.raises(module.CapacityProfileError):
        altered.validate()


@pytest.mark.parametrize("evidence", [["receipt"], ("receipt",)])
def test_direct_profile_validation_preserves_list_and_tuple_evidence(evidence) -> None:
    valid = module.CapacityProfile.from_plan(canonical_plan())
    altered = replace(valid, required_evidence=evidence)

    altered.validate()
    assert altered.required_evidence == evidence


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated_active_users", 5000.9),
        ("authenticated_active_users", "5000"),
        ("projects_per_user_min", 3.9),
        ("tenant_leaks_max", False),
    ],
)
def test_target_values_are_not_silently_coerced(field: str, value: object) -> None:
    plan = canonical_plan()
    plan["capacity_acceptance"][field] = value

    with pytest.raises(module.CapacityProfileError):
        module.CapacityProfile.from_plan(plan)


@pytest.mark.parametrize(
    "field",
    [
        "ordinary_read_p95_ms_max",
        "durable_enqueue_p95_ms_max",
        "unexpected_error_rate_max",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_slo_does_not_become_a_valid_profile(field: str, value: float) -> None:
    plan = canonical_plan()
    plan["capacity_acceptance"][field] = value

    with pytest.raises(module.CapacityProfileError):
        module.CapacityProfile.from_plan(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordinary_read_p95_ms_max", -1),
        ("durable_enqueue_p95_ms_max", False),
        ("unexpected_error_rate_max", "0.005"),
    ],
)
def test_slo_values_require_nonnegative_numbers(field: str, value: object) -> None:
    plan = canonical_plan()
    plan["capacity_acceptance"][field] = value

    with pytest.raises(module.CapacityProfileError):
        module.CapacityProfile.from_plan(plan)


@pytest.mark.parametrize("evidence", ["receipt", [], [""], [None]])
def test_evidence_inventory_cannot_be_a_string_or_empty_items(evidence: object) -> None:
    plan = canonical_plan()
    plan["capacity_acceptance"]["required_evidence"] = evidence

    with pytest.raises(module.CapacityProfileError):
        module.CapacityProfile.from_plan(plan)


@pytest.mark.parametrize(
    "raw",
    [
        '{"capacity_acceptance": {}, "capacity_acceptance": {}}',
        '{"extra": [{"users": 4999, "users": 5000}]}',
        '{"extra": {"users": 5000, "\\u0075sers": 5000}}',
    ],
)
def test_duplicate_plan_keys_are_rejected_at_all_depths(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(module.CapacityProfileError):
        module.load_plan(path)


@pytest.mark.parametrize("case", ["duplicate", "nan", "missing_field", "non_utf8"])
def test_invalid_cli_input_fails_before_runtime_measurement(
    monkeypatch, tmp_path: Path, capsys, case: str
) -> None:
    plan = canonical_plan()
    if case == "nan":
        plan["capacity_acceptance"]["ordinary_read_p95_ms_max"] = float("nan")
    if case == "missing_field":
        del plan["capacity_acceptance"]["durable_jobs_min"]
    raw = json.dumps(plan)
    if case == "duplicate":
        raw = raw.replace(
            '"authenticated_active_users": 5000',
            '"authenticated_active_users": 4999, "authenticated_active_users": 5000',
            1,
        )
    path = tmp_path / "invalid-plan.json"
    path.write_bytes(b'{"invalid": "\xff"}' if case == "non_utf8" else raw.encode("utf-8"))

    def unexpected_measurement():
        raise AssertionError("invalid input must be rejected before runtime inspection")

    monkeypatch.setattr(module, "measure_runtime_free_space", unexpected_measurement)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH), "--plan", str(path),
            "--free-bytes", str(45 * module.GIB), "--fr08-accepted",
        ],
    )
    assert module.main() == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "INVALID_PROFILE"
    assert report["execution"] == {
        "load_test_authorized": False,
        "heavy_work_permitted": False,
        "load_test_started": False,
        "production_targeted": False,
        "provider_calls": False,
    }
    assert captured.err == ""


@pytest.mark.parametrize("write_file", [False, True])
def test_non_ascii_evidence_survives_cli_under_ascii_locale(
    tmp_path: Path, write_file: bool
) -> None:
    plan = copy.deepcopy(canonical_plan())
    plan["capacity_acceptance"]["required_evidence"] = ["دليل عربي محفوظ"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    output_path = tmp_path / "output.json"
    code = """
import importlib.util
from pathlib import Path
import sys
source, plan, output = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("fr09_profile_ascii", source)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.measure_runtime_free_space = lambda: {
    "runtime_fs_separate_from_root": True,
    "runtime_min_free_bytes": 45 * module.GIB,
}
sys.argv = [source, "--plan", plan, "--free-bytes", str(45 * module.GIB), "--fr08-accepted"]
if output:
    sys.argv += ["--output", output]
raise SystemExit(module.main())
"""
    child_env = dict(
        os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0",
        PYTHONIOENCODING="ascii:strict",
    )
    completed = subprocess.run(
        [
            sys.executable, "-c", code, str(MODULE_PATH), str(plan_path),
            str(output_path) if write_file else "",
        ],
        env=child_env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("ascii", errors="replace")
    raw = output_path.read_text(encoding="utf-8") if write_file else completed.stdout.decode("ascii")
    report = json.loads(raw)
    assert report["profile"]["required_evidence"] == ["دليل عربي محفوظ"]
    assert report["execution"]["heavy_work_permitted"] is True
    assert report["execution"]["load_test_authorized"] is False
    assert report["execution"]["load_test_started"] is False
