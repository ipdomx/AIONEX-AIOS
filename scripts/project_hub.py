"""Canonical project report renderer and append-only, evidence-gated batch journal.

PLAN.json is reviewed in Git. Runtime receipts and the current report are generated
in the same directory, so deployment evidence can be recorded immediately without
creating an unreviewed change in the production source tree.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"planned", "in_progress", "local_verified", "merged", "deployment_failed", "complete"}
LABELS = {"planned": "لم تبدأ", "in_progress": "قيد التنفيذ", "local_verified": "مختبرة محليًا — لم تغلق", "merged": "مدمجة — ينتظر القبول التشغيلي", "deployment_failed": "فشل نشر/تحقق — غير مغلقة", "complete": "مغلقة بالدليل"}


def load_plan(root: Path) -> dict[str, Any]:
    return json.loads((root / "docs/project/PLAN.json").read_text(encoding="utf-8"))


def validate_plan(plan: dict[str, Any]) -> None:
    ids = [b["id"] for b in plan["batches"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate batch id")
    known = set(ids)
    seen: set[str] = set()
    for batch in plan["batches"]:
        if not set(batch["depends_on"]) <= seen:
            raise ValueError("dependencies must precede their batch")
        seen.add(batch["id"])
    caps = plan["capabilities"]
    if len(caps) != 62 or len({c["capability_id"] for c in caps}) != 62:
        raise ValueError("the 62-capability baseline must remain fully accounted for")
    for cap in caps:
        if cap.get("scope") == "deferred":
            if not cap.get("deferred_reason"):
                raise ValueError("deferred capability requires an Owner reason")
        elif not cap.get("final_batches") or not set(cap["final_batches"]) <= known:
            raise ValueError("unowned capability")
    for item in plan["audit_findings"]:
        if not item["batches"] or not set(item["batches"]) <= known:
            raise ValueError("unowned audit finding")
    if len(plan["owner_decisions"]["deferred"]) != 4:
        raise ValueError("Owner deferred scope changed")
    profile = plan["capacity_acceptance"]
    if profile["authenticated_active_users"] < 5000 or profile["projects_per_user_min"] < 3 or profile["conversations_per_user_min"] < 3:
        raise ValueError("capacity acceptance weakened")


def read_events(root: Path) -> list[dict[str, Any]]:
    path = root / "docs/project/runtime/events.jsonl"
    if not path.exists():
        return []
    # JSON Lines records are delimited by physical LF bytes. str.splitlines()
    # also splits valid JSON string characters such as U+0085/U+2028/U+2029.
    # Do not silently discard non-JSON whitespace or partially valid records.
    with path.open("r", encoding="utf-8", newline="\n") as stream:
        return [json.loads(line) for line in stream if line.strip(" \t\r\n")]


FR25_NATURAL_SAMPLE_RE = re.compile(r"FR25-NATURAL-\d{8}T\d+Z\.json")


def fr25_natural_sample_refs(event: dict[str, Any]) -> set[str]:
    """Return unique immutable FR25 raw-sample filenames credited by one event."""
    references: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            references.update(FR25_NATURAL_SAMPLE_RE.findall(value))
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(event.get("evidence", []))
    return references


def declared_fr25_reference_exceptions(events: list[dict[str, Any]]) -> dict[str, frozenset[str]]:
    """Load exact, independently verified historical duplicate-reference acknowledgements."""
    exceptions: dict[str, frozenset[str]] = {}
    for event in events:
        if (
            event.get("schema") != "aionex.fr25.g7-evidence-dedup-audit-event.v1"
            or event.get("verification_passed") is not True
            or event.get("evidence_reference_duplicate_detected") is not True
        ):
            continue
        sample = event.get("duplicate_raw_sample")
        event_ids = event.get("duplicate_event_ids")
        if (
            not isinstance(sample, str)
            or FR25_NATURAL_SAMPLE_RE.fullmatch(sample) is None
            or not isinstance(event_ids, list)
            or len(event_ids) != 2
            or any(not isinstance(item, str) or not item for item in event_ids)
            or len(set(event_ids)) != 2
        ):
            raise ValueError("invalid FR25 duplicate-reference acknowledgement")
        declared = frozenset(event_ids)
        if sample in exceptions and exceptions[sample] != declared:
            raise ValueError("conflicting FR25 duplicate-reference acknowledgements")
        exceptions[sample] = declared
    return exceptions


def validate_fr25_sample_references(events: list[dict[str, Any]]) -> None:
    """Prevent distinct events from granting continuity credit for one raw sample."""
    references: dict[str, set[str]] = {}
    for event in events:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            continue
        for sample in fr25_natural_sample_refs(event):
            references.setdefault(sample, set()).add(event_id)
    exceptions = declared_fr25_reference_exceptions(events)
    for sample, event_ids in references.items():
        if len(event_ids) > 1 and frozenset(event_ids) != exceptions.get(sample):
            raise ValueError(f"duplicate FR25 natural sample evidence reference: {sample}")


def validate_runtime(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Read and validate the runtime journal under the writer's lock."""
    directory = root / "docs/project/runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".journal.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        return current_state(plan, read_events(root))


