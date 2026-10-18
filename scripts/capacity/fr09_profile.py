#!/usr/bin/env python3
"""FR-09 expanded-capacity profile preflight.

This module prepares and validates the deterministic load profile only. It does
not open sockets, connect to databases, call providers, mutate production, or
run a load test. Actual capacity execution remains separately gated.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
import shutil
from pathlib import Path
from typing import Any

GIB = 1024**3

HISTORICAL_RECEIPTS = (
    "docs/phase-36/receipts/36N-2026-09-07-production-capacity-test.md",
    "docs/phase-36/receipts/36H-2026-08-24-scale-part6b.md",
    "docs/phase-36/receipts/36H-2026-09-05-realtime-production-activation.md",
    "docs/phase-36/receipts/36N-2026-09-07-server-capacity-guard.md",
)


class CapacityProfileError(ValueError):
    """Raised when the canonical expanded-capacity contract is incomplete."""


_INTEGER_FIELDS = (
    "authenticated_active_users",
    "projects_per_user_min",
    "conversations_per_user_min",
    "durable_jobs_min",
    "steady_state_minutes_min",
    "tenant_leaks_max",
    "lost_jobs_max",
    "duplicate_terminal_executions_max",
)
_METRIC_FIELDS = (
    "ordinary_read_p95_ms_max",
    "durable_enqueue_p95_ms_max",
    "unexpected_error_rate_max",
)


def _nonnegative_finite_number(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        raise CapacityProfileError(f"{label} must be a number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise CapacityProfileError(f"{label} must be finite") from exc
    if not math.isfinite(number) or number < 0:
        raise CapacityProfileError(f"{label} must be finite and non-negative")
    return number


@dataclass(frozen=True)
class CapacityProfile:
    authenticated_active_users: int
    projects_per_user_min: int
    conversations_per_user_min: int
    durable_jobs_min: int
    steady_state_minutes_min: int
    ordinary_read_p95_ms_max: float
    durable_enqueue_p95_ms_max: float
    unexpected_error_rate_max: float
    tenant_leaks_max: int
    lost_jobs_max: int
    duplicate_terminal_executions_max: int
    required_evidence: tuple[str, ...]

    @classmethod
    def from_plan(cls, plan: dict[str, Any]) -> "CapacityProfile":
        if not isinstance(plan, dict):
            raise CapacityProfileError("plan root must be an object")
        raw = plan.get("capacity_acceptance")
        if not isinstance(raw, dict):
            raise CapacityProfileError("capacity_acceptance object is required")
        evidence = raw.get("required_evidence", ())
        if not isinstance(evidence, (list, tuple)):
            raise CapacityProfileError("required evidence inventory must be a list")
        try:
            profile = cls(
                **{name: raw[name] for name in _INTEGER_FIELDS},
                **{
                    name: _nonnegative_finite_number(raw[name], name)
                    for name in _METRIC_FIELDS
                },
                required_evidence=tuple(evidence),
            )
        except KeyError as exc:
            raise CapacityProfileError("required capacity profile field is missing") from exc
        profile.validate()
        return profile

    def validate(self) -> None:
        for name in _INTEGER_FIELDS:
            if type(getattr(self, name)) is not int:
                raise CapacityProfileError(f"{name} must be an integer")
        for name in _METRIC_FIELDS:
            _nonnegative_finite_number(getattr(self, name), name)
        if self.authenticated_active_users < 5000:
            raise CapacityProfileError("full 5000-user acceptance requires at least 5000 users")
        if self.projects_per_user_min < 3:
            raise CapacityProfileError("expanded profile requires at least 3 projects/user")
        if self.conversations_per_user_min < 3:
            raise CapacityProfileError(
                "expanded profile requires at least 3 conversations/user"
            )
        if self.durable_jobs_min < self.authenticated_active_users * 3:
            raise CapacityProfileError("full profile requires at least 3 durable jobs per user")
        if self.steady_state_minutes_min < 15:
            raise CapacityProfileError("steady-state duration must be at least 15 minutes")
        if self.ordinary_read_p95_ms_max > 500:
            raise CapacityProfileError("ordinary-read p95 ceiling weakened")
        if self.durable_enqueue_p95_ms_max > 1000:
            raise CapacityProfileError("enqueue p95 ceiling weakened")
        if self.unexpected_error_rate_max > 0.005:
            raise CapacityProfileError("unexpected error-rate ceiling weakened")
        if any(
            value != 0
            for value in (
                self.tenant_leaks_max,
                self.lost_jobs_max,
                self.duplicate_terminal_executions_max,
            )
        ):
            raise CapacityProfileError("isolation/loss/duplicate ceilings must remain zero")
        if not isinstance(self.required_evidence, (list, tuple)):
            raise CapacityProfileError("required evidence inventory must be a list")
        if not self.required_evidence or any(
            not isinstance(item, str) or not item.strip()
            for item in self.required_evidence
        ):
            raise CapacityProfileError("required evidence inventory must contain non-empty strings")

    @property
    def total_projects(self) -> int:
        return self.authenticated_active_users * self.projects_per_user_min

    @property
    def total_conversations(self) -> int:
        return self.authenticated_active_users * self.conversations_per_user_min


@dataclass(frozen=True)
class RampStep:
    name: str
    users: int
    projects: int
    conversations: int
    durable_jobs: int
    steady_state_minutes: int


def build_ramp(profile: CapacityProfile) -> tuple[RampStep, ...]:
    user_steps = tuple(dict.fromkeys((25, 100, 250, 500, 1000, 2500, 5000, profile.authenticated_active_users)))
    steps: list[RampStep] = []
    for users in user_steps:
        ratio = users / profile.authenticated_active_users
        jobs = max(1, round(profile.durable_jobs_min * ratio))
        steps.append(
            RampStep(
                name=f"users-{users}",
                users=users,
                projects=users * profile.projects_per_user_min,
                conversations=users * profile.conversations_per_user_min,
                durable_jobs=jobs,
                steady_state_minutes=(
                    profile.steady_state_minutes_min
                    if users == profile.authenticated_active_users
                    else 0
                ),
            )
        )
    return tuple(steps)


def _fs_device(path: Path) -> int:
    return path.stat().st_dev


def measure_runtime_free_space() -> dict[str, Any]:
    """Read the real Docker/containerd backing filesystems; do not infer from /."""
    root = Path("/")
    docker = Path("/var/lib/docker")
    containerd = Path("/var/lib/containerd")
    root_device = _fs_device(root)
    runtime_devices = (_fs_device(docker), _fs_device(containerd))
    runtime_free = min(shutil.disk_usage(path).free for path in (docker, containerd))
    return {
        "measurement_paths": [str(docker), str(containerd)],
        "runtime_min_free_bytes": runtime_free,
        "runtime_fs_separate_from_root": all(dev != root_device for dev in runtime_devices),
        "docker_containerd_share_filesystem": runtime_devices[0] == runtime_devices[1],
    }


def build_preflight(
    profile: CapacityProfile,
    *,
    fr08_accepted: bool,
    free_bytes: int,
    heavy_min_free_bytes: int,
    measured_storage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not fr08_accepted:
        blockers.append("FR-08 dependency is not accepted")
    if heavy_min_free_bytes < 40 * GIB:
        blockers.append("heavy-work minimum free space cannot be weakened below 40 GiB")
    if free_bytes < heavy_min_free_bytes:
        blockers.append("free disk is below the configured heavy-work capacity gate")
    if measured_storage is None:
        blockers.append("Docker runtime filesystem capacity is not independently measured")
    else:
        if measured_storage.get("runtime_fs_separate_from_root") is not True:
            blockers.append("Docker/containerd runtime filesystem identity is not verified")
        measured_free = measured_storage.get("runtime_min_free_bytes")
        if type(measured_free) is not int or measured_free < heavy_min_free_bytes:
            blockers.append("Docker/containerd runtime free space is below the heavy-work gate")

    return {
        "schema": 1,
        "kind": "fr09-expanded-capacity-preflight",
        "profile": asdict(profile),
        "derived": {
            "total_projects_min": profile.total_projects,
            "total_conversations_min": profile.total_conversations,
            "durable_jobs_min": profile.durable_jobs_min,
        },
        "ramp": [asdict(step) for step in build_ramp(profile)],
        "historical_receipts": list(HISTORICAL_RECEIPTS),
        "historical_evidence_boundary": (
            "Historical 1000-participant/control-plane evidence is retained as "
            "baseline only and is not expanded-profile acceptance."
        ),
        "execution": {
            "load_test_started": False,
            "production_targeted": False,
            "provider_calls": False,
            "fr08_accepted": fr08_accepted,
            "free_bytes": free_bytes,
            "free_bytes_provenance": "operator_supplied_staging_budget_not_measured",
            "measured_runtime_storage": measured_storage,
            "heavy_min_free_bytes": heavy_min_free_bytes,
            "load_test_authorized": False,
            "heavy_work_permitted": not blockers,
            "blockers": blockers,
        },
    }


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CapacityProfileError("duplicate JSON field")
        result[key] = value
    return result


def _reject_nonfinite_json_number(value: str) -> Any:
    raise CapacityProfileError("non-finite JSON number")


def load_plan(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_nonfinite_json_number,
    )
    if not isinstance(value, dict):
        raise CapacityProfileError("plan root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--free-bytes", type=int, required=True)
    parser.add_argument("--heavy-min-free-bytes", type=int, default=40 * GIB)
    parser.add_argument("--fr08-accepted", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        profile = CapacityProfile.from_plan(load_plan(args.plan))
    except (OSError, UnicodeError, json.JSONDecodeError, CapacityProfileError) as exc:
        print(json.dumps({
            "status": "INVALID_PROFILE",
            "error_type": type(exc).__name__,
            "execution": {
                "load_test_authorized": False,
                "heavy_work_permitted": False,
                "load_test_started": False,
                "production_targeted": False,
                "provider_calls": False,
            },
        }, sort_keys=True))
        return 2
    try:
        measured_storage = measure_runtime_free_space()
    except (OSError, ValueError):
        # Absent/unreadable vault paths are a HOLD, never implicit root-disk PASS.
        measured_storage = None
    result = build_preflight(
        profile,
        fr08_accepted=args.fr08_accepted,
        free_bytes=args.free_bytes,
        heavy_min_free_bytes=args.heavy_min_free_bytes,
        measured_storage=measured_storage,
    )
    raw = json.dumps(
        result, indent=2, ensure_ascii=args.output is None, sort_keys=True, allow_nan=False
    ) + "\n"
    if args.output is None:
        print(raw, end="")
    else:
        args.output.write_text(raw, encoding="utf-8")
    # A HOLD must never appear successful to a CI/operator shell caller.
    return 0 if result["execution"]["heavy_work_permitted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
