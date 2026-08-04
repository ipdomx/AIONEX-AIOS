import asyncio
import hashlib
import inspect
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

import aios.local_model_sandbox as sandbox_module
from aios.local_model_sandbox import (
    ALLOWED_OLLAMA_ENDPOINT,
    CgroupResourceMonitor,
    LocalModelSandbox,
    OllamaLocalHTTPTransport,
    SandboxValidationError,
)
from aios.offline_execution import OfflineMockExecutor
from aios.providers.adapters import OllamaProvider


IMAGE_DIGEST = "ollama/ollama@sha256:" + "4" * 64
PROVIDER_KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_HOST",
)


def valid_department_payload(department, criteria, *, tests_passed=True, security_reviewed=True):
    return {
        "schema_version": 1,
        "department": department,
        "summary": f"Concrete {department} design with isolated implementation boundaries and verification evidence.",
        "implementation_plan": [
            f"Implement the first {department} control with explicit inputs, outputs, and failure handling.",
            f"Validate the second {department} control using deterministic assertions and archived results.",
            f"Review the final {department} control against rollback, monitoring, and operational requirements.",
        ],
        "technical_evidence": [
            {
                "criterion": criterion,
                "evidence": f"The {department} artifact documents concrete evidence for {criterion}.",
                "verification": f"Run a deterministic {department} verification for {criterion} and archive the result.",
            }
            for criterion in criteria
        ],
        "risks": [
            {
                "risk": f"A {department} boundary could regress under an unexpected integration change.",
                "mitigation": f"Use isolated {department} regression checks and a reviewed rollback procedure.",
            }
        ],
        "tests_passed": tests_passed,
        "security_reviewed": security_reviewed,
    }


class FakeRawTransport:
    def __init__(self, *, mode="valid", tests_passed=True, security_reviewed=True):
        self.mode = mode
        self.tests_passed = tests_passed
        self.security_reviewed = security_reviewed
        self.calls = []

    async def __call__(self, payload):
        self.calls.append(payload)
        metadata = payload["metadata"]
        department = metadata["department"]
        criteria = tuple(metadata["acceptance_criteria"])
        if self.mode == "invalid-json":
            text = "not-json"
        else:
            result = valid_department_payload(
                department,
                criteria,
                tests_passed=self.tests_passed,
                security_reviewed=self.security_reviewed,
            )
            if self.mode == "missing-key":
                result.pop("risks")
            elif self.mode == "missing-criterion":
                result["technical_evidence"] = result["technical_evidence"][:-1]
            elif self.mode == "extra-key":
                result["unexpected"] = True
            text = json.dumps(result)
        return {
            "text": text,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 1000.0,
            "cost": 0.0,
            "confidence": 1.0,
            "total_duration_ns": 1_000_000_000,
            "load_duration_ns": 100_000_000,
            "prompt_eval_count": 100,
            "prompt_eval_duration_ns": 200_000_000,
            "eval_count": 50,
            "eval_duration_ns": 500_000_000,
            "done": True,
            "done_reason": "stop",
        }


class FakeResourceMonitor:
    def __init__(self):
        self.phase = "initializing"
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def set_phase(self, phase):
        self.phase = phase

    def stop(self):
        self.stopped = True

    def samples(self):
        return [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "monotonic_seconds": 1.0,
                "phase": "Architecture",
                "cpu_usage_usec": 100,
                "cpu_percent": 0.0,
                "memory_current_bytes": 1024,
                "memory_peak_bytes": 2048,
                "host_memory_available_bytes": 40 * 1024**3,
                "host_load_1m": 1.0,
            },
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "monotonic_seconds": 2.0,
                "phase": self.phase,
                "cpu_usage_usec": 2_000_100,
                "cpu_percent": 200.0,
                "memory_current_bytes": 4096,
                "memory_peak_bytes": 8192,
                "host_memory_available_bytes": 39 * 1024**3,
                "host_load_1m": 2.0,
            },
        ]