def apply_event(plan: dict[str, Any], states: dict[str, dict[str, Any]], event: dict[str, Any]) -> None:
    batch = next((b for b in plan["batches"] if b["id"] == event.get("batch_id")), None)
    if batch is None or event.get("status") not in STATUSES:
        raise ValueError("unknown batch or status")
    if not event.get("event_id") or not event.get("summary_ar"):
        raise ValueError("receipt identity and summary are required")
    if event["status"] == "complete":
        if not re.fullmatch(r"[0-9a-f]{40}", str(event.get("merge_commit", ""))):
            raise ValueError("completion requires exact merge commit")
        if event.get("protected_checks_passed") is not True or int(event.get("protected_check_count", 0)) < 1:
            raise ValueError("completion requires protected checks")
        if event.get("verification_passed") is not True or not event.get("evidence"):
            raise ValueError("completion requires retained verification evidence")
        if batch["requires_deploy"] and event.get("deployment_verified") is not True:
            raise ValueError("merge alone is not deployment")
        if any(states[d]["status"] != "complete" for d in batch["depends_on"]):
            raise ValueError("unfinished prerequisite")
        if batch["id"] == "FR-09":
            result = event.get("capacity_result", {})
            policy = plan["capacity_acceptance"]
            for key in ["authenticated_active_users", "projects_per_user_min", "conversations_per_user_min", "durable_jobs_min", "steady_state_minutes_min"]:
                if result.get(key, 0) < policy[key]:
                    raise ValueError("expanded capacity evidence missing")
            for key in ["ordinary_read_p95_ms_max", "durable_enqueue_p95_ms_max", "unexpected_error_rate_max", "tenant_leaks_max", "lost_jobs_max", "duplicate_terminal_executions_max"]:
                if key not in result or result[key] > policy[key]:
                    raise ValueError("capacity SLO failed or unmeasured")
    states[batch["id"]] = dict(event)


