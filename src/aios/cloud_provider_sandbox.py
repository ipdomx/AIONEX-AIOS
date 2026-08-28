from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .local_model_sandbox import LocalModelSandbox, SandboxValidationError
from .organization import EngineeringOrganization
from .providers import BudgetAccount, CostGovernor, DataSensitivity, ModelCapability, ModelRequest, ProviderPolicy
from .providers.adapters import OpenAIProvider
from .providers.shared import AsyncRateLimiter, RetryManager, RetryPolicy, TokenCounter


ALLOWED_OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
ALLOWED_OPENAI_MODELS_ENDPOINT = "https://api.openai.com/v1/models"
PHASE22C_SECRET_PATH = Path("/root/.config/aionex/phase22c-openai.env")
DEFAULT_MAXIMUM_REQUESTS = 6
DEFAULT_MAXIMUM_OUTPUT_TOKENS = 1200
MAXIMUM_TRANSPORT_OUTPUT_TOKENS = 3000
DEFAULT_MAXIMUM_BUDGET_USD = 1.0
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAXIMUM_INPUT_TOKENS = 4096
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CloudSandboxValidationError(ValueError):
    """Raised when Phase 22C input or model output violates the sandbox contract."""


class CloudBudgetExceeded(RuntimeError):
    """Raised before a request that cannot fit inside the configured budget."""


class CloudRequestLimitExceeded(RuntimeError):
    """Raised before a request that would exceed the hard request cap."""