def offline_execution(tmp_path):
    return OfflineMockExecutor().execute(
        execution_id="offline",
        project="AIONEX-AIOS",
        objective="Compare isolated local execution",
        output_root=tmp_path / "offline-root",
    )


def make_sandbox(transport=None, monitor=None, **kwargs):
    return LocalModelSandbox(
        transport or FakeRawTransport(),
        model="qwen3:8b",
        image_digest=IMAGE_DIGEST,
        container_limits={"cpus": 4, "memory": "12GiB", "context": 4096},
        resource_monitor=monitor or FakeResourceMonitor(),
        **kwargs,
    )


def execute_success(tmp_path, *, transport=None, monitor=None):
    offline = offline_execution(tmp_path)
    sandbox = make_sandbox(transport=transport, monitor=monitor)
    result = sandbox.execute(
        execution_id="local",
        project="AIONEX-AIOS",
        objective="Compare isolated local execution",
        output_root=tmp_path / "local-root",
        offline_result=offline,
        offline_run_metrics={"total_duration": 0.01},
    )
    return sandbox, result, offline


def test_loopback_transport_is_allowed_and_normalizes_ollama_response():
    captured = {}

    def post_json(url, payload, timeout):
        captured.update({"url": url, "payload": payload, "timeout": timeout})
        return {
            "model": "qwen3:8b",
            "message": {"role": "assistant", "content": "{}"},
            "done": True,
            "done_reason": "stop",
            "total_duration": 2_000_000_000,
            "load_duration": 100_000_000,
            "prompt_eval_count": 10,
            "prompt_eval_duration": 200_000_000,
            "eval_count": 5,
            "eval_duration": 500_000_000,
        }

    transport = OllamaLocalHTTPTransport(post_json=post_json, timeout_seconds=12)
    result = asyncio.run(
        transport(
            {
                "model": "qwen3:8b",
                "messages": [{"role": "user", "content": "x"}],
                "metadata": {
                    "format": {"type": "object"},
                    "think": False,
                    "keep_alive": 0,
                    "options": {"seed": 22, "num_ctx": 4096},
                },
                "options": {"temperature": 0.0, "num_predict": 100},
            }
        )
    )
    assert captured["url"] == ALLOWED_OLLAMA_ENDPOINT + "/api/chat"
    assert captured["payload"]["options"]["seed"] == 22
    assert captured["payload"]["options"]["num_ctx"] == 4096
    assert captured["payload"]["format"] == {"type": "object"}
    assert captured["payload"]["think"] is False
    assert result["text"] == "{}"
    assert result["eval_count"] == 5
    assert result["total_duration_ns"] == 2_000_000_000


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://localhost:11435",
        "http://127.0.0.1:11434",
        "https://127.0.0.1:11435",
        "http://127.0.0.1:11435/",
        "http://127.0.0.1:11435?x=1",
        "http://10.0.0.1:11435",
        "http://example.com:11435",
    ),
)
def test_transport_rejects_every_non_exact_endpoint(endpoint):
    with pytest.raises(ValueError, match="only http://127.0.0.1:11435"):
        OllamaLocalHTTPTransport(endpoint)


def test_transport_rejects_incomplete_response():
    def post_json(url, payload, timeout):
        return {"message": {"content": "{}"}, "done": False}

    with pytest.raises(SandboxValidationError, match="incomplete"):
        asyncio.run(OllamaLocalHTTPTransport(post_json=post_json)({"model": "qwen3:8b", "messages": []}))


def test_image_digest_must_be_exact_official_sha256_pin():
    with pytest.raises(ValueError, match="pin the official Ollama image"):
        LocalModelSandbox(FakeRawTransport(), image_digest="ollama/ollama:latest")


def test_transport_serializes_requests():
    lock = threading.Lock()
    active = 0
    maximum = 0

    def post_json(url, payload, timeout):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"message": {"content": "{}"}, "done": True}

    transport = OllamaLocalHTTPTransport(post_json=post_json)

    async def run():
        payload = {"model": "qwen3:8b", "messages": [], "metadata": {}}
        await asyncio.gather(transport(payload), transport(payload), transport(payload))

    asyncio.run(run())
    assert maximum == 1
    assert transport.maximum_active_requests == 1
    assert transport.request_count == 3