def current_state(plan: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    states = {b["id"]: {"status": "planned"} for b in plan["batches"]}
    seen: set[str] = set()
    for event in events:
        if event.get("event_id") in seen:
            raise ValueError("duplicate event id in journal")
        apply_event(plan, states, event)
        seen.add(event["event_id"])
    validate_fr25_sample_references(events)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_status": "RELEASED_VERIFIED" if states["FR-25"]["status"] == "complete" else "FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED",
        "canonical_report": plan["report"],
        "last_event_id": events[-1]["event_id"] if events else None,
        "next_batch": next((b["id"] for b in plan["batches"] if states[b["id"]]["status"] != "complete"), None),
        "batches": states,
        "deferred": plan["owner_decisions"]["deferred"],
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def render(root: Path, plan: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    state = current_state(plan, events)
    out = ["# التقرير والخريطة الموحدان — AIONEX AIOS", "", f"الحالة: **{state['release_status']}**", f"آخر تحديث UTC: {state['generated_at']}", f"الدفعة التالية: **{state['next_batch']}**", "", plan["goal_ar"], "", "هذا هو مدخل المتابعة الحالي. PLAN.json هو عقد الخطة المتعقب، وruntime/events.jsonl سجل التنفيذ المحفوظ. التقارير السابقة أدلة تاريخية لا نقاط متابعة متنافسة.", "", "## قرارات المالك الملزمة"]
    for key, value in plan["owner_decisions"].items():
        if isinstance(value, list):
            out.append(f"**{key}:** " + "؛ ".join(value))
        else:
            out.append(f"**{key}:** {value}")
        out.append("")
    out += ["## جدول التنفيذ والإغلاق", "", "| الدفعة | المطلوب | الحالة |", "|---|---|---|"]
    for batch in plan["batches"]:
        out.append(f"| {batch['id']} | {batch['title_ar']} | {LABELS[state['batches'][batch['id']]['status']]} |")
    out += ["", "## التفاصيل ومعيار الإغلاق لكل دفعة"]
    for batch in plan["batches"]:
        out += ["", f"### {batch['id']} — {batch['title_ar']}", batch["scope_ar"], "", f"**شرط الإغلاق:** {batch['exit_ar']}", f"**تعتمد على:** {', '.join(batch['depends_on']) or 'لا شيء'}"]
        if batch.get("sub_batches"):
            out.append("**التجزئة الداخلية:** " + "؛ ".join(batch["sub_batches"]))
        record = state["batches"][batch["id"]]
        if record.get("summary_ar"):
            out += [f"**آخر تنفيذ:** {record['summary_ar']}", f"**مرجع الدمج:** {record.get('merge_commit', 'لم يثبت بعد')}", "**الأدلة:** " + "؛ ".join(record.get("evidence", []))]
    out += ["", f"## عقد قبول {plan['capacity_acceptance']['authenticated_active_users']} مستخدم متعدد المشاريع والمحادثات", "", "```json", json.dumps(plan["capacity_acceptance"], ensure_ascii=False, indent=2), "```", "", "## القدرات الـ62 — لا قدرة بلا مالك إغلاق", "", "التصنيف أدناه هو تصنيف المصدر عند إنشاء الخطة، وليس ترقية تلقائية. القبول النهائي مرتبط بدفعاته وإيصالاتها.", "", "| القدرة | التصنيف التاريخي | الدفعة النهائية / التأجيل |", "|---|---|---|"]
    for cap in plan["capabilities"]:
        out.append(f"| {cap['capability_id']} | {cap['maturity']} | {', '.join(cap.get('final_batches', [])) or cap.get('deferred_reason', '')} |")
    out += ["", "## الوظائف الأساسية السابقة التي لا تسقط من النطاق", "", "؛ ".join(plan["core_feature_groups"]), "", "## مطابقة جميع نتائج التدقيق", "", "| المرجع | النتيجة | المسؤول عن الإغلاق |", "|---|---|---|"]
    for item in plan["audit_findings"]:
        out.append(f"| {item['id']} | {item['finding_ar']} | {', '.join(item['batches'])} |")
    out += ["", "## حالة الانطلاق والمصادر", "", "```json", json.dumps(plan["baseline"], ensure_ascii=False, indent=2), "```", "", "مراجع المصدر والوثائق كاملة في SOURCE-INDEX.json؛ رد الاستضافة وتوجيه المالك في baseline/OWNER-DIRECTIVE-2026-09-10.md.", "", "## سجل التنفيذ الحديث"]
    for event in events[-30:]:
        out += ["", f"**{event.get('at', '')} / {event['batch_id']} / {LABELS[event['status']]}** — {event['summary_ar']}"]
    out += ["", "## قاعدة الاعتماد", "لا تعتمد جاهزية الإطلاق من نجاح خدمة أو نسبة إجمالية. لا RELEASED_VERIFIED قبل إغلاق FR-25 بجميع متطلباته، ولا يغلق اختبار السعة بنتيجة أقل من الملف الموسع. كل دليل يميز المحلي عن المزود الحقيقي وعن النشر والدمج. الأمان المطلق غير مدعى.", ""]
    atomic_write(root / "docs/project/STATE.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    atomic_write(root / plan["report"], "\n".join(out))
    return state


def record(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    plan = load_plan(root)
    validate_plan(plan)
    directory = root / "docs/project/runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".journal.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        events = read_events(root)
        for prior in events:
            if prior.get("event_id") == event.get("event_id"):
                comparable = {k: v for k, v in prior.items() if k != "at"}
                incoming = {k: v for k, v in event.items() if k != "at"}
                if comparable != incoming:
                    raise ValueError("same event id with conflicting content")
                return render(root, plan, events)
        event = dict(event)
        event.setdefault("at", datetime.now(timezone.utc).isoformat())
        current_state(plan, [*events, event])
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return render(root, plan, [*events, event])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "render", "record"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    plan = load_plan(args.root)
    validate_plan(plan)
    if args.command == "validate":
        validate_runtime(args.root, plan)
        print("PROJECT_HUB_VALIDATION_PASS")
        return
    if args.command == "record":
        if args.receipt is None:
            parser.error("--receipt is required")
        state = record(args.root, json.loads(args.receipt.read_text(encoding="utf-8")))
    else:
        directory = args.root / "docs/project/runtime"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".journal.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = render(args.root, plan, read_events(args.root))
    print(json.dumps({"release_status": state["release_status"], "next_batch": state["next_batch"], "report": str(args.root / plan["report"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