class OpenAITransportError(ConnectionError):
    """Sanitized OpenAI transport failure that never includes credentials or response bodies."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str = "",
        error_type: str = "",
        error_param: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type
        self.error_param = error_param


class SecretConfigurationError(RuntimeError):
    """Raised when the external Phase 22C secret file is absent or unsafe."""


@dataclass(frozen=True, slots=True, repr=False)
class Phase22CSecret:
    api_key: str
    model: str

    @property
    def key_last4(self) -> str:
        return self.api_key[-4:] if len(self.api_key) >= 4 else ""

    def __repr__(self) -> str:
        return f"Phase22CSecret(api_key='[REDACTED]', model={self.model!r})"


def load_phase22c_secret(path: str | Path = PHASE22C_SECRET_PATH) -> Phase22CSecret:
    secret_path = Path(path)
    if secret_path != PHASE22C_SECRET_PATH:
        raise SecretConfigurationError(f"secret path must be {PHASE22C_SECRET_PATH}")
    if not secret_path.is_file() or secret_path.is_symlink():
        raise SecretConfigurationError("Phase 22C secret file is missing or is not a regular file")
    file_stat = secret_path.stat()
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise SecretConfigurationError("Phase 22C secret file permissions must be 600")
    if file_stat.st_uid != 0:
        raise SecretConfigurationError("Phase 22C secret file must be owned by root")

    values: dict[str, str] = {}
    for raw_line in secret_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SecretConfigurationError("Phase 22C secret file contains an invalid line")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name in values:
            raise SecretConfigurationError("Phase 22C secret file contains a duplicate variable")
        values[name] = value

    allowed = {"OPENAI_API_KEY", "AIOS_PHASE22C_MODEL"}
    unknown = set(values) - allowed
    if unknown:
        raise SecretConfigurationError("Phase 22C secret file contains unsupported variables")
    api_key = values.get("OPENAI_API_KEY", "")
    model = values.get("AIOS_PHASE22C_MODEL", "")
    if not api_key:
        raise SecretConfigurationError("OPENAI_API_KEY is missing")
    if not model or not _MODEL_ID.fullmatch(model):
        raise SecretConfigurationError("AIOS_PHASE22C_MODEL is missing or invalid")
    return Phase22CSecret(api_key=api_key, model=model)


PostJSON = Callable[[str, dict[str, Any], Mapping[str, str], float], dict[str, Any]]
GetJSON = Callable[[str, Mapping[str, str], float], dict[str, Any]]


class OpenAIOfficialHTTPTransport:
    """Responses API transport restricted to official OpenAI HTTPS endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = ALLOWED_OPENAI_ENDPOINT,
        models_endpoint: str = ALLOWED_OPENAI_MODELS_ENDPOINT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_requests: int = DEFAULT_MAXIMUM_REQUESTS,
        maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
        input_cost_per_million: float,
        output_cost_per_million: float,
        post_json: PostJSON | None = None,
        get_json: GetJSON | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self.endpoint = self._validate_endpoint(endpoint, ALLOWED_OPENAI_ENDPOINT)
        self.models_endpoint = self._validate_endpoint(models_endpoint, ALLOWED_OPENAI_MODELS_ENDPOINT)
        if not 1.0 <= float(timeout_seconds) <= DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be between 1 and 180")
        if not 1 <= int(maximum_requests) <= DEFAULT_MAXIMUM_REQUESTS:
            raise ValueError("maximum_requests must be between 1 and 6")
        if not 1 <= int(maximum_output_tokens) <= MAXIMUM_TRANSPORT_OUTPUT_TOKENS:
            raise ValueError("maximum_output_tokens must be between 1 and 3000")
        if input_cost_per_million < 0 or output_cost_per_million < 0:
            raise ValueError("model prices must be non-negative")
        if input_cost_per_million == 0 and output_cost_per_million == 0:
            raise ValueError("at least one model price must be positive")
        self._api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.maximum_requests = int(maximum_requests)
        self.maximum_output_tokens = int(maximum_output_tokens)
        self.input_cost_per_million = float(input_cost_per_million)
        self.output_cost_per_million = float(output_cost_per_million)
        self._post_json = post_json or self._default_post_json
        self._get_json = get_json or self._default_get_json
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self.request_count = 0
        self.active_requests = 0
        self.maximum_active_requests = 0

    def __repr__(self) -> str:
        return (
            "OpenAIOfficialHTTPTransport(api_key='[REDACTED]', "
            f"endpoint={self.endpoint!r}, maximum_requests={self.maximum_requests}, "
            f"maximum_output_tokens={self.maximum_output_tokens})"
        )

    async def validate_model(self, model: str) -> dict[str, Any]:
        if not _MODEL_ID.fullmatch(model):
            raise ValueError("model ID is invalid")
        url = f"{self.models_endpoint}/{quote(model, safe='')}"
        raw = await asyncio.wait_for(
            asyncio.to_thread(self._get_json_serialized, url, self._headers(), self.timeout_seconds),
            timeout=self.timeout_seconds + 2.0,
        )
        if not isinstance(raw, dict) or raw.get("id") != model:
            raise OpenAITransportError("OpenAI model availability response did not match the requested model")
        return {"id": raw.get("id"), "object": raw.get("object"), "owned_by": raw.get("owned_by")}

    async def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._async_lock:
            if self.request_count >= self.maximum_requests:
                raise CloudRequestLimitExceeded("Phase 22C request limit reached")
            self.request_count += 1
            self.active_requests += 1
            self.maximum_active_requests = max(self.maximum_active_requests, self.active_requests)
            started = time.monotonic()
            try:
                request_payload = self._request_payload(payload)
                raw = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._post_json_serialized,
                        self.endpoint,
                        request_payload,
                        self._headers(),
                        self.timeout_seconds,
                    ),
                    timeout=self.timeout_seconds + 2.0,
                )
                return self._normalize_response(raw, elapsed_seconds=time.monotonic() - started)
            finally:
                self.active_requests -= 1

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_json_serialized(
        self, url: str, payload: dict[str, Any], headers: Mapping[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        with self._sync_lock:
            return self._post_json(url, payload, headers, timeout_seconds)

    def _get_json_serialized(
        self, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        with self._sync_lock:
            return self._get_json(url, headers, timeout_seconds)

    @staticmethod
    def _validate_endpoint(endpoint: str, expected: str) -> str:
        parts = urlsplit(endpoint)
        if (
            endpoint != expected
            or parts.scheme != "https"
            or parts.hostname != "api.openai.com"
            or parts.port not in (None, 443)
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("only the official OpenAI API endpoint is permitted")
        return endpoint

    def _request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("tools"):
            raise CloudSandboxValidationError("tools are forbidden in Phase 22C")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise CloudSandboxValidationError("request metadata must be a mapping")
        response_format = payload.get("response_format")
        if not isinstance(response_format, Mapping):
            raise CloudSandboxValidationError("strict response format is required")
        json_schema = response_format.get("json_schema")
        if response_format.get("type") != "json_schema" or not isinstance(json_schema, Mapping):
            raise CloudSandboxValidationError("strict JSON schema response format is required")
        required_schema_keys = {"name", "strict", "schema"}
        if set(json_schema) != required_schema_keys or json_schema.get("strict") is not True:
            raise CloudSandboxValidationError("strict JSON schema configuration is invalid")

        allowed = {"model", "input", "max_output_tokens", "temperature", "response_format", "metadata", "tools"}
        unexpected = set(payload) - allowed
        if unexpected:
            raise CloudSandboxValidationError("OpenAI request contains unsupported fields")
        if payload.get("temperature") != 0.0:
            raise CloudSandboxValidationError("temperature must equal zero")
        max_output_tokens = int(payload.get("max_output_tokens", 0) or 0)
        if not 1 <= max_output_tokens <= self.maximum_output_tokens:
            raise CloudSandboxValidationError(
                "max_output_tokens exceeds the configured transport limit"
            )

        model = str(payload.get("model") or "")
        request_body: dict[str, Any] = {
            "model": model,
            "input": payload.get("input"),
            "max_output_tokens": max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": json_schema["name"],
                    "strict": True,
                    "schema": json_schema["schema"],
                },
                "verbosity": "low",
            },
        }

        # GPT-5 reasoning models reject the sampling-temperature field.
        # Keep the internal deterministic contract at 0.0, but omit the
        # unsupported outbound field and use the model-supported minimum
        # reasoning effort to reduce latency and token consumption.
        if model == "gpt-5-mini" or model.startswith("gpt-5-mini-"):
            request_body["reasoning"] = {"effort": "minimal"}
        else:
            request_body["temperature"] = 0

        return request_body

    def _normalize_response(self, raw: dict[str, Any], *, elapsed_seconds: float) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise OpenAITransportError("OpenAI response was not an object")
        status = str(raw.get("status", ""))
        if status != "completed":
            reason = ""
            incomplete = raw.get("incomplete_details")
            if isinstance(incomplete, Mapping):
                reason = str(incomplete.get("reason", ""))[:80]
            raise OpenAITransportError(
                "OpenAI response was not completed",
                error_code="response_incomplete",
                error_type="response_status",
                error_param=reason,
            )
        text = self._extract_output_text(raw)
        usage = raw.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise OpenAITransportError("OpenAI response usage was invalid")
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        calculated_cost = (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000
        return {
            "text": text,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            "latency_ms": elapsed_seconds * 1000,
            "cost": calculated_cost,
            "confidence": 1.0,
            "response_id": str(raw.get("id", "")),
            "status": status,
            "actual_model": str(raw.get("model", "")),
            "reported_cost": None,
            "calculated_cost": calculated_cost,
            "cost_basis": "token usage multiplied by operator-verified model rates",
        }

    @staticmethod
    def _extract_output_text(raw: Mapping[str, Any]) -> str:
        direct = raw.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        output = raw.get("output")
        if not isinstance(output, list):
            raise OpenAITransportError("OpenAI response did not contain output text")
        pieces: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    pieces.append(part["text"])
        text = "".join(pieces)
        if not text.strip():
            raise OpenAITransportError("OpenAI response did not contain output text")
        return text

    @classmethod
    def _default_post_json(
        cls, url: str, payload: dict[str, Any], headers: Mapping[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        cls._validate_endpoint(url, ALLOWED_OPENAI_ENDPOINT)
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        return cls._open_json(request, timeout_seconds)

    @classmethod
    def _default_get_json(
        cls, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> dict[str, Any]:
        prefix = f"{ALLOWED_OPENAI_MODELS_ENDPOINT}/"
        if not url.startswith(prefix) or url == prefix:
            raise ValueError("only the official OpenAI models endpoint is permitted")
        suffix = url[len(prefix) :]
        if "/" in suffix or not suffix:
            raise ValueError("OpenAI model URL is invalid")
        request = Request(url, headers=dict(headers), method="GET")
        return cls._open_json(request, timeout_seconds)

    @staticmethod
    def _open_json(request: Request, timeout_seconds: float) -> dict[str, Any]:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_code = ""
            error_type = ""
            error_param = ""
            try:
                decoded = json.loads(exc.read().decode("utf-8", errors="replace"))
                error = decoded.get("error") if isinstance(decoded, Mapping) else None
                if isinstance(error, Mapping):
                    raw_code = error.get("code")
                    raw_type = error.get("type")
                    raw_param = error.get("param")
                    if raw_code not in (None, ""):
                        error_code = str(raw_code)[:80]
                    if raw_type not in (None, ""):
                        error_type = str(raw_type)[:80]
                    if raw_param not in (None, ""):
                        error_param = str(raw_param)[:80]
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
            safe_detail = "/".join(
                part for part in (error_type, error_code, error_param) if part
            )
            raise OpenAITransportError(
                f"OpenAI HTTP {exc.code}{': ' + safe_detail if safe_detail else ''}",
                status_code=exc.code,
                error_code=error_code,
                error_type=error_type,
                error_param=error_param,
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise OpenAITransportError(
                "OpenAI connection failed",
                error_code=type(exc).__name__.lower(),
                error_type="connection",
            ) from None
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            raise OpenAITransportError(
                "OpenAI returned invalid JSON",
                error_code="invalid_json",
                error_type="response_validation",
            ) from None
        if not isinstance(decoded, dict):
            raise OpenAITransportError(
                "OpenAI returned a non-object response",
                error_code="non_object_response",
                error_type="response_validation",
            )
        return decoded


@dataclass(frozen=True, slots=True)
class CloudProviderExecutionResult:
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
    requests_count: int
    retries_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calculated_cost: float
    total_duration: float


class CloudProviderSandbox:
    """Six-department OpenAI-only sandbox with strict budget, schema and filesystem gates."""

    def __init__(
        self,
        raw_transport: Callable[[dict[str, Any]], Any],
        *,
        model: str,
        input_cost_per_million: float,
        output_cost_per_million: float,
        cost_governor: CostGovernor | None,
        budget_account: BudgetAccount | None,
        provider_policy: ProviderPolicy | None = None,
        organization: EngineeringOrganization | None = None,
        maximum_requests: int = DEFAULT_MAXIMUM_REQUESTS,
        maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
        maximum_input_tokens: int = DEFAULT_MAXIMUM_INPUT_TOKENS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_attempts_per_department: int = 2,
    ) -> None:
        if not model or not _MODEL_ID.fullmatch(model):
            raise ValueError("model ID is invalid")
        if cost_governor is None or budget_account is None:
            raise ValueError("BudgetAccount and CostGovernor are required")
        if not 0 < budget_account.limit <= DEFAULT_MAXIMUM_BUDGET_USD:
            raise ValueError("budget limit must be greater than zero and no more than 1.00 USD")
        if budget_account.spent != 0:
            raise ValueError("budget account must start with zero spend")
        if not 1 <= maximum_requests <= DEFAULT_MAXIMUM_REQUESTS:
            raise ValueError("maximum_requests must be between one and six")
        if not 1 <= maximum_output_tokens <= DEFAULT_MAXIMUM_OUTPUT_TOKENS:
            raise ValueError("maximum_output_tokens exceeds the Phase 22C limit")
        if maximum_input_tokens < 512:
            raise ValueError("maximum_input_tokens is too small")
        if not 1 <= timeout_seconds <= DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be between 1 and 180")
        if maximum_attempts_per_department not in (1, 2):
            raise ValueError("maximum_attempts_per_department must be one or two")
        if input_cost_per_million < 0 or output_cost_per_million < 0:
            raise ValueError("model prices must be non-negative")
        if input_cost_per_million == 0 and output_cost_per_million == 0:
            raise ValueError("at least one model price must be positive")

        self.model = model
        self.input_cost_per_million = float(input_cost_per_million)
        self.output_cost_per_million = float(output_cost_per_million)
        self.cost_governor = cost_governor
        self.budget_account = budget_account
        self.budget_scope = "phase22c:openai"
        self.cost_governor.set_limit(self.budget_scope, self.budget_account.limit)
        self.provider_policy = provider_policy or ProviderPolicy()
        self.organization = organization or EngineeringOrganization()
        self.maximum_requests = int(maximum_requests)
        self.maximum_output_tokens = int(maximum_output_tokens)
        self.maximum_input_tokens = int(maximum_input_tokens)
        self.timeout_seconds = float(timeout_seconds)
        self.maximum_attempts_per_department = maximum_attempts_per_department
        self._request_attempts = 0
        self._retries = 0
        self._successful_departments = 0
        self._token_counter = TokenCounter()

        capability = ModelCapability(
            provider="openai",
            model=model,
            tasks=frozenset({"coding", "reasoning"}),
            languages=frozenset({"ar", "en", "multilingual"}),
            supports_tools=False,
            local=False,
            max_context_tokens=maximum_input_tokens,
            quality_score=0.9,
            latency_score=0.8,
            privacy_score=0.45,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
        )
        self.provider = OpenAIProvider((capability,), raw_transport=raw_transport)
        self.provider.rate_limiter = AsyncRateLimiter(requests_per_minute=6, concurrent_requests=1)
        self.provider.retry = RetryManager(
            RetryPolicy(max_attempts=1, base_delay=0, max_delay=0, retryable=(TimeoutError, ConnectionError))
        )

    @property
    def worst_case_request_cost(self) -> float:
        return (
            self.maximum_input_tokens * self.input_cost_per_million
            + self.maximum_output_tokens * self.output_cost_per_million
        ) / 1_000_000

    def execute(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
        local_result_directory: str | Path,
    ) -> CloudProviderExecutionResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._execute_async(
                    execution_id=execution_id,
                    project=project,
                    objective=objective,
                    output_root=output_root,
                    local_result_directory=local_result_directory,
                )
            )
        raise RuntimeError("CloudProviderSandbox.execute cannot run inside an active event loop")

    async def _execute_async(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
        local_result_directory: str | Path,
    ) -> CloudProviderExecutionResult:
        root = self._prepare_root(output_root)
        safe_id = self._validate_execution_id(execution_id)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")
        if destination.exists():
            raise FileExistsError(f"cloud execution already exists: {safe_id}")
        if staging.exists():
            raise FileExistsError(f"cloud execution staging already exists: {safe_id}")
        local_directory = Path(local_result_directory).resolve(strict=True)
        if not local_directory.is_dir() or not (local_directory / "manifest.json").is_file():
            raise FileNotFoundError("local-model comparison execution is missing")

        self._assert_initial_budget()
        self.provider_policy.allowed_by_project[project] = {"openai"}
        self.provider_policy.blocked_providers.update(
            {"anthropic", "gemini", "openrouter", "ollama", "mistral", "cohere", "xai", "deepseek"}
        )

        staging.mkdir(mode=0o700)
        started = time.monotonic()
        try:
            artifacts_dir = staging / "artifacts"
            artifacts_dir.mkdir(mode=0o700)
            blueprint = self.organization.plan(project, objective)
            if len(blueprint.deliverables) != DEFAULT_MAXIMUM_REQUESTS:
                raise CloudSandboxValidationError("Phase 22C requires exactly six departments")
            artifact_records: list[dict[str, Any]] = []
            artifact_payloads: list[dict[str, Any]] = []

            for index, deliverable in enumerate(blueprint.deliverables):
                remaining_departments = len(blueprint.deliverables) - index
                generated, metrics, errors, attempts = await self._generate_department(
                    project=project,
                    objective=objective,
                    department=deliverable.department,
                    acceptance_criteria=deliverable.acceptance_criteria,
                    remaining_departments=remaining_departments,
                )
                wrapper = {
                    "schema_version": 1,
                    "execution_id": safe_id,
                    "project": project,
                    "objective": objective,
                    "provider": "openai",
                    "model": self.model,
                    "department": deliverable.department,
                    "model_output": generated,
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": attempts,
                    "attempt_errors": errors,
                    "metrics": metrics,
                    "data_policy": {
                        "raw_prompt_stored": False,
                        "raw_api_response_stored": False,
                        "authorization_header_stored": False,
                        "validated_engineering_artifact_stored": True,
                    },
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
                        "errors": errors,
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
                        "cloud_model": self.model,
                    }
                )
                self._successful_departments += 1

            if self._successful_departments != DEFAULT_MAXIMUM_REQUESTS:
                raise CloudSandboxValidationError("not all six departments completed")
            review = self.organization.chief_review(blueprint)
            total_duration = time.monotonic() - started
            aggregate = self._aggregate_metrics(artifact_records, total_duration)
            budget_snapshot = self.cost_governor.snapshot(self.budget_scope)
            artifact_hashes = {item["department"]: item["sha256"] for item in artifact_records}
            manifest = {
                "schema_version": 1,
                "execution_id": safe_id,
                "project": project,
                "objective": objective,
                "mode": "single-cloud-provider-sandbox",
                "provider": "openai",
                "model": self.model,
                "endpoint": ALLOWED_OPENAI_ENDPOINT,
                "execution_network_used": True,
                "provider_keys_used": True,
                "cloud_model_used": True,
                "production_modified": False,
                "fallback_used": False,
                "requests_count": self._request_attempts,
                "retries_count": self._retries,
                "maximum_requests": self.maximum_requests,
                "parallel_requests": 1,
                "maximum_output_tokens_per_request": self.maximum_output_tokens,
                "timeout_seconds": self.timeout_seconds,
                "temperature": 0,
                "input_tokens": aggregate["input_tokens"],
                "output_tokens": aggregate["output_tokens"],
                "total_tokens": aggregate["total_tokens"],
                "reported_cost": None,
                "calculated_cost": aggregate["calculated_cost"],
                "cost_basis": "token usage multiplied by operator-verified model rates",
                "budget_cap": self.budget_account.limit,
                "budget": budget_snapshot,
                "total_duration": aggregate["total_duration"],
                "latency": aggregate["latency"],
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
                "data_policy": {
                    "store_api_state": False,
                    "raw_prompt_stored": False,
                    "raw_api_response_stored": False,
                    "authorization_header_stored": False,
                    "api_key_stored": False,
                    "validated_engineering_artifacts_stored": True,
                },
                "proof": {
                    "execution_network_used": True,
                    "provider_keys_used": True,
                    "cloud_model_used": True,
                    "production_modified": False,
                    "fallback_used": False,
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write_text(manifest_path, self._canonical_json(manifest))
            report_path = staging / "REPORT.md"
            self._atomic_write_text(report_path, self._report(manifest))

            comparison = self._real_only_comparison(
                local_directory=local_directory,
                cloud_manifest=manifest,
                cloud_artifacts=artifact_payloads,
            )
            comparison_path = staging / "comparison.json"
            self._atomic_write_text(comparison_path, self._canonical_json(comparison))
            comparison_report_path = staging / "COMPARISON_REPORT.md"
            self._atomic_write_text(comparison_report_path, self._comparison_report(comparison))

            os.replace(staging, destination)
            return CloudProviderExecutionResult(
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
                requests_count=self._request_attempts,
                retries_count=self._retries,
                input_tokens=aggregate["input_tokens"],
                output_tokens=aggregate["output_tokens"],
                total_tokens=aggregate["total_tokens"],
                calculated_cost=aggregate["calculated_cost"],
                total_duration=aggregate["total_duration"],
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _assert_initial_budget(self) -> None:
        required = self.worst_case_request_cost * DEFAULT_MAXIMUM_REQUESTS
        if not self.cost_governor.authorize(self.budget_scope, required):
            raise CloudBudgetExceeded(
                "configured model pricing cannot fit six worst-case requests inside the budget cap"
            )

    async def _generate_department(
        self,
        *,
        project: str,
        objective: str,
        department: str,
        acceptance_criteria: tuple[str, ...],
        remaining_departments: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], int]:
        errors: list[str] = []
        for attempt in range(1, self.maximum_attempts_per_department + 1):
            if attempt > 1:
                self._retries += 1
            if self._request_attempts >= self.maximum_requests:
                raise CloudRequestLimitExceeded("Phase 22C request cap would be exceeded")
            self._authorize_remaining_budget(remaining_departments)
            prompt = self._prompt(
                project, objective, department, acceptance_criteria, errors[-1] if errors else None
            )
            estimated_input = self._token_counter.estimate_request(prompt, self._system_prompt())
            if estimated_input > self.maximum_input_tokens:
                raise CloudSandboxValidationError("request exceeds the Phase 22C input-token safety cap")
            request = ModelRequest(
                task="coding",
                prompt=prompt,
                system_prompt=self._system_prompt(),
                language="en",
                sensitivity=DataSensitivity.INTERNAL,
                max_cost=self.worst_case_request_cost,
                max_tokens=self.maximum_output_tokens,
                temperature=0.0,
                require_local=False,
                metadata={
                    "department": department,
                    "acceptance_criteria": list(acceptance_criteria),
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"phase22c_{department.lower()}",
                            "strict": True,
                            "schema": self._openai_json_schema(department, acceptance_criteria),
                        },
                    },
                },
            )
            capability = self.provider.capability(self.model)
            allowed, reason = self.provider_policy.allows(capability, request, project)
            if not allowed:
                raise CloudSandboxValidationError(f"provider policy denied request: {reason}")
            self._request_attempts += 1
            wall_started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.provider.generate(request, self.model), timeout=self.timeout_seconds
                )
            except OpenAITransportError as exc:
                if exc.status_code in {400, 401, 403, 404, 429}:
                    raise
                errors.append(self._safe_error(attempt, exc))
                if attempt >= self.maximum_attempts_per_department:
                    raise RuntimeError(
                        f"{department} failed after {attempt} attempts: {errors[-1]}"
                    ) from exc
                continue
            except (TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
                errors.append(self._safe_error(attempt, exc))
                if attempt >= self.maximum_attempts_per_department:
                    raise RuntimeError(
                        f"{department} failed after {attempt} attempts: {errors[-1]}"
                    ) from exc
                continue

            metrics = self._response_metrics(response, time.monotonic() - wall_started)
            self._record_cost(metrics["calculated_cost"])
            if metrics["input_tokens"] > self.maximum_input_tokens:
                raise CloudBudgetExceeded("provider-reported input tokens exceeded the configured safety cap")
            try:
                generated = LocalModelSandbox._parse_and_validate(
                    response.text, department, acceptance_criteria
                )
            except SandboxValidationError as exc:
                errors.append(self._safe_error(attempt, exc))
                if attempt >= self.maximum_attempts_per_department:
                    raise RuntimeError(
                        f"{department} failed after {attempt} attempts: {errors[-1]}"
                    ) from exc
                continue
            return generated, metrics, errors, attempt
        raise AssertionError("unreachable")

    def _authorize_remaining_budget(self, remaining_departments: int) -> None:
        required = self.worst_case_request_cost * remaining_departments
        if not self.cost_governor.authorize(self.budget_scope, required):
            raise CloudBudgetExceeded("remaining departments cannot fit inside the remaining budget")

    def _record_cost(self, cost: float) -> None:
        snapshot_before = self.cost_governor.snapshot(self.budget_scope)
        remaining = float(snapshot_before["remaining"] or 0.0)
        if not self.cost_governor.authorize(self.budget_scope, cost) and cost > remaining + 1e-12:
            raise CloudBudgetExceeded("response cost would exceed the remaining budget")
        self.cost_governor.record(self.budget_scope, cost)
        snapshot = self.cost_governor.snapshot(self.budget_scope)
        self.budget_account.spent = float(snapshot["spent"] or 0.0)
        if self.budget_account.spent > self.budget_account.limit + 1e-12:
            raise CloudBudgetExceeded("budget cap exceeded")

    @staticmethod
    def _safe_error(attempt: int, exc: BaseException) -> str:
        if isinstance(exc, OpenAITransportError):
            detail = f"status={exc.status_code}" if exc.status_code is not None else type(exc).__name__
            if exc.error_type:
                detail += f",type={exc.error_type}"
            if exc.error_code:
                detail += f",code={exc.error_code}"
            if exc.error_param:
                detail += f",param={exc.error_param}"
            return f"attempt {attempt}: OpenAITransportError({detail})"
        return f"attempt {attempt}: {type(exc).__name__}: {str(exc)[:160]}"

    @staticmethod
    def _openai_json_schema(department: str, criteria: tuple[str, ...]) -> dict[str, Any]:
        # Keep the provider schema inside the strict Structured Outputs subset. More
        # detailed cardinality and non-empty-string rules are enforced locally after receipt.
        evidence_item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["criterion", "evidence", "verification"],
            "properties": {
                "criterion": {"type": "string", "enum": list(criteria)},
                "evidence": {"type": "string"},
                "verification": {"type": "string"},
            },
        }
        risk_item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["risk", "mitigation"],
            "properties": {
                "risk": {"type": "string"},
                "mitigation": {"type": "string"},
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
                "schema_version": {"type": "integer", "enum": [1]},
                "department": {"type": "string", "enum": [department]},
                "summary": {"type": "string"},
                "implementation_plan": {"type": "array", "items": {"type": "string"}},
                "technical_evidence": {"type": "array", "items": evidence_item},
                "risks": {"type": "array", "items": risk_item},
                "tests_passed": {"type": "boolean"},
                "security_reviewed": {"type": "boolean"},
            },
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are one AIOS engineering department in a controlled single-provider sandbox. "
            "Use no tools, external browsing, secrets, or unstated execution evidence. "
            "Return only the requested JSON object. Never claim tests passed or a security review occurred "
            "unless explicit execution evidence is provided."
        )

    @staticmethod
    def _prompt(
        project: str,
        objective: str,
        department: str,
        criteria: tuple[str, ...],
        previous_error: str | None,
    ) -> str:
        criteria_lines = "\n".join(f"- {item}" for item in criteria)
        correction = f"\nCorrect this prior validation failure: {previous_error}\n" if previous_error else ""
        return (
            f"Project: {project}\nObjective: {objective}\nDepartment: {department}\n\n"
            "Produce a department-specific engineering artifact as one strict JSON object. "
            "Cover every acceptance criterion exactly once in technical_evidence using the criterion text verbatim. "
            "Provide concrete implementation steps, technical evidence, verification methods, and risk mitigations. "
            "No project source, user data, production secrets, or execution credentials are included in this request. "
            "Do not add keys outside the schema. Keep the summary and every string concise. "
            "Use exactly three implementation_plan items and exactly one risk item.\n\n"
            f"Acceptance criteria:\n{criteria_lines}\n{correction}"
        )

    @staticmethod
    def _response_metrics(response: Any, wall_duration: float) -> dict[str, Any]:
        metadata = response.metadata if isinstance(response.metadata, Mapping) else {}
        input_tokens = int(response.input_tokens or 0)
        output_tokens = int(response.output_tokens or 0)
        total_tokens = int(metadata.get("total_tokens", input_tokens + output_tokens) or 0)
        return {
            "wall_duration_seconds": round(wall_duration, 6),
            "latency_ms": round(float(response.latency_ms or 0.0), 4),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "reported_cost": metadata.get("reported_cost"),
            "calculated_cost": round(float(response.cost or 0.0), 10),
            "actual_model": str(metadata.get("actual_model", "")),
            "response_status": str(metadata.get("status", "")),
        }

    @staticmethod
    def _aggregate_metrics(artifact_records: list[dict[str, Any]], total_duration: float) -> dict[str, Any]:
        metrics = [item["metrics"] for item in artifact_records]
        return {
            "total_duration": round(total_duration, 6),
            "input_tokens": sum(int(item["input_tokens"]) for item in metrics),
            "output_tokens": sum(int(item["output_tokens"]) for item in metrics),
            "total_tokens": sum(int(item["total_tokens"]) for item in metrics),
            "calculated_cost": round(sum(float(item["calculated_cost"]) for item in metrics), 10),
            "latency": {
                "total_ms": round(sum(float(item["latency_ms"]) for item in metrics), 4),
                "average_ms": round(
                    sum(float(item["latency_ms"]) for item in metrics) / len(metrics), 4
                ),
                "departments": {
                    item["department"]: item["metrics"]["latency_ms"] for item in artifact_records
                },
            },
        }

    @classmethod
    def _real_only_comparison(
        cls,
        *,
        local_directory: Path,
        cloud_manifest: dict[str, Any],
        cloud_artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        local_manifest = json.loads((local_directory / "manifest.json").read_text(encoding="utf-8"))
        local_artifacts = [
            json.loads((local_directory / item["path"]).read_text(encoding="utf-8"))
            for item in local_manifest["artifacts"]
        ]
        local_quality = LocalModelSandbox._quality_metrics(local_artifacts, local=True)
        cloud_quality = LocalModelSandbox._quality_metrics(cloud_artifacts, local=True)
        local = {
            "provider": "ollama",
            "model": local_manifest.get("model"),
            "artifact_count": len(local_artifacts),
            "valid_json": local_manifest["schema_validation"]["all_valid"],
            "acceptance_coverage": local_manifest["acceptance_coverage"]["overall"],
            "approved": local_manifest["review"]["approved"],
            "readiness_score": local_manifest["review"]["readiness_score"],
            "blocking_findings": local_manifest["review"]["blocking_findings"],
            "rework_plan": local_manifest["review"]["rework_plan"],
            "total_duration": local_manifest["total_duration"],
            "input_tokens": local_manifest["prompt_eval_count"],
            "output_tokens": local_manifest["eval_count"],
            "calculated_cost": 0.0,
            "errors": [error for item in local_manifest["artifacts"] for error in item["errors"]],
            "quality": local_quality,
            "truthful_evidence": "retained local Qwen execution evidence",
            "value_per_cost": None,
        }
        cloud_cost = float(cloud_manifest["calculated_cost"])
        cloud = {
            "provider": "openai",
            "model": cloud_manifest["model"],
            "artifact_count": len(cloud_artifacts),
            "valid_json": cloud_manifest["schema_validation"]["all_valid"],
            "acceptance_coverage": cloud_manifest["acceptance_coverage"]["overall"],
            "approved": cloud_manifest["review"]["approved"],
            "readiness_score": cloud_manifest["review"]["readiness_score"],
            "blocking_findings": cloud_manifest["review"]["blocking_findings"],
            "rework_plan": cloud_manifest["review"]["rework_plan"],
            "total_duration": cloud_manifest["total_duration"],
            "input_tokens": cloud_manifest["input_tokens"],
            "output_tokens": cloud_manifest["output_tokens"],
            "calculated_cost": cloud_cost,
            "reported_cost": cloud_manifest["reported_cost"],
            "errors": [error for item in cloud_manifest["artifacts"] for error in item["errors"]],
            "quality": cloud_quality,
            "truthful_evidence": "live OpenAI execution evidence",
            "value_per_cost": round(cloud_quality["quality_score"] / cloud_cost, 4) if cloud_cost else None,
        }
        return {
            "schema_version": 2,
            "comparison_mode": "real-only",
            "project": cloud_manifest["project"],
            "objective": cloud_manifest["objective"],
            "local_qwen3_8b": local,
            "openai": cloud,
            "quality_method": (
                "Deterministic structural heuristic over two real execution evidence sets: schema validity, "
                "acceptance coverage, department specialization, actionability, risk clarity, technical evidence density, "
                "and pairwise repetition."
            ),
            "value_method": "quality heuristic divided by calculated token cost when cost is non-zero",
            "winner_by_quality": max(
                (("local_qwen3_8b", local_quality["quality_score"]), ("openai", cloud_quality["quality_score"])),
                key=lambda item: item[1],
            )[0],
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
        artifacts = "\n".join(
            f"- {item['department']}: `{item['path']}` — SHA-256 `{item['sha256']}` — "
            f"${item['metrics']['calculated_cost']:.10f}"
            for item in manifest["artifacts"]
        )
        blockers = review["blocking_findings"] or ["None"]
        rework = review["rework_plan"] or ["None"]
        return (
            "# Phase 22C Single Cloud Provider Sandbox Report\n\n"
            f"- Provider: `openai`\n"
            f"- Model: `{manifest['model']}`\n"
            f"- Requests: `{manifest['requests_count']}`\n"
            f"- Retries: `{manifest['retries_count']}`\n"
            f"- Input tokens: `{manifest['input_tokens']}`\n"
            f"- Output tokens: `{manifest['output_tokens']}`\n"
            f"- Calculated cost: `${manifest['calculated_cost']:.10f}`\n"
            f"- Budget cap: `${manifest['budget_cap']:.2f}`\n"
            f"- Total duration: `{manifest['total_duration']} seconds`\n"
            f"- Approved: `{str(review['approved']).lower()}`\n"
            f"- Readiness score: `{review['readiness_score']}`\n"
            "- Execution network used: `true`\n"
            "- Provider key used: `true`\n"
            "- Cloud model used: `true`\n"
            "- Fallback used: `false`\n"
            "- Production modified: `false`\n"
            "- Raw prompts/API responses/authorization headers stored: `false`\n\n"
            f"## Artifacts\n\n{artifacts}\n\n"
            "## Blocking findings\n\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n\n## Rework plan\n\n"
            + "\n".join(f"- {item}" for item in rework)
            + "\n"
        )

    @staticmethod
    def _comparison_report(comparison: dict[str, Any]) -> str:
        local = comparison["local_qwen3_8b"]
        cloud = comparison["openai"]
        return (
            "# Phase 22C Real-Only Comparison\n\n"
            "| Metric | qwen3:8b | OpenAI |\n"
            "|---|---:|---:|\n"
            f"| Artifacts | {local['artifact_count']} | {cloud['artifact_count']} |\n"
            f"| Acceptance coverage | {local['acceptance_coverage']} | {cloud['acceptance_coverage']} |\n"
            f"| Quality heuristic | {local['quality']['quality_score']} | {cloud['quality']['quality_score']} |\n"
            f"| Pairwise repetition | {local['quality']['pairwise_repetition']} | {cloud['quality']['pairwise_repetition']} |\n"
            f"| Total duration (s) | {local['total_duration']} | {cloud['total_duration']} |\n"
            f"| Input tokens | {local['input_tokens']} | {cloud['input_tokens']} |\n"
            f"| Output tokens | {local['output_tokens']} | {cloud['output_tokens']} |\n"
            f"| Calculated cost (USD) | {local['calculated_cost']} | {cloud['calculated_cost']} |\n"
            f"| Readiness | {local['readiness_score']} | {cloud['readiness_score']} |\n"
            f"| Approved | {local['approved']} | {cloud['approved']} |\n\n"
            f"Winner by documented quality heuristic: `{comparison['winner_by_quality']}`\n\n"
            f"Method: {comparison['quality_method']}\n\n"
            f"Value method: {comparison['value_method']}\n"
        )