def test_complete_cycle_creates_six_valid_artifacts_and_comparison(tmp_path):
    sandbox, result, _ = execute_success(tmp_path)
    assert isinstance(sandbox.provider, OllamaProvider)
    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.blocking_findings == ()
    assert result.rework_plan == ()
    assert len(result.artifact_paths) == 6
    assert all(path.is_file() for path in result.artifact_paths)
    assert result.manifest_path.is_file()
    assert result.report_path.is_file()
    assert result.comparison_path.is_file()
    assert result.comparison_report_path.is_file()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["departments"] == [
        "Architecture",
        "Backend",
        "Frontend",
        "Security",
        "Quality",
        "DevOps",
    ]
    assert manifest["schema_validation"]["all_valid"] is True
    assert manifest["acceptance_coverage"]["overall"] == 1.0
    assert manifest["model"] == "qwen3:8b"
    assert manifest["image_digest"] == IMAGE_DIGEST
    assert manifest["network_used"] is False
    assert manifest["execution_network_used"] is False
    assert manifest["model_acquisition_network_used"] is True
    assert manifest["provider_keys_used"] is False
    assert manifest["cloud_model_used"] is False
    assert manifest["production_modified"] is False
    assert manifest["prompt_eval_count"] == 600
    assert manifest["eval_count"] == 300
    assert manifest["tokens_per_second"] == 100.0
    assert manifest["peak_cpu_percent"] == 200.0
    assert manifest["peak_memory_bytes"] == 8192

    for record in manifest["artifacts"]:
        path = result.output_directory / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_valid"] is True
        assert payload["acceptance_coverage"] == 1.0
        assert payload["department"] == record["department"]

    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    assert comparison["offline_mock"]["artifact_count"] == 6
    assert comparison["offline_mock"]["quality"]["acceptance_coverage"] == 1.0
    assert comparison["offline_mock"]["quality"]["technical_evidence_density"] == 1.0
    assert comparison["local_model"]["artifact_count"] == 6
    assert comparison["local_model"]["quality"]["technical_evidence_density"] == 1.0
    assert "deterministic" in comparison["quality_method"].lower()


