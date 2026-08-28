from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .organization import EngineeringOrganization
from .providers import DataSensitivity, ModelCapability, ModelRequest
from .providers.adapters import OllamaProvider


ALLOWED_OLLAMA_ENDPOINT = "http://127.0.0.1:11435"
DEFAULT_MODEL = "qwen3:8b"
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IMAGE_DIGEST = re.compile(r"^ollama/ollama@sha256:[0-9a-f]{64}$")
_DEPARTMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Architecture": ("architecture", "dependency", "interface", "failure", "boundary"),
    "Backend": ("api", "database", "transaction", "interface", "latency"),
    "Frontend": ("accessibility", "render", "interaction", "user", "browser"),
    "Security": ("threat", "control", "vulnerability", "authorization", "attack"),
    "Quality": ("test", "regression", "coverage", "assertion", "evidence"),
    "DevOps": ("deployment", "rollback", "observability", "container", "monitoring"),
}


class SandboxValidationError(ValueError):
    """Raised when a local-model response violates the sandbox contract."""


class ResourceMonitor(Protocol):
    def start(self) -> None: ...

    def set_phase(self, phase: str) -> None: ...

    def stop(self) -> None: ...

    def samples(self) -> list[dict[str, Any]]: ...


class NullResourceMonitor:
    def start(self) -> None:
        return None

    def set_phase(self, phase: str) -> None:
        return None

    def stop(self) -> None:
        return None

    def samples(self) -> list[dict[str, Any]]:
        return []


class CgroupResourceMonitor:
    """Sample an already-created cgroup without invoking Docker or shell commands."""

    def __init__(self, cgroup_path: str | Path, *, interval_seconds: float = 1.0) -> None:
        self.cgroup_path = Path(cgroup_path).resolve(strict=True)
        if not self.cgroup_path.is_dir():
            raise NotADirectoryError(str(self.cgroup_path))
        self.interval_seconds = max(0.1, float(interval_seconds))
        self._phase = "initializing"
        self._phase_lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._samples_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("resource monitor already started")
        self._sample()
        self._thread = threading.Thread(target=self._run, name="aios-phase22b-resource-monitor", daemon=True)
        self._thread.start()

    def set_phase(self, phase: str) -> None:
        with self._phase_lock:
            self._phase = str(phase)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds * 3))
            self._thread = None
        self._sample()

    def samples(self) -> list[dict[str, Any]]:
        with self._samples_lock:
            raw = [dict(item) for item in self._samples]
        previous: dict[str, Any] | None = None
        for item in raw:
            item["cpu_percent"] = 0.0
            if previous is not None:
                elapsed = item["monotonic_seconds"] - previous["monotonic_seconds"]
                usage_delta = item["cpu_usage_usec"] - previous["cpu_usage_usec"]
                if elapsed > 0 and usage_delta >= 0:
                    item["cpu_percent"] = round((usage_delta / 1_000_000) / elapsed * 100, 4)
            previous = item
        return raw

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def _sample(self) -> None:
        cpu = self._read_cpu_stat()
        with self._phase_lock:
            phase = self._phase
        sample = {
            "timestamp": datetime.now(UTC).isoformat(),
            "monotonic_seconds": time.monotonic(),
            "phase": phase,
            "cpu_usage_usec": cpu.get("usage_usec", 0),
            "cpu_user_usec": cpu.get("user_usec", 0),
            "cpu_system_usec": cpu.get("system_usec", 0),
            "memory_current_bytes": self._read_int("memory.current"),
            "memory_peak_bytes": self._read_int("memory.peak"),
            "host_memory_available_bytes": self._host_memory_available(),
            "host_load_1m": self._host_load_1m(),
        }
        with self._samples_lock:
            self._samples.append(sample)

    def _read_cpu_stat(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for line in (self.cgroup_path / "cpu.stat").read_text(encoding="utf-8").splitlines():
            key, value = line.split(maxsplit=1)
            if value.isdigit():
                result[key] = int(value)
        return result

    def _read_int(self, name: str) -> int:
        path = self.cgroup_path / name
        if not path.exists():
            return 0
        value = path.read_text(encoding="utf-8").strip()
        return int(value) if value.isdigit() else 0

    @staticmethod
    def _host_memory_available() -> int:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
        return 0

    @staticmethod
    def _host_load_1m() -> float:
        return float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])


PostJSON = Callable[[str, dict[str, Any], float], dict[str, Any]]


