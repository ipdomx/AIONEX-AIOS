#!/usr/bin/env python3
"""Fail-closed binary/module reachability evidence for the FR-23 final audit.

This tool evaluates link-time Go module evidence emitted by the pinned AIOS
security-tool builds (go version -m). It intentionally does not mutate
dependency manifests, generate VEX, dismiss repository alerts, scan production,
or claim that a source-level advisory is closed because a module is not linked.

Exit codes:
  0: every supplied reachability rule passed
  1: at least one reachability rule failed
  2: malformed/incomplete policy or evidence (fail closed)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SEMVER = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?P<pre>-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
ALLOWED_RULE_MODES = {
    "absent",
    "min_version_or_absent",
    "prefix_min_version_or_absent",
}


class PolicyError(ValueError):
    """The committed FR-23 policy fixture is incomplete or unsafe."""


class EvidenceError(ValueError):
    """The supplied binary-module evidence is incomplete or ambiguous."""


@dataclass(frozen=True)
class LinkedModule:
    module: str
    version: str
    replacement_module: str | None = None
    replacement_version: str | None = None


def _semver_key(value: str) -> tuple[int, int, int, int, tuple[str, ...]]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise EvidenceError(f"unsupported semantic version: {value!r}")
    prerelease = match.group("pre")
    stable_rank = 1 if prerelease is None else 0
    pre_parts = tuple((prerelease or "").lstrip("-").split("."))
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stable_rank,
        pre_parts,
    )


def version_at_least(observed: str, minimum: str) -> bool:
    return _semver_key(observed) >= _semver_key(minimum)


def parse_go_version_m(text: str, *, minimum_dependency_count: int) -> dict[str, LinkedModule]:
    """Parse go version -m output and reject truncated/ambiguous evidence."""

    modules: dict[str, LinkedModule] = {}
    current_module: str | None = None
    build_lines = 0
    path_lines = 0

    for raw in text.splitlines():
        fields = raw.strip().split()
        if not fields:
            continue
        kind = fields[0]

        if kind == "path":
            path_lines += 1
            current_module = None
            continue
        if kind == "build":
            build_lines += 1
            current_module = None
            continue
        if kind == "dep":
            if len(fields) < 3:
                raise EvidenceError(f"malformed dependency line: {raw!r}")
            module, version = fields[1], fields[2]
            if module in modules and modules[module].version != version:
                raise EvidenceError(f"conflicting versions for linked module {module}")
            modules[module] = LinkedModule(module=module, version=version)
            current_module = module
            continue
        if kind == "=>":
            if current_module is None:
                raise EvidenceError("replacement line without preceding dependency")
            if len(fields) < 2:
                raise EvidenceError(f"malformed replacement line: {raw!r}")
            replacement_module = fields[1]
            replacement_version = fields[2] if len(fields) >= 3 and fields[2].startswith("v") else None
            previous = modules[current_module]
            modules[current_module] = LinkedModule(
                module=previous.module,
                version=previous.version,
                replacement_module=replacement_module,
                replacement_version=replacement_version,
            )
            current_module = None
            continue
        current_module = None

    if path_lines < 1 or build_lines < 1:
        raise EvidenceError("evidence does not look like complete go version -m output")
    if len(modules) < minimum_dependency_count:
        raise EvidenceError(
            f"dependency evidence is too small: {len(modules)} < {minimum_dependency_count}"
        )
    return modules


def _require_bool(mapping: dict[str, Any], key: str, expected: bool) -> None:
    if mapping.get(key) is not expected:
        raise PolicyError(f"policy {key!r} must be {expected!r}")


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read policy: {exc}") from exc

    if not isinstance(policy, dict) or policy.get("schema") != 1:
        raise PolicyError("policy schema 1 required")
    semantics = policy.get("semantics")
    tools = policy.get("tools")
    if not isinstance(semantics, dict) or not isinstance(tools, dict) or not tools:
        raise PolicyError("policy semantics and tools are required")

    _require_bool(semantics, "reachability_only", True)
    _require_bool(semantics, "dependabot_closure", False)
    preserved = semantics.get("preserved_open_alerts")
    if not isinstance(preserved, list) or not {48, 50}.issubset(set(preserved)):
        raise PolicyError("Dependabot HIGH alerts 48 and 50 must remain explicitly preserved OPEN")
    if semantics.get("final_live_closure_gated_by") != ["FR-06", "FR-21"]:
        raise PolicyError("FR-06 and FR-21 must remain the explicit final/live closure gates")

    for tool, config in tools.items():
        if not isinstance(tool, str) or not tool:
            raise PolicyError("tool names must be non-empty strings")
        if not isinstance(config, dict):
            raise PolicyError(f"tool {tool} configuration must be an object")
        minimum_count = config.get("minimum_dependency_count")
        if not isinstance(minimum_count, int) or minimum_count < 1:
            raise PolicyError(f"tool {tool} must define a positive minimum_dependency_count")
        rules = config.get("rules")
        if not isinstance(rules, list) or not rules:
            raise PolicyError(f"tool {tool} requires at least one rule")
        seen_ids: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                raise PolicyError(f"tool {tool} has a non-object rule")
            rule_id = rule.get("id")
            mode = rule.get("mode")
            if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
                raise PolicyError(f"tool {tool} has a missing/duplicate rule id")
            seen_ids.add(rule_id)
            if mode not in ALLOWED_RULE_MODES:
                raise PolicyError(f"rule {rule_id} has unsupported mode {mode!r}")
            if rule.get("closure_effect") != "none":
                raise PolicyError(f"rule {rule_id} must not claim source-alert closure")
            if mode in {"absent", "min_version_or_absent"}:
                if not isinstance(rule.get("module"), str) or not rule["module"]:
                    raise PolicyError(f"rule {rule_id} requires module")
            if mode == "prefix_min_version_or_absent":
                if not isinstance(rule.get("prefix"), str) or not rule["prefix"]:
                    raise PolicyError(f"rule {rule_id} requires prefix")
            if mode != "absent":
                minimum = rule.get("minimum")
                if not isinstance(minimum, str):
                    raise PolicyError(f"rule {rule_id} requires minimum version")
                _semver_key(minimum)
    return policy


def _replacement_error(module: LinkedModule) -> str | None:
    if module.replacement_module is None:
        return None
    suffix = f" {module.replacement_version}" if module.replacement_version is not None else ""
    return f"targeted module {module.module} is replaced by {module.replacement_module}{suffix}"


def evaluate_tool(tool: str, config: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
    try:
        raw = evidence_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"{tool}: cannot read evidence {evidence_path}: {exc}") from exc

    modules = parse_go_version_m(raw, minimum_dependency_count=config["minimum_dependency_count"])
    rules_out: list[dict[str, Any]] = []
    status = "PASS"

    for rule in config["rules"]:
        mode = rule["mode"]
        result: dict[str, Any] = {
            "id": rule["id"],
            "mode": mode,
            "closure_effect": "none",
            "status": "PASS",
        }

        if mode == "absent":
            module = modules.get(rule["module"])
            if module is not None:
                replacement = _replacement_error(module)
                if replacement:
                    raise EvidenceError(f"{tool}: {replacement}")
                result.update(
                    status="FAIL",
                    reason="module_is_linked",
                    module=module.module,
                    observed=module.version,
                )
                status = "FAIL"
            else:
                result.update(reason="module_not_linked", module=rule["module"])

        elif mode == "min_version_or_absent":
            module = modules.get(rule["module"])
            if module is None:
                result.update(reason="module_not_linked", module=rule["module"])
            else:
                replacement = _replacement_error(module)
                if replacement:
                    raise EvidenceError(f"{tool}: {replacement}")
                minimum = rule["minimum"]
                ok = version_at_least(module.version, minimum)
                result.update(
                    reason="version_at_or_above_floor" if ok else "version_below_floor",
                    module=module.module,
                    observed=module.version,
                    minimum=minimum,
                    status="PASS" if ok else "FAIL",
                )
                if not ok:
                    status = "FAIL"

        elif mode == "prefix_min_version_or_absent":
            matched = sorted(
                (m for name, m in modules.items() if name.startswith(rule["prefix"])),
                key=lambda item: item.module,
            )
            if not matched:
                result.update(reason="module_family_not_linked", prefix=rule["prefix"])
            else:
                minimum = rule["minimum"]
                rows = []
                failed = False
                for module in matched:
                    replacement = _replacement_error(module)
                    if replacement:
                        raise EvidenceError(f"{tool}: {replacement}")
                    ok = version_at_least(module.version, minimum)
                    rows.append(
                        {
                            "module": module.module,
                            "observed": module.version,
                            "minimum": minimum,
                            "ok": ok,
                        }
                    )
                    failed = failed or not ok
                result.update(
                    reason="all_family_versions_at_or_above_floor"
                    if not failed
                    else "module_family_contains_version_below_floor",
                    prefix=rule["prefix"],
                    matched=rows,
                    status="FAIL" if failed else "PASS",
                )
                if failed:
                    status = "FAIL"
        rules_out.append(result)

    return {
        "tool": tool,
        "status": status,
        "evidence": str(evidence_path),
        "evidence_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "dependency_count": len(modules),
        "rules": rules_out,
    }


def evaluate(policy: dict[str, Any], evidence: dict[str, Path]) -> tuple[int, dict[str, Any]]:
    expected = set(policy["tools"])
    supplied = set(evidence)
    if supplied != expected:
        missing = sorted(expected - supplied)
        unexpected = sorted(supplied - expected)
        raise EvidenceError(f"evidence set mismatch; missing={missing}, unexpected={unexpected}")

    results = []
    any_failed = False
    for tool in sorted(expected):
        result = evaluate_tool(tool, policy["tools"][tool], evidence[tool])
        results.append(result)
        any_failed = any_failed or result["status"] != "PASS"

    report = {
        "schema": 1,
        "status": "FAIL" if any_failed else "PASS",
        "semantics": policy["semantics"],
        "tools": results,
    }
    return (1 if any_failed else 0), report


def _parse_evidence_args(values: Iterable[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise EvidenceError("--evidence requires TOOL=PATH")
        tool, path = value.split("=", 1)
        if not tool or not path or tool in result:
            raise EvidenceError(f"invalid/duplicate evidence selector: {value!r}")
        result[tool] = Path(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="TOOL=PATH",
        help="go version -m evidence for one policy tool; repeat for every tool",
    )
    args = parser.parse_args(argv)

    try:
        policy = load_policy(args.policy)
        evidence = _parse_evidence_args(args.evidence)
        code, report = evaluate(policy, evidence)
    except (PolicyError, EvidenceError) as exc:
        report = {
            "schema": 1,
            "status": "ERROR",
            "error": str(exc),
            "semantics": {
                "reachability_only": True,
                "dependabot_closure": False,
                "preserved_open_alerts": [48, 50],
            },
        }
        code = 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
