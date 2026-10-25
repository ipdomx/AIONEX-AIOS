"""Verify real model proof is fail-closed and separate from worker jobs."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fr09_local_inference", ROOT / "scripts" / "capacity" / "fr09_local_inference.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_reject_external_providers_and_paths():
    for value in (
        "https://ollama:11434", "http://api.openai.com:11434",
        "http://ollama:11435", "http://u:p@ollama:11434",
        "http://ollama:11434/api/generate", "http://ollama:11434/?a=1",
    ):
        with pytest.raises(ValueError):
            mod.local_endpoint(value)
    assert mod.local_endpoint("http://ollama:11434") == "http://ollama:11434"


def test_large_run_refused_without_isolation(monkeypatch):
    monkeypatch.delenv("AIOS_FR09_ISOLATED_LAB", raising=False)
    assert mod.isolation_tier(4, "http://ollama:11434", None) == "SAMPLE_ONLY"
    with pytest.raises(ValueError):
        mod.isolation_tier(15000, "http://ollama:11434", None)


def test_unproven_attestation_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_FR09_ISOLATED_LAB", "true")
    attestation = tmp_path / "receipt.json"
    attestation.write_text(json.dumps({"deployment_tier": "isolated_load_lab"}))
    with pytest.raises(ValueError):
        mod.isolation_tier(15000, "http://127.0.0.1:11434", str(attestation))


def test_attested_loopback_only(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_FR09_ISOLATED_LAB", "true")
    attestation = tmp_path / "receipt.json"
    attestation.write_text(json.dumps({
        "deployment_tier": "isolated_load_lab",
        "production_container_overlap": 0,
        "production_database_mounted": False,
        "paid_provider_egress": False,
        "approved_max_requests": 15000,
        "lab_run_id": "isolated-fr09-20261025",
    }))
    assert mod.isolation_tier(15000, "http://127.0.0.1:11434", str(attestation)) == "ATTESTED_ISOLATED_LAB"
    with pytest.raises(ValueError):
        mod.isolation_tier(15000, "http://ollama:11434", str(attestation))


def ok(expected="POSITIVE"):
    return {"model": "gemma3:4b", "done": True, "done_reason": "stop",
            "response": expected, "prompt_eval_count": 12, "eval_count": 3,
            "eval_duration": 3_000_000}


@pytest.mark.parametrize("key,value", [
    ("model", "fake"), ("done", False), ("done_reason", "length"),
    ("response", "wrong"), ("eval_count", 0),
    ("prompt_eval_count", 0), ("eval_duration", 0),
])
def test_fake_or_truncated_call_never_passes(key, value):
    reply = ok()
    reply[key] = value
    assert mod.validate_reply(reply, "POSITIVE", "gemma3:4b")


def test_unique_prompts_both_answer_classes():
    prompts = [mod.prompt_for(i) for i in range(24)]
    assert len({p for p, _ in prompts}) == 24
    assert {cls for _, cls in prompts} == {"POSITIVE", "NEGATIVE"}


def test_confirmed_calls_still_not_full_release(monkeypatch):
    def fake(base, route, payload, timeout):
        if route == "/api/tags":
            return {"models": [{"name": "gemma3:4b", "digest": "d"*64}]}
        case = int(payload["prompt"].split("FR09-")[1][:6])
        return ok(mod.CASES[case % len(mod.CASES)][1])
    monkeypatch.setattr(mod, "local_json", fake)
    proof = mod.receipt("http://ollama:11434", "gemma3:4b", 4, 2, 10, 20)
    assert proof["status"] == "SAMPLE_VERIFIED_NOT_FR09_RELEASE_EVIDENCE"
    assert proof["verified_real_inference_calls"] == 4
    assert proof["durable_worker_jobs_proven"] == 0
    assert proof["fr25_released"] is False
    assert len(proof["receipt_hash_chain_sha256"]) == 64


def test_first_failure_halts_bounded_batch(monkeypatch):
    attempts = []
    def fake(base, route, payload, timeout):
        if route == "/api/tags":
            return {"models": [{"name": "gemma3:4b", "digest": "d"*64}]}
        attempts.append(1)
        return ok("BAD")
    monkeypatch.setattr(mod, "local_json", fake)
    proof = mod.receipt("http://ollama:11434", "gemma3:4b", 10, 2, 10, 20)
    assert len(attempts) == 2
    assert proof["status"] == "INFERENCE_PROOF_INCOMPLETE_HOLD"
    assert proof["verified_real_inference_calls"] == 0
