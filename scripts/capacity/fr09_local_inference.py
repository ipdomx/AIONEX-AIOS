#!/usr/bin/env python3
"""Strict local Ollama model-call evidence; does not replace FR09 mixed-load acceptance."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MIN_FULL_INFERENCES = 15000
MAX_PROD_SAMPLE = 16
CASES = (
    ("The backup restored every file successfully.", "POSITIVE"),
    ("The API failed every request.", "NEGATIVE"),
    ("All workers passed their health checks.", "POSITIVE"),
    ("The queue lost several acknowledged jobs.", "NEGATIVE"),
    ("The dashboard loaded quickly without errors.", "POSITIVE"),
    ("The deployment crashed before any users could log in.", "NEGATIVE"),
    ("The security scan confirmed the vulnerability was fixed.", "POSITIVE"),
    ("The database lost committed customer records.", "NEGATIVE"),
)


def local_endpoint(value: str) -> str:
    p = urlsplit(value)
    if (p.scheme != "http" or p.hostname not in {"ollama", "127.0.0.1", "localhost"}
            or p.port != 11434 or p.username is not None or p.password is not None
            or p.path not in ("", "/") or p.query or p.fragment):
        raise ValueError("Only a private direct Ollama endpoint on port 11434 is permitted")
    return f"http://{p.hostname}:{p.port}"


def isolation_tier(count: int, endpoint: str, receipt: str | None) -> str:
    if count < 1 or count > MIN_FULL_INFERENCES:
        raise ValueError("Invalid count")
    if count <= MAX_PROD_SAMPLE:
        return "SAMPLE_ONLY"
    if os.getenv("AIOS_FR09_ISOLATED_LAB") != "true" or endpoint != "http://127.0.0.1:11434":
        raise ValueError("High volume requires an attested isolated lab and loopback Ollama")
    if not receipt:
        raise ValueError("Missing isolation receipt")
    data = json.loads(Path(receipt).read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("deployment_tier") != "isolated_load_lab"
            or data.get("production_container_overlap") != 0
            or data.get("production_database_mounted") is not False
            or data.get("paid_provider_egress") is not False
            or type(data.get("approved_max_requests")) is not int
            or data["approved_max_requests"] < count
            or not isinstance(data.get("lab_run_id"), str)
            or len(data["lab_run_id"]) < 12):
        raise ValueError("Isolation attestation incomplete")
    return "ATTESTED_ISOLATED_LAB"


def prompt_for(index: int) -> tuple[str, str]:
    report, expected = CASES[index % len(CASES)]
    return (
        "Classify sentiment of this service report. Reply only POSITIVE or NEGATIVE, "
        "uppercase with no explanation or punctuation.\n"
        f"Audit case FR09-{index:06d}\nReport: {report}",
        expected,
    )


class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Ollama must never redirect requests")


def local_json(base: str, route: str, data: dict | None, timeout: float) -> dict:
    # Reject system proxies and follow no redirects, even before inspecting response.
    opener = build_opener(ProxyHandler({}), RefuseRedirect())
    body = json.dumps(data).encode() if data is not None else None
    req = Request(base + route, data=body,
                  headers={"Content-Type": "application/json"},
                  method="POST" if body is not None else "GET")
    with opener.open(req, timeout=timeout) as reply:
        if reply.status != 200 or reply.url != base + route:
            raise ValueError("Nonlocal redirect or bad response")
        result = json.loads(reply.read(1_000_000))
    if not isinstance(result, dict):
        raise ValueError("Not a JSON object")
    return result


def resolve_model_digest(base: str, model: str, timeout: float) -> str:
    entries = local_json(base, "/api/tags", None, timeout).get("models")
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and item.get("name") == model:
                digest = item.get("digest")
                if isinstance(digest, str) and len(digest) >= 32:
                    return digest
    raise ValueError("Model digest not confirmed")


def validate_reply(reply: object, expected: str, model: str) -> list[str]:
    if not isinstance(reply, dict):
        return ["invalid_payload"]
    failures = []
    if reply.get("model") != model:
        failures.append("model_mismatch")
    if reply.get("done") is not True or reply.get("done_reason") != "stop":
        failures.append("not_fully_generated")
    if (type(reply.get("prompt_eval_count")) is not int or reply["prompt_eval_count"] <= 0
            or type(reply.get("eval_count")) is not int or reply["eval_count"] <= 0):
        failures.append("no_real_token_counts")
    if not isinstance(reply.get("response"), str) or reply["response"].strip().upper() != expected:
        failures.append("wrong_or_unverified_answer")
    if type(reply.get("eval_duration")) is not int or reply["eval_duration"] <= 0:
        failures.append("missing_model_compute_time")
    return failures


def trial(base: str, model: str, index: int, timeout: float) -> dict:
    prompt, expected = prompt_for(index)
    result = {
        "request_index": index,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha256": None,
        "validated": False,
        "generated_tokens": 0,
        "prompt_tokens": 0,
        "failures": [],
    }
    started = time.monotonic()
    try:
        reply = local_json(base, "/api/generate", {
            "model": model, "prompt": prompt, "stream": False, "keep_alive": "5m",
            "options": {"num_predict": 24, "num_ctx": 1024, "temperature": 0},
        }, timeout)
        result["failures"] = validate_reply(reply, expected, model)
        result["response_sha256"] = hashlib.sha256(str(reply.get("response", "")).encode()).hexdigest()
        result["generated_tokens"] = reply.get("eval_count") if type(reply.get("eval_count")) is int else 0
        result["prompt_tokens"] = reply.get("prompt_eval_count") if type(reply.get("prompt_eval_count")) is int else 0
        result["validated"] = not result["failures"]
    except Exception as exc:
        # Never include potentially private exception text, tokens or headers.
        result["failures"] = [type(exc).__name__]
    result["wall_ms"] = round(1000 * (time.monotonic() - started), 2)
    return result


def receipt(base: str, model: str, count: int, concurrency: int,
            timeout: float, deadline: float, isolation_receipt: str | None = None) -> dict:
    base = local_endpoint(base)
    tier = isolation_tier(count, base, isolation_receipt)
    if concurrency < 1 or concurrency > (4 if tier == "SAMPLE_ONLY" else 16):
        raise ValueError("Concurrency exceeds safe capacity profile")
    if timeout < 1 or timeout > 180 or deadline < 1:
        raise ValueError("Timeout limits invalid")
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    digest = resolve_model_digest(base, model, timeout)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        for offset in range(0, count, concurrency):
            seconds_left = deadline - (time.monotonic() - start)
            if seconds_left <= 0:
                break
            indices = list(range(offset, min(count, offset + concurrency)))
            batch = list(pool.map(
                lambda i: trial(base, model, i, min(timeout, max(1.0, seconds_left))), indices,
            ))
            results.extend(batch)
            if any(not item["validated"] for item in batch):
                break
    elapsed = time.monotonic() - start
    hash_chain = "0" * 64
    for item in results:
        hash_chain = hashlib.sha256(
            (hash_chain + json.dumps(item, sort_keys=True, separators=(",", ":"))).encode()
        ).hexdigest()
    valid = [item for item in results if item["validated"]]
    complete = len(results) == count and len(valid) == count
    if not complete:
        status = "INFERENCE_PROOF_INCOMPLETE_HOLD"
    elif tier == "ATTESTED_ISOLATED_LAB" and count == MIN_FULL_INFERENCES:
        status = "LOCAL_MODEL_15000_VERIFIED_NOT_FULL_FR09"
    else:
        status = "SAMPLE_VERIFIED_NOT_FR09_RELEASE_EVIDENCE"
    latency = sorted(item["wall_ms"] for item in results)
    return {
        "schema": "aionex.fr09.local-ollama-model-evidence.v1",
        "status": status,
        "start_utc": started_at,
        "finish_utc": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "model": model,
        "model_digest": digest,
        "endpoint_category": "local_ollama" if base == "http://ollama:11434" else "loopback",
        "requested": count,
        "attempted": len(results),
        "verified_real_inference_calls": len(valid),
        "unverified_calls": len(results) - len(valid),
        "verified_output_tokens": sum(x["generated_tokens"] for x in valid),
        "elapsed_seconds": round(elapsed, 3),
        "inferences_per_second": round(len(valid) / elapsed, 5) if elapsed else 0,
        "p95_wall_ms": latency[math.ceil(len(latency) * .95)-1] if latency else None,
        "receipt_hash_chain_sha256": hash_chain,
        "samples": results,
        "paid_provider_calls": 0,
        "used_customer_data": False,
        "durable_worker_jobs_proven": 0,
        "fr09_full_mixed_accepted": False,
        "fr25_released": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default="http://ollama:11434")
    p.add_argument("--model", default="gemma3:4b")
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--max-wall-seconds", type=float, default=180)
    p.add_argument("--isolation-receipt")
    args = p.parse_args()
    try:
        result = receipt(args.endpoint, args.model, args.count, args.concurrency,
                         args.timeout, args.max_wall_seconds, args.isolation_receipt)
    except Exception as exc:
        print(json.dumps({"status": "INFERENCE_PROOF_REFUSED",
                          "error_class": type(exc).__name__, "fr25_released": False}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] != "INFERENCE_PROOF_INCOMPLETE_HOLD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
