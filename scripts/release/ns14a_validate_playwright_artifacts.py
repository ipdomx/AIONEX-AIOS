#!/usr/bin/env python3
"""Fail closed when a Playwright JSON report references artifacts not retained."""
from __future__ import annotations
import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

FAIL_STATUSES = {"failed", "timedOut", "unexpected", "interrupted"}

MAX_ATTACHMENT_BYTES = 128 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024


def audit(report: dict[str, Any], evidence_root: Path, expected_tests: int = 6) -> dict[str, Any]:
    """Evidence retention is separate from six-case NS14A acceptance."""
    attachments: list[dict[str, str]] = []
    failed_results = 0
    case_statuses: list[str] = []
    if not 1 <= expected_tests <= 12:
        raise ValueError("invalid NS14A expected test count")
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise ValueError("private evidence root must be a physical directory")
    root = evidence_root.resolve(strict=True)

    def walk(node: Any) -> None:
        nonlocal failed_results
        if isinstance(node, dict):
            if isinstance(node.get("tests"), list):
                for test in node["tests"]:
                    case_statuses.append(str(test.get("status")) if isinstance(test, dict) else "invalid")
            status = node.get("status")
            value = node.get("attachments")
            if isinstance(status, str) and status in FAIL_STATUSES and isinstance(value, list):
                failed_results += 1
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        attachments.append({
                            "name": str(item.get("name", "unknown")),
                            "path": item["path"],
                        })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(report)
    retained = 0
    missing: list[dict[str, str]] = []
    unsafe: list[dict[str, str]] = []
    by_name: dict[str, dict[str, int]] = {}
    for item in attachments:
        name = item["name"]
        counts = by_name.setdefault(name, {"referenced": 0, "retained": 0, "missing": 0})
        counts["referenced"] += 1
        raw = item["path"]
        relative = raw[1:] if raw.startswith("/") else raw
        parts = Path(relative).parts
        if (
            not relative.startswith("test-results/")
            or ".." in parts
            or "\\" in relative
            or "\x00" in relative
            or Path(relative).is_absolute()
            or len(parts) < 3
        ):
            unsafe.append(item)
            counts["missing"] += 1
            continue
        target = root.joinpath(*parts)
        try:
            # Reject every symlink component, not merely a final linked file.
            current = root
            for component in parts:
                current = current / component
                if current.is_symlink():
                    raise ValueError("symlink in evidence attachment path")
            resolved = target.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError("attachment escaped retained evidence root")
            metadata = target.lstat()
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_ATTACHMENT_BYTES:
                raise ValueError("missing, empty, oversized or non-regular evidence")
            retained += 1
            counts["retained"] += 1
        except (OSError, ValueError):
            missing.append(item)
            counts["missing"] += 1
    report_errors = report.get("errors", [])
    report_errors_invalid = not isinstance(report_errors, list) or bool(report_errors)
    count_ok = len(case_statuses) == expected_tests
    status_ok = all(x in ("expected", "unexpected") for x in case_statuses)
    accepted = (
        not unsafe and not missing and count_ok and status_ok
        and not report_errors_invalid
        and (failed_results == 0 or len(attachments) > 0)
    )
    all_cases_passed = accepted and not failed_results and all(x == "expected" for x in case_statuses)
    return {
        "schema_version": 2,
        "kind": "playwright_artifact_retention_audit",
        "cases_expected": expected_tests,
        "cases_reported": len(case_statuses),
        "case_statuses": case_statuses,
        "all_original_tests_passed": all_cases_passed,
        "report_errors_present": report_errors_invalid,
        "failed_result_nodes": failed_results,
        "attachments_referenced": len(attachments),
        "attachments_retained": retained,
        "attachments_missing": len(missing) + len(unsafe),
        "by_name": by_name,
        "unsafe_paths": unsafe,
        "missing": missing,
        "retention_gate_passed": accepted,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_json", type=Path)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--expected-tests", type=int, default=6)
    args = parser.parse_args()
    if args.report_json.is_symlink() or not args.report_json.is_file():
        parser.error("report must be a physical regular file")
    if not 0 < args.report_json.stat().st_size <= MAX_REPORT_BYTES:
        parser.error("report size invalid")
    report = json.loads(args.report_json.read_text(encoding="utf-8"))
    result = audit(report, args.evidence_root, args.expected_tests)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["retention_gate_passed"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