class OllamaLocalHTTPTransport:
    """Strict loopback-only raw transport for the existing OllamaProvider."""

    def __init__(
        self,
        endpoint: str = ALLOWED_OLLAMA_ENDPOINT,
        *,
        timeout_seconds: float = 900.0,
        post_json: PostJSON | None = None,
    ) -> None:
        self.endpoint = self._validate_endpoint(endpoint)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._post_json = post_json or self._default_post_json
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self.request_count = 0
        self.active_requests = 0
        self.maximum_active_requests = 0

    async def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self.active_requests += 1
            self.maximum_active_requests = max(self.maximum_active_requests, self.active_requests)
            self.request_count += 1
            try:
                request_payload = self._request_payload(payload)
                raw = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._post_json_serialized,
                        f"{self.endpoint}/api/chat",
                        request_payload,
                        self.timeout_seconds,
                    ),
                    timeout=self.timeout_seconds + 2.0,
                )
                return self._normalize_response(raw)
            finally:
                self.active_requests -= 1

    def _post_json_serialized(
        self, url: str, payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        # asyncio cancellation cannot terminate a running worker thread. The synchronous
        # lock guarantees that a timed-out request and a retry can never overlap on Ollama.
        with self._sync_lock:
            return self._post_json(url, payload, timeout_seconds)

    @staticmethod
    def _validate_endpoint(endpoint: str) -> str:
        parts = urlsplit(endpoint)
        if (
            endpoint != ALLOWED_OLLAMA_ENDPOINT
            or parts.scheme != "http"
            or parts.hostname != "127.0.0.1"
            or parts.port != 11435
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("",)
            or parts.query
            or parts.fragment
        ):
            raise ValueError(f"only {ALLOWED_OLLAMA_ENDPOINT} is permitted")
        return endpoint

    @staticmethod
    def _request_payload(payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        metadata = request_payload.pop("metadata", {})
        if not isinstance(metadata, Mapping):
            raise SandboxValidationError("request metadata must be a mapping")
        options = dict(request_payload.get("options") or {})
        extra_options = metadata.get("options") or {}
        if not isinstance(extra_options, Mapping):
            raise SandboxValidationError("Ollama options must be a mapping")
        options.update(extra_options)
        request_payload["options"] = options
        request_payload["format"] = metadata.get("format", "json")
        request_payload["think"] = bool(metadata.get("think", False))
        request_payload["keep_alive"] = metadata.get("keep_alive", 0)
        return request_payload

    @staticmethod
    def _normalize_response(raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise SandboxValidationError("Ollama response must be an object")
        if raw.get("done") is not True:
            raise SandboxValidationError("Ollama response is incomplete")
        message = raw.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise SandboxValidationError("Ollama response is missing message.content")
        total_duration = int(raw.get("total_duration", 0) or 0)
        prompt_eval_count = int(raw.get("prompt_eval_count", 0) or 0)
        eval_count = int(raw.get("eval_count", 0) or 0)
        return {
            "text": message["content"],
            "usage": {
                "input_tokens": prompt_eval_count,
                "output_tokens": eval_count,
            },
            "latency_ms": total_duration / 1_000_000,
            "cost": 0.0,
            "confidence": 1.0 if raw.get("done", False) else 0.0,
            "total_duration_ns": total_duration,
            "load_duration_ns": int(raw.get("load_duration", 0) or 0),
            "prompt_eval_count": prompt_eval_count,
            "prompt_eval_duration_ns": int(raw.get("prompt_eval_duration", 0) or 0),
            "eval_count": eval_count,
            "eval_duration_ns": int(raw.get("eval_duration", 0) or 0),
            "done": bool(raw.get("done", False)),
            "done_reason": str(raw.get("done_reason", "")),
            "created_at": raw.get("created_at"),
            "model": raw.get("model"),
        }

    @staticmethod
    def _default_post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ConnectionError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ConnectionError(f"Ollama connection failed: {exc.reason}") from exc
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SandboxValidationError("Ollama returned invalid response JSON") from exc
        if not isinstance(decoded, dict):
            raise SandboxValidationError("Ollama HTTP response must be an object")
        return decoded


@dataclass(frozen=True, slots=True)
class LocalModelExecutionResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    comparison_path: Path
    comparison_report_path: Path
    artifact_paths: tuple[Path, ...]
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    total_duration: float
    prompt_eval_count: int
    eval_count: int
    tokens_per_second: float
    cpu_samples: tuple[dict[str, Any], ...]
    memory_samples: tuple[dict[str, Any], ...]


class LocalModelSandbox:
    """Run the six-department organization through one isolated local Ollama model."""

    def __init__(
        self,
        raw_transport: Callable[[dict[str, Any]], Any],
        *,
        model: str = DEFAULT_MODEL,
        image_digest: str,
        organization: EngineeringOrganization | None = None,
        container_limits: Mapping[str, Any] | None = None,
        department_timeout_seconds: float = 900.0,
        max_attempts: int = 2,
        resource_monitor: ResourceMonitor | None = None,
    ) -> None:
        if not model or "/" in model or "\\" in model:
            raise ValueError("model name is invalid")
        if not _IMAGE_DIGEST.fullmatch(image_digest):
            raise ValueError("image_digest must pin the official Ollama image by SHA-256")
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be one or two")
        self.model = model
        self.image_digest = image_digest
        self.organization = organization or EngineeringOrganization()
        self.container_limits = dict(container_limits or {})
        self.department_timeout_seconds = max(1.0, float(department_timeout_seconds))
        self.max_attempts = max_attempts
        self.resource_monitor = resource_monitor or NullResourceMonitor()
        capability = ModelCapability(
            provider="ollama",
            model=model,
            tasks=frozenset({"coding", "reasoning", "private"}),
            languages=frozenset({"ar", "en", "multilingual"}),
            local=True,
            max_context_tokens=4096,
            quality_score=0.75,
            latency_score=0.45,
            privacy_score=1.0,
        )
        self.provider = OllamaProvider((capability,), raw_transport=raw_transport)

    def execute(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
    ) -> LocalModelExecutionResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._execute_async(
                    execution_id=execution_id,
                    project=project,
                    objective=objective,
                    output_root=output_root,
                )
            )
        raise RuntimeError("LocalModelSandbox.execute cannot run inside an active event loop")

    async def _execute_async(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
    ) -> LocalModelExecutionResult:
        root = self._prepare_root(output_root)
        safe_id = self._validate_execution_id(execution_id)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")
        if destination.exists():
            raise FileExistsError(f"local model execution already exists: {safe_id}")
        if staging.exists():
            raise FileExistsError(f"local model staging already exists: {safe_id}")
        staging.mkdir(mode=0o700)
        monitor_started = False
        started = time.monotonic()
        try:
            artifacts_dir = staging / "artifacts"
            artifacts_dir.mkdir(mode=0o700)
            blueprint = self.organization.plan(project, objective)
            artifact_records: list[dict[str, Any]] = []
            artifact_payloads: list[dict[str, Any]] = []

            self.resource_monitor.start()
            monitor_started = True
            for deliverable in blueprint.deliverables:
                self.resource_monitor.set_phase(deliverable.department)
                generated, metrics, attempt_errors, attempts = await self._generate_department(
                    project=project,
                    objective=objective,
                    department=deliverable.department,
                    acceptance_criteria=deliverable.acceptance_criteria,
                )
                wrapper = {
                    "schema_version": 1,
                    "execution_id": safe_id,
                    "project": project,
                    "objective": objective,
                    "provider": "ollama",
                    "model": self.model,
                    "department": deliverable.department,
                    "model_output": generated,
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": attempts,
                    "attempt_errors": attempt_errors,
                    "metrics": metrics,
                }
                filename = f"{deliverable.department.lower()}.json"
                artifact_path = artifacts_dir / filename
                self._atomic_write_text(artifact_path, self._canonical_json(wrapper))
                digest = self._sha256(artifact_path)
                artifact_records.append(
                    {
                        "department": deliverable.department,
                        "path": f"artifacts/{filename}",
                        "sha256": digest,
                        "schema_valid": True,
                        "acceptance_coverage": 1.0,
                        "attempts": attempts,
                        "errors": attempt_errors,
                        "metrics": metrics,
                    }
                )
                artifact_payloads.append(wrapper)
                passed_criteria = [entry["criterion"] for entry in generated["technical_evidence"]]
                deliverable.evidence.update(
                    {
                        "passed_criteria": passed_criteria,
                        "tests_passed": generated["tests_passed"],
                        "security_reviewed": generated["security_reviewed"],
                        "artifact": f"artifacts/{filename}",
                        "sha256": digest,
                        "local_model": self.model,
                    }
                )

            self.resource_monitor.set_phase("engineering-review")
            review = self.organization.chief_review(blueprint)
            self.resource_monitor.stop()
            monitor_started = False
            samples = self.resource_monitor.samples()
            wall_duration = time.monotonic() - started
            aggregate = self._aggregate_metrics(artifact_records, wall_duration, samples)
            artifact_hashes = {item["department"]: item["sha256"] for item in artifact_records}
            manifest = {
                "schema_version": 1,
                "execution_id": safe_id,
                "project": project,
                "objective": objective,
                "mode": "local-model-sandbox",
                "model": self.model,
                "image_digest": self.image_digest,
                "endpoint": ALLOWED_OLLAMA_ENDPOINT,
                "container_limits": dict(self.container_limits),
                "model_acquisition_network_used": True,
                "execution_network_used": False,
                "network_used": False,
                "provider_keys_used": False,
                "cloud_model_used": False,
                "production_modified": False,
                "departments": list(blueprint.departments),
                "artifacts": artifact_records,
                "artifact_hashes": artifact_hashes,
                "schema_validation": {
                    "all_valid": all(item["schema_valid"] for item in artifact_records),
                    "departments": {item["department"]: item["schema_valid"] for item in artifact_records},
                },
                "acceptance_coverage": {
                    "overall": round(
                        sum(item["acceptance_coverage"] for item in artifact_records) / len(artifact_records), 4
                    ),
                    "departments": {
                        item["department"]: item["acceptance_coverage"] for item in artifact_records
                    },
                },
                **aggregate,
                "review": {
                    "approved": review.approved,
                    "readiness_score": review.readiness_score,
                    "blocking_findings": list(review.blocking_findings),
                    "rework_plan": list(review.rework_plan),
                    "rationale": review.rationale,
                    "departments": [
                        {
                            "department": item.department,
                            "approved": item.approved,
                            "score": item.score,
                            "findings": list(item.findings),
                            "required_actions": list(item.required_actions),
                            "manager_id": item.manager_id,
                        }
                        for item in review.department_decisions
                    ],
                },
                "proof": {
                    "model_acquisition_network_used": True,
                    "execution_network_used": False,
                    "network_used": False,
                    "provider_keys_used": False,
                    "cloud_model_used": False,
                    "production_modified": False,
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write_text(manifest_path, self._canonical_json(manifest))
            report_path = staging / "REPORT.md"
            self._atomic_write_text(report_path, self._report(manifest))

            comparison = self._execution_assessment(
                local_manifest=manifest,
                local_artifacts=artifact_payloads,
            )
            comparison_path = staging / "comparison.json"
            self._atomic_write_text(comparison_path, self._canonical_json(comparison))
            comparison_report_path = staging / "COMPARISON_REPORT.md"
            self._atomic_write_text(comparison_report_path, self._comparison_report(comparison))

            os.replace(staging, destination)
            cpu_samples = tuple(
                {
                    "timestamp": item.get("timestamp"),
                    "phase": item.get("phase"),
                    "cpu_usage_usec": item.get("cpu_usage_usec", 0),
                    "cpu_percent": item.get("cpu_percent", 0.0),
                    "host_load_1m": item.get("host_load_1m", 0.0),
                }
                for item in samples
            )
            memory_samples = tuple(
                {
                    "timestamp": item.get("timestamp"),
                    "phase": item.get("phase"),
                    "memory_current_bytes": item.get("memory_current_bytes", 0),
                    "memory_peak_bytes": item.get("memory_peak_bytes", 0),
                    "host_memory_available_bytes": item.get("host_memory_available_bytes", 0),
                }
                for item in samples
            )
            return LocalModelExecutionResult(
                execution_id=safe_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                comparison_path=destination / "comparison.json",
                comparison_report_path=destination / "COMPARISON_REPORT.md",
                artifact_paths=tuple(destination / item["path"] for item in artifact_records),
                approved=review.approved,
                readiness_score=review.readiness_score,
                blocking_findings=review.blocking_findings,
                rework_plan=review.rework_plan,
                total_duration=aggregate["total_duration"],
                prompt_eval_count=aggregate["prompt_eval_count"],
                eval_count=aggregate["eval_count"],
                tokens_per_second=aggregate["tokens_per_second"],
                cpu_samples=cpu_samples,
                memory_samples=memory_samples,
            )
        except BaseException:
            if monitor_started:
                self.resource_monitor.stop()
            shutil.rmtree(staging, ignore_errors=True)
            raise

    async def _generate_department(
        self,
        *,
        project: str,
        objective: str,
        department: str,
        acceptance_criteria: tuple[str, ...],
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], int]:
        errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            prompt = self._prompt(project, objective, department, acceptance_criteria, errors[-1] if errors else None)
            request = ModelRequest(
                task="coding",
                prompt=prompt,
                system_prompt=(
                    "You are an isolated AIOS engineering department. Use no tools, network, secrets, "
                    "cloud services, or unstated execution evidence. Return only the requested JSON object."
                ),
                language="en",
                sensitivity=DataSensitivity.RESTRICTED,
                max_tokens=1536,
                temperature=0.0,
                require_local=True,
                metadata={
                    "department": department,
                    "acceptance_criteria": list(acceptance_criteria),
                    "format": self._json_schema(department, acceptance_criteria),
                    "think": False,
                    "keep_alive": 0,
                    "options": {"seed": 22, "num_ctx": 4096, "temperature": 0.0},
                },
            )
            wall_started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.provider.generate(request, self.model), timeout=self.department_timeout_seconds
                )
                generated = self._parse_and_validate(response.text, department, acceptance_criteria)
                metrics = self._response_metrics(response.metadata, time.monotonic() - wall_started)
                return generated, metrics, errors, attempt
            except (TimeoutError, SandboxValidationError, ConnectionError, OSError, RuntimeError, ValueError) as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {str(exc)[:400]}")
                if attempt >= self.max_attempts:
                    raise RuntimeError(
                        f"{department} failed after {self.max_attempts} attempts: {errors[-1]}"
                    ) from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _prompt(
        project: str,
        objective: str,
        department: str,
        criteria: tuple[str, ...],
        previous_error: str | None,
    ) -> str:
        criteria_lines = "\n".join(f"- {item}" for item in criteria)
        correction = f"\nPrevious response error to correct: {previous_error}\n" if previous_error else ""
        return (
            f"Project: {project}\nObjective: {objective}\nDepartment: {department}\n\n"
            "Produce a department-specific engineering artifact as one strict JSON object. "
            "Cover every acceptance criterion exactly once in technical_evidence, using the criterion text verbatim. "
            "Give concrete implementation steps, technical evidence, verification methods, and clear risk mitigations. "
            "Do not claim that tests passed or that a security review happened unless the prompt contains explicit "
            "execution evidence; this sandbox provides no such external evidence. Do not add keys outside the schema.\n\n"
            f"Acceptance criteria:\n{criteria_lines}\n{correction}"
        )

    @staticmethod
    def _json_schema(department: str, criteria: tuple[str, ...]) -> dict[str, Any]:
        evidence_item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["criterion", "evidence", "verification"],
            "properties": {
                "criterion": {"type": "string", "enum": list(criteria)},
                "evidence": {"type": "string", "minLength": 1},
                "verification": {"type": "string", "minLength": 1},
            },
        }
        risk_item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["risk", "mitigation"],
            "properties": {
                "risk": {"type": "string", "minLength": 1},
                "mitigation": {"type": "string", "minLength": 1},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "department",
                "summary",
                "implementation_plan",
                "technical_evidence",
                "risks",
                "tests_passed",
                "security_reviewed",
            ],
            "properties": {
                "schema_version": {"type": "integer", "const": 1},
                "department": {"type": "string", "const": department},
                "summary": {"type": "string", "minLength": 1},
                "implementation_plan": {
                    "type": "array",
                    "minItems": 3,
                    "items": {"type": "string", "minLength": 1},
                },
                "technical_evidence": {
                    "type": "array",
                    "minItems": len(criteria),
                    "maxItems": len(criteria),
                    "items": evidence_item,
                },
                "risks": {"type": "array", "minItems": 1, "items": risk_item},
                "tests_passed": {"type": "boolean"},
                "security_reviewed": {"type": "boolean"},
            },
        }

    @classmethod
    def _parse_and_validate(
        cls, text: str, department: str, criteria: tuple[str, ...]
    ) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SandboxValidationError("model output is not strict JSON") from exc
        if not isinstance(payload, dict):
            raise SandboxValidationError("model output must be a JSON object")
        cls._exact_keys(
            payload,
            {
                "schema_version",
                "department",
                "summary",
                "implementation_plan",
                "technical_evidence",
                "risks",
                "tests_passed",
                "security_reviewed",
            },
            "model output",
        )
        if payload["schema_version"] != 1:
            raise SandboxValidationError("schema_version must equal 1")
        if payload["department"] != department:
            raise SandboxValidationError("department does not match the requested department")
        if not cls._nonempty(payload["summary"]):
            raise SandboxValidationError("summary must be non-empty")
        plan = payload["implementation_plan"]
        if not isinstance(plan, list) or len(plan) < 3 or not all(cls._nonempty(item) for item in plan):
            raise SandboxValidationError("implementation_plan requires at least three non-empty strings")
        evidence = payload["technical_evidence"]
        if not isinstance(evidence, list) or len(evidence) != len(criteria):
            raise SandboxValidationError("technical_evidence must have one item per acceptance criterion")
        seen: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                raise SandboxValidationError("technical_evidence entries must be objects")
            cls._exact_keys(item, {"criterion", "evidence", "verification"}, "technical_evidence entry")
            if item["criterion"] not in criteria:
                raise SandboxValidationError("technical_evidence contains an unknown criterion")
            if item["criterion"] in seen:
                raise SandboxValidationError("technical_evidence contains a duplicate criterion")
            if not cls._nonempty(item["evidence"]) or not cls._nonempty(item["verification"]):
                raise SandboxValidationError("technical evidence and verification must be non-empty")
            seen.append(item["criterion"])
        if set(seen) != set(criteria):
            raise SandboxValidationError("not every acceptance criterion is covered")
        risks = payload["risks"]
        if not isinstance(risks, list) or not risks:
            raise SandboxValidationError("risks must contain at least one item")
        for item in risks:
            if not isinstance(item, dict):
                raise SandboxValidationError("risk entries must be objects")
            cls._exact_keys(item, {"risk", "mitigation"}, "risk entry")
            if not cls._nonempty(item["risk"]) or not cls._nonempty(item["mitigation"]):
                raise SandboxValidationError("risk and mitigation must be non-empty")
        if type(payload["tests_passed"]) is not bool:
            raise SandboxValidationError("tests_passed must be boolean")
        if type(payload["security_reviewed"]) is not bool:
            raise SandboxValidationError("security_reviewed must be boolean")
        return payload

    @staticmethod
    def _exact_keys(payload: dict[str, Any], expected: set[str], label: str) -> None:
        keys = set(payload)
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise SandboxValidationError(f"{label} keys mismatch; missing={missing}, extra={extra}")

    @staticmethod
    def _nonempty(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _response_metrics(metadata: Mapping[str, Any], wall_duration: float) -> dict[str, Any]:
        total_ns = int(metadata.get("total_duration_ns", 0) or 0)
        load_ns = int(metadata.get("load_duration_ns", 0) or 0)
        prompt_ns = int(metadata.get("prompt_eval_duration_ns", 0) or 0)
        eval_ns = int(metadata.get("eval_duration_ns", 0) or 0)
        eval_count = int(metadata.get("eval_count", 0) or 0)
        return {
            "wall_duration_seconds": round(wall_duration, 6),
            "total_duration": round(total_ns / 1_000_000_000, 6),
            "load_duration": round(load_ns / 1_000_000_000, 6),
            "prompt_eval_count": int(metadata.get("prompt_eval_count", 0) or 0),
            "prompt_eval_duration": round(prompt_ns / 1_000_000_000, 6),
            "eval_count": eval_count,
            "eval_duration": round(eval_ns / 1_000_000_000, 6),
            "tokens_per_second": round(eval_count / (eval_ns / 1_000_000_000), 4) if eval_ns else 0.0,
            "done": bool(metadata.get("done", False)),
            "done_reason": str(metadata.get("done_reason", "")),
        }

    @staticmethod
    def _aggregate_metrics(
        artifact_records: list[dict[str, Any]], wall_duration: float, samples: list[dict[str, Any]]
    ) -> dict[str, Any]:
        metrics = [item["metrics"] for item in artifact_records]
        prompt_eval_count = sum(int(item["prompt_eval_count"]) for item in metrics)
        eval_count = sum(int(item["eval_count"]) for item in metrics)
        eval_duration = sum(float(item["eval_duration"]) for item in metrics)
        cpu_samples = [
            {
                "timestamp": item.get("timestamp"),
                "phase": item.get("phase"),
                "cpu_usage_usec": item.get("cpu_usage_usec", 0),
                "cpu_percent": item.get("cpu_percent", 0.0),
                "host_load_1m": item.get("host_load_1m", 0.0),
            }
            for item in samples
        ]
        memory_samples = [
            {
                "timestamp": item.get("timestamp"),
                "phase": item.get("phase"),
                "memory_current_bytes": item.get("memory_current_bytes", 0),
                "memory_peak_bytes": item.get("memory_peak_bytes", 0),
                "host_memory_available_bytes": item.get("host_memory_available_bytes", 0),
            }
            for item in samples
        ]
        return {
            "total_duration": round(wall_duration, 6),
            "load_duration": round(sum(float(item["load_duration"]) for item in metrics), 6),
            "prompt_eval_count": prompt_eval_count,
            "prompt_eval_duration": round(sum(float(item["prompt_eval_duration"]) for item in metrics), 6),
            "eval_count": eval_count,
            "eval_duration": round(eval_duration, 6),
            "tokens_per_second": round(eval_count / eval_duration, 4) if eval_duration else 0.0,
            "cpu_samples": cpu_samples,
            "memory_samples": memory_samples,
            "peak_cpu_percent": max((float(item.get("cpu_percent", 0.0)) for item in cpu_samples), default=0.0),
            "peak_memory_bytes": max(
                (int(item.get("memory_peak_bytes", 0) or item.get("memory_current_bytes", 0)) for item in memory_samples),
                default=0,
            ),
        }

    @classmethod
    def _execution_assessment(
        cls,
        *,
        local_manifest: dict[str, Any],
        local_artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        quality = cls._quality_metrics(local_artifacts, local=True)
        local_summary = {
            "provider": "ollama",
            "model": local_manifest["model"],
            "artifact_count": len(local_artifacts),
            "valid_json": local_manifest["schema_validation"]["all_valid"],
            "acceptance_coverage": local_manifest["acceptance_coverage"]["overall"],
            "approved": local_manifest["review"]["approved"],
            "readiness_score": local_manifest["review"]["readiness_score"],
            "blocking_findings": local_manifest["review"]["blocking_findings"],
            "rework_plan": local_manifest["review"]["rework_plan"],
            "total_duration": local_manifest["total_duration"],
            "prompt_eval_count": local_manifest["prompt_eval_count"],
            "eval_count": local_manifest["eval_count"],
            "tokens_per_second": local_manifest["tokens_per_second"],
            "peak_cpu_percent": local_manifest["peak_cpu_percent"],
            "peak_memory_bytes": local_manifest["peak_memory_bytes"],
            "errors": [error for item in local_manifest["artifacts"] for error in item["errors"]],
            "quality": quality,
            "truthful_evidence": "real local Qwen execution; no synthetic baseline",
        }
        return {
            "schema_version": 2,
            "assessment_mode": "real-local-execution",
            "project": local_manifest["project"],
            "objective": local_manifest["objective"],
            "local_model": local_summary,
            "quality_method": (
                "Deterministic structural heuristic over real local execution evidence only: schema validity, "
                "acceptance coverage, department specialization, actionable steps, risk/mitigation clarity, "
                "technical evidence density, and pairwise repetition."
            ),
        }

    @classmethod
    def _quality_metrics(cls, artifacts: list[dict[str, Any]], *, local: bool) -> dict[str, Any]:
        specialization_hits = 0
        actionable = 0
        actionable_total = 0
        clear_risks = 0
        risk_total = 0
        evidence_count = 0
        expected_evidence = 0
        texts: list[set[str]] = []
        for wrapper in artifacts:
            payload = wrapper.get("model_output", {}) if local else wrapper
            department = str(wrapper.get("department") or payload.get("department") or "")
            text = json.dumps(payload, ensure_ascii=False).lower()
            words = set(re.findall(r"[a-z0-9_]{3,}", text))
            texts.append(words)
            if any(keyword in text for keyword in _DEPARTMENT_KEYWORDS.get(department, ())):
                specialization_hits += 1
            plan = payload.get("implementation_plan", [])
            if isinstance(plan, list):
                actionable_total += len(plan)
                actionable += sum(isinstance(item, str) and len(item.strip()) >= 20 for item in plan)
            risks = payload.get("risks", [])
            if isinstance(risks, list):
                risk_total += len(risks)
                clear_risks += sum(
                    isinstance(item, dict)
                    and len(str(item.get("risk", "")).strip()) >= 15
                    and len(str(item.get("mitigation", "")).strip()) >= 15
                    for item in risks
                )
            if local:
                evidence = payload.get("technical_evidence", [])
                if isinstance(evidence, list):
                    evidence_count += len(evidence)
                    expected_evidence += len(evidence)
            else:
                criteria = payload.get("acceptance_criteria", [])
                if isinstance(criteria, list):
                    expected_evidence += len(criteria)
                passed = payload.get("evidence", {}).get("passed_criteria", [])
                evidence_count += len(passed) if isinstance(passed, list) else 0
        pairwise: list[float] = []
        for index, left in enumerate(texts):
            for right in texts[index + 1 :]:
                union = left | right
                pairwise.append(len(left & right) / len(union) if union else 0.0)
        count = max(1, len(artifacts))
        specialization = specialization_hits / count
        actionability = actionable / actionable_total if actionable_total else 0.0
        risk_clarity = clear_risks / risk_total if risk_total else 0.0
        evidence_density = evidence_count / expected_evidence if expected_evidence else 0.0
        repetition = sum(pairwise) / len(pairwise) if pairwise else 0.0
        schema_validity = 1.0
        acceptance_coverage = evidence_density
        base = (
            schema_validity
            + acceptance_coverage
            + specialization
            + actionability
            + risk_clarity
            + evidence_density
        ) / 6
        quality_score = max(0.0, min(1.0, base * (1 - 0.25 * repetition)))
        return {
            "schema_validity": round(schema_validity, 4),
            "acceptance_coverage": round(acceptance_coverage, 4),
            "department_specialization": round(specialization, 4),
            "actionability": round(actionability, 4),
            "risk_clarity": round(risk_clarity, 4),
            "technical_evidence_density": round(evidence_density, 4),
            "pairwise_repetition": round(repetition, 4),
            "quality_score": round(quality_score, 4),
        }

    @staticmethod
    def _prepare_root(output_root: str | Path) -> Path:
        raw = Path(output_root)
        if not raw.is_absolute():
            raise ValueError("output_root must be an explicit absolute path")
        raw.mkdir(parents=True, exist_ok=True)
        root = raw.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        return root

    @staticmethod
    def _validate_execution_id(execution_id: str) -> str:
        if not _EXECUTION_ID.fullmatch(execution_id) or execution_id in {".", ".."}:
            raise ValueError("execution_id contains unsafe path characters")
        return execution_id

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError("path escapes output_root")
        return resolved

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _report(manifest: dict[str, Any]) -> str:
        review = manifest["review"]
        artifact_lines = "\n".join(
            f"- {item['department']}: `{item['path']}` — SHA-256 `{item['sha256']}` — "
            f"{item['metrics']['tokens_per_second']} tokens/s"
            for item in manifest["artifacts"]
        )
        blockers = review["blocking_findings"] or ["None"]
        rework = review["rework_plan"] or ["None"]
        return (
            "# Phase 22B Local Model Sandbox Report\n\n"
            f"- Execution ID: `{manifest['execution_id']}`\n"
            f"- Model: `{manifest['model']}`\n"
            f"- Image: `{manifest['image_digest']}`\n"
            f"- Approved: `{str(review['approved']).lower()}`\n"
            f"- Readiness score: `{review['readiness_score']}`\n"
            f"- Total duration: `{manifest['total_duration']} seconds`\n"
            f"- Prompt tokens: `{manifest['prompt_eval_count']}`\n"
            f"- Generated tokens: `{manifest['eval_count']}`\n"
            f"- Generation rate: `{manifest['tokens_per_second']} tokens/s`\n"
            f"- Peak CPU: `{manifest['peak_cpu_percent']}%`\n"
            f"- Peak memory: `{manifest['peak_memory_bytes']} bytes`\n"
            "- Model acquisition network used: `true`\n"
            "- Execution network used: `false`\n"
            "- Provider keys used: `false`\n"
            "- Cloud model used: `false`\n"
            "- Production modified: `false`\n\n"
            f"## Artifacts\n\n{artifact_lines}\n\n"
            "## Blocking findings\n\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n\n## Rework plan\n\n"
            + "\n".join(f"- {item}" for item in rework)
            + "\n"
        )

    @staticmethod
    def _comparison_report(comparison: dict[str, Any]) -> str:
        local = comparison["local_model"]
        return (
            "# Phase 22B Real Local Model Assessment\n\n"
            f"- Provider: `{local['provider']}`\n"
            f"- Model: `{local['model']}`\n"
            f"- Artifacts: `{local['artifact_count']}`\n"
            f"- Acceptance coverage: `{local['acceptance_coverage']}`\n"
            f"- Quality heuristic: `{local['quality']['quality_score']}`\n"
            f"- Pairwise repetition: `{local['quality']['pairwise_repetition']}`\n"
            f"- Total duration: `{local['total_duration']} seconds`\n"
            f"- Generated tokens: `{local['eval_count']}`\n"
            f"- Tokens/s: `{local['tokens_per_second']}`\n"
            f"- Readiness score: `{local['readiness_score']}`\n"
            f"- Approved: `{local['approved']}`\n\n"
            f"Method: {comparison['quality_method']}\n"
        )