def test_unit_execution_performs_no_network_with_fake_transport(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", blocked)
    _, result, _ = execute_success(tmp_path)
    assert result.manifest_path.exists()


@pytest.mark.parametrize("mode", ("invalid-json", "missing-key", "missing-criterion", "extra-key"))
def test_invalid_model_outputs_are_rejected_and_staging_is_cleaned(tmp_path, mode):
    offline = offline_execution(tmp_path)
    sandbox = make_sandbox(FakeRawTransport(mode=mode))
    root = tmp_path / "local-root"
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        sandbox.execute(
            execution_id="failed",
            project="p",
            objective="o",
            output_root=root,
            offline_result=offline,
        )
    assert not (root / "failed").exists()
    assert not (root / ".staging-failed").exists()
    assert list(root.iterdir()) == []


def test_parser_strictly_rejects_incomplete_schema():
    payload = valid_department_payload("Backend", ("one", "two", "three"))
    payload.pop("summary")
    with pytest.raises(SandboxValidationError, match="keys mismatch"):
        LocalModelSandbox._parse_and_validate(json.dumps(payload), "Backend", ("one", "two", "three"))


@pytest.mark.parametrize("execution_id", ("../escape", "nested/path", "/absolute", "..", ".", "a\\b"))
def test_path_traversal_is_rejected(tmp_path, execution_id):
    offline = offline_execution(tmp_path)
    root = tmp_path / "local-root"
    with pytest.raises(ValueError):
        make_sandbox().execute(
            execution_id=execution_id,
            project="p",
            objective="o",
            output_root=root,
            offline_result=offline,
        )
    assert not any(root.iterdir()) if root.exists() else True


def test_output_root_must_be_absolute(tmp_path, monkeypatch):
    offline = offline_execution(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        make_sandbox().execute(
            execution_id="local",
            project="p",
            objective="o",
            output_root=Path("relative"),
            offline_result=offline,
        )
    assert not (tmp_path / "relative").exists()


def test_existing_execution_is_never_replaced(tmp_path):
    sandbox, result, offline = execute_success(tmp_path)
    before = {
        path.relative_to(result.output_directory): path.read_bytes()
        for path in result.output_directory.rglob("*")
        if path.is_file()
    }
    with pytest.raises(FileExistsError):
        sandbox.execute(
            execution_id="local",
            project="second",
            objective="second",
            output_root=tmp_path / "local-root",
            offline_result=offline,
        )
    after = {
        path.relative_to(result.output_directory): path.read_bytes()
        for path in result.output_directory.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_staging_is_cleaned_when_atomic_write_fails(tmp_path, monkeypatch):
    offline = offline_execution(tmp_path)
    sandbox = make_sandbox()
    original = sandbox._atomic_write_text
    calls = 0

    def fail(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated atomic failure")
        return original(path, content)

    monkeypatch.setattr(sandbox, "_atomic_write_text", fail)
    root = tmp_path / "local-root"
    with pytest.raises(RuntimeError, match="simulated atomic failure"):
        sandbox.execute(
            execution_id="atomic-failure",
            project="p",
            objective="o",
            output_root=root,
            offline_result=offline,
        )
    assert not (root / "atomic-failure").exists()
    assert not (root / ".staging-atomic-failure").exists()
    assert list(root.iterdir()) == []


def test_no_file_outside_output_root_is_modified(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    before = sentinel.stat().st_mtime_ns, sentinel.read_bytes()
    _, result, _ = execute_success(tmp_path)
    after = sentinel.stat().st_mtime_ns, sentinel.read_bytes()
    assert after == before
    assert all(result.output_directory in path.parents for path in result.artifact_paths)


def test_provider_environment_keys_are_not_read(tmp_path, monkeypatch):
    for name in PROVIDER_KEY_NAMES:
        monkeypatch.setenv(name, "must-not-be-read")

    def forbidden_getenv(*args, **kwargs):
        raise AssertionError("provider environment key lookup attempted")

    monkeypatch.setattr(os, "getenv", forbidden_getenv)
    _, result, _ = execute_success(tmp_path)
    assert result.approved is True


def test_false_model_evidence_flows_to_engineering_review_without_fabrication(tmp_path):
    transport = FakeRawTransport(tests_passed=False, security_reviewed=False)
    _, result, _ = execute_success(tmp_path, transport=transport)
    assert result.approved is False
    assert result.readiness_score < 1.0
    assert any("tests have not passed" in item for item in result.blocking_findings)
    assert result.rework_plan


def test_executor_source_contains_no_shell_or_subprocess_calls():
    source = inspect.getsource(sandbox_module)
    forbidden = ("import subprocess", "from subprocess", "os.system(", "Popen(", "shell=True")
    assert not any(item in source for item in forbidden)


def test_cgroup_resource_monitor_reads_only_supplied_cgroup(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "cpu.stat").write_text("usage_usec 100\nuser_usec 60\nsystem_usec 40\n", encoding="utf-8")
    (cgroup / "memory.current").write_text("4096\n", encoding="utf-8")
    (cgroup / "memory.peak").write_text("8192\n", encoding="utf-8")
    monitor = CgroupResourceMonitor(cgroup, interval_seconds=0.1)
    monitor.start()
    monitor.set_phase("Backend")
    time.sleep(0.12)
    (cgroup / "cpu.stat").write_text("usage_usec 200100\nuser_usec 160000\nsystem_usec 40100\n", encoding="utf-8")
    monitor.stop()
    samples = monitor.samples()
    assert samples
    assert samples[-1]["memory_current_bytes"] == 4096
    assert any(item["phase"] == "Backend" for item in samples)
    assert max(item["cpu_percent"] for item in samples) >= 0.0
