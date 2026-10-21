"""JSONL records use physical LF delimiters, not Unicode string line boundaries."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("project_hub_unicode", ROOT / "scripts/project_hub.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)


def journal(root: Path, content: str) -> Path:
    path = root / "docs/project/runtime/events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    return path


@pytest.mark.parametrize("character", ["\u0085", "\u2028", "\u2029"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_unicode_line_characters_are_part_of_json_strings(tmp_path, character, newline):
    events = [
        {"event_id": "first", "summary_ar": "before" + character + "after"},
        {"event_id": "second", "evidence": ["same" + character + "path"]},
    ]
    path = journal(tmp_path, newline.join(json.dumps(e, ensure_ascii=False) for e in events) + newline)
    before = path.read_bytes()
    assert hub.read_events(tmp_path) == events
    assert path.read_bytes() == before


def test_legacy_utf8_misdecoded_as_latin1_roundtrips_without_rewriting(tmp_path):
    summary = "\u0645\u0647\u0645\u0629 \u0627\u0633\u062a\u0639\u0627\u062f\u0629".encode("utf-8").decode("latin1")
    event = {"event_id": "legacy", "summary_ar": summary}
    path = journal(tmp_path, json.dumps(event, ensure_ascii=False) + "\n")
    before = path.read_bytes()
    assert hub.read_events(tmp_path) == [event]
    assert path.read_bytes() == before


def test_json_whitespace_and_unterminated_final_record_are_supported(tmp_path):
    events = [{"event_id": "first"}, {"event_id": "last"}]
    journal(tmp_path, " \t\r\n" + json.dumps(events[0]) + "\r\n\n" + json.dumps(events[1]))
    assert hub.read_events(tmp_path) == events


@pytest.mark.parametrize("invalid", ["{", "{\"event_id\":", "\u0085", "\u2028", "\u2029", "{\"summary\":\"raw\rcarriage\"}"])
def test_invalid_record_is_not_skipped_or_partially_accepted(tmp_path, invalid):
    journal(tmp_path, '{"event_id": "valid"}\n' + invalid + "\n")
    with pytest.raises(json.JSONDecodeError):
        hub.read_events(tmp_path)


def test_record_and_replay_keep_unicode_content_and_acceptance_gates(tmp_path):
    plan = hub.load_plan(ROOT)
    directory = tmp_path / "docs/project"
    directory.mkdir(parents=True)
    (directory / "PLAN.json").write_text(json.dumps(plan), encoding="utf-8")
    event = {
        "event_id": "unicode-roundtrip", "batch_id": "FR-08", "status": "in_progress",
        "summary_ar": "before\u0085middle\u2028after\u2029end", "verification_passed": True,
    }
    first = hub.record(tmp_path, event)
    path = directory / "runtime/events.jsonl"
    original = path.read_bytes()
    second = hub.record(tmp_path, event)
    assert path.read_bytes() == original
    assert len(hub.read_events(tmp_path)) == 1
    assert first["last_event_id"] == second["last_event_id"] == event["event_id"]
    assert second["release_status"] == "FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED"
    assert second["batches"]["FR-08"]["status"] == "in_progress"
    assert hub.validate_runtime(tmp_path, plan)["last_event_id"] == event["event_id"]
