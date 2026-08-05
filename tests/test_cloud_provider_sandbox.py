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

import aios.cloud_provider_sandbox as cloud_module
from aios.cloud_provider_sandbox import (
    ALLOWED_OPENAI_ENDPOINT,
    ALLOWED_OPENAI_MODELS_ENDPOINT,
    CloudBudgetExceeded,
    CloudProviderSandbox,
    CloudRequestLimitExceeded,
    CloudSandboxValidationError,
    OpenAIOfficialHTTPTransport,
    OpenAITransportError,
    Phase22CSecret,
    SecretConfigurationError,
    load_phase22c_secret,
)
from aios.offline_execution import OfflineMockExecutor
from aios.organization import EngineeringOrganization
from aios.providers import BudgetAccount, CostGovernor, ProviderPolicy
from aios.providers.adapters import OpenAIProvider


MODEL = "test-text-model"
INPUT_RATE = 1.0
OUTPUT_RATE = 2.0
API_KEY = "sk-test-secret-that-must-never-leak"


def _pretend_root_owned(monkeypatch, target: Path) -> None:
    """Keep the production root-owner guard while making CI fixtures portable."""
    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        value = original_stat(self, *args, **kwargs)
        if self == target:
            class RootOwnedStat:
                st_mode = value.st_mode
                st_uid = 0
                st_size = value.st_size

            return RootOwnedStat()
        return value

    monkeypatch.setattr(Path, "stat", fake_stat)


def valid_department_payload(department, criteria, *, tests_passed=True, security_reviewed=True):
    return {
        "schema_version": 1,
        "department": department,
        "summary": f"Concrete {department} cloud-provider design with explicit boundaries and verification steps.",
        "implementation_plan": [
            f"Implement the first {department} control with explicit inputs, outputs, and failure handling.",
            f"Validate the second {department} control with deterministic assertions and archived evidence.",
            f"Review the final {department} control against rollback, monitoring, and operational requirements.",
        ],
        "technical_evidence": [
            {
                "criterion": criterion,
                "evidence": f"The {department} artifact documents concrete technical evidence for {criterion}.",
                "verification": f"Run deterministic {department} verification for {criterion} and archive the result.",
            }
            for criterion in criteria
        ],
        "risks": [
            {
                "risk": f"A {department} integration boundary could regress under an unexpected change.",
                "mitigation": f"Use isolated {department} regression checks and a reviewed rollback procedure.",
            }
        ],
        "tests_passed": tests_passed,
        "security_reviewed": security_reviewed,
    }


class FakeRawTransport:
    def __init__(self, *, mode="valid", tests_passed=True, security_reviewed=True, cost=0.001):
        self.mode = mode
        self.tests_passed = tests_passed
        self.security_reviewed = security_reviewed
        self.cost = cost
        self.calls = []
        self.active = 0
        self.maximum_active = 0

    async def __call__(self, payload):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
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
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "latency_ms": 250.0,
                "cost": self.cost,
                "confidence": 1.0,
                "status": "completed",
                "actual_model": MODEL,
                "reported_cost": None,
                "calculated_cost": self.cost,
            }
        finally:
            self.active -= 1


def create_offline(tmp_path):
    return OfflineMockExecutor().execute(
        execution_id="offline",
        project="AIONEX-AIOS",
        objective="Compare controlled cloud execution",
        output_root=tmp_path / "offline-root",
    )


def create_local_reference(tmp_path):
    root = tmp_path / "local-reference"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    organization = EngineeringOrganization()
    blueprint = organization.plan("AIONEX-AIOS", "Compare controlled cloud execution")
    records = []
    for item in blueprint.deliverables:
        wrapper = {
            "schema_version": 1,
            "execution_id": "local-reference",
            "project": "AIONEX-AIOS",
            "objective": "Compare controlled cloud execution",
            "provider": "ollama",
            "model": "qwen3:8b",
            "department": item.department,
            "model_output": valid_department_payload(
                item.department, item.acceptance_criteria, tests_passed=False, security_reviewed=False
            ),
            "schema_valid": True,
            "acceptance_coverage": 1.0,
            "attempts": 1,
            "attempt_errors": [],
            "metrics": {"wall_duration_seconds": 1.0, "eval_count": 50},
        }
        path = artifacts / f"{item.department.lower()}.json"
        path.write_text(json.dumps(wrapper), encoding="utf-8")
        records.append(
            {
                "department": item.department,
                "path": f"artifacts/{path.name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "schema_valid": True,
                "acceptance_coverage": 1.0,
                "attempts": 1,
                "errors": [],
                "metrics": wrapper["metrics"],
            }
        )
    manifest = {
        "schema_version": 1,
        "project": "AIONEX-AIOS",
        "objective": "Compare controlled cloud execution",
        "model": "qwen3:8b",
        "artifacts": records,
        "schema_validation": {"all_valid": True},
        "acceptance_coverage": {"overall": 1.0},
        "review": {
            "approved": False,
            "readiness_score": 0.82,
            "blocking_findings": ["tests have not passed"],
            "rework_plan": ["pass department tests"],
        },
        "total_duration": 10.0,
        "prompt_eval_count": 600,
        "eval_count": 300,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def make_sandbox(transport=None, *, budget=1.0, governor=None, account=None, policy=None, **kwargs):
    return CloudProviderSandbox(
        transport or FakeRawTransport(),
        model=MODEL,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        cost_governor=governor if governor is not None else CostGovernor(),
        budget_account=account if account is not None else BudgetAccount(budget),
        provider_policy=policy,
        **kwargs,
    )


def execute_success(tmp_path, *, transport=None, sandbox=None):
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    active_sandbox = sandbox or make_sandbox(transport)
    result = active_sandbox.execute(
        execution_id="cloud",
        project="AIONEX-AIOS",
        objective="Compare controlled cloud execution",
        output_root=tmp_path / "cloud-root",
        offline_result=offline,
        local_result_directory=local,
        offline_run_metrics={"total_duration": 0.01},
    )
    return active_sandbox, result, offline, local


def responses_payload():
    return {
        "model": MODEL,
        "input": [{"role": "user", "content": "x"}],
        "max_output_tokens": 1200,
        "temperature": 0.0,
        "tools": [],
        "metadata": {},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "phase22c_test",
                "strict": True,
                "schema": {"type": "object", "additionalProperties": False, "properties": {}},
            },
        },
    }


def completed_api_response():
    return {
        "id": "resp_test",
        "status": "completed",
        "model": MODEL,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "{}"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def test_official_transport_accepts_only_responses_endpoint_and_normalizes_response():
    captured = {}

    def post_json(url, payload, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": dict(headers), "timeout": timeout})
        return completed_api_response()

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=post_json,
    )
    result = asyncio.run(transport(responses_payload()))
    assert captured["url"] == ALLOWED_OPENAI_ENDPOINT
    assert captured["payload"]["store"] is False
    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert captured["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert result["text"] == "{}"
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert result["actual_model"] == MODEL
    assert result["reported_cost"] is None
    assert result["cost"] == pytest.approx(0.00002)
    assert API_KEY not in repr(transport)


def test_gpt5_mini_omits_temperature_and_uses_minimal_reasoning():
    captured = {}

    def post_json(url, payload, headers, timeout):
        captured["payload"] = payload
        return completed_api_response()

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=post_json,
    )
    payload = responses_payload()
    payload["model"] = "gpt-5-mini"
    asyncio.run(transport(payload))

    assert "temperature" not in captured["payload"]
    assert captured["payload"]["reasoning"] == {"effort": "minimal"}
    assert captured["payload"]["text"]["verbosity"] == "low"
    assert captured["payload"]["store"] is False


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://api.openai.com/v1/responses",
        "https://example.com/v1/responses",
        "https://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/responses/",
        "https://api.openai.com/v1/responses?x=1",
        "https://user:pass@api.openai.com/v1/responses",
    ),
)
def test_transport_rejects_every_non_official_endpoint(endpoint):
    with pytest.raises(ValueError, match="official OpenAI"):
        OpenAIOfficialHTTPTransport(
            API_KEY,
            endpoint=endpoint,
            input_cost_per_million=INPUT_RATE,
            output_cost_per_million=OUTPUT_RATE,
        )


def test_model_availability_uses_only_official_models_endpoint():
    captured = {}

    def get_json(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = dict(headers)
        return {"id": MODEL, "object": "model", "owned_by": "openai"}

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        get_json=get_json,
        post_json=lambda *args: completed_api_response(),
    )
    result = asyncio.run(transport.validate_model(MODEL))
    assert captured["url"] == f"{ALLOWED_OPENAI_MODELS_ENDPOINT}/{MODEL}"
    assert result["id"] == MODEL
    assert API_KEY not in json.dumps(result)



def test_incomplete_response_has_only_sanitized_diagnostic_fields():
    def post_json(url, payload, headers, timeout):
        return {
            "id": "resp_incomplete",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
            "usage": None,
        }

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=post_json,
    )

    with pytest.raises(OpenAITransportError) as raised:
        asyncio.run(transport(responses_payload()))

    assert raised.value.status_code is None
    assert raised.value.error_type == "response_status"
    assert raised.value.error_code == "response_incomplete"
    assert raised.value.error_param == "max_output_tokens"
    assert API_KEY not in str(raised.value)


def test_transport_rejects_tools_and_nonzero_temperature():
    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=lambda *args: completed_api_response(),
    )
    payload = responses_payload()
    payload["tools"] = [{"type": "web_search"}]
    with pytest.raises(CloudSandboxValidationError, match="tools"):
        asyncio.run(transport(payload))

    payload = responses_payload()
    payload["temperature"] = 0.2
    with pytest.raises(CloudSandboxValidationError, match="temperature"):
        asyncio.run(transport(payload))


def test_transport_refuses_more_than_hard_request_cap():
    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        maximum_requests=1,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=lambda *args: completed_api_response(),
    )
    asyncio.run(transport(responses_payload()))
    with pytest.raises(CloudRequestLimitExceeded):
        asyncio.run(transport(responses_payload()))


def test_transport_serializes_requests():
    lock = threading.Lock()
    active = 0
    maximum = 0

    def post_json(url, payload, headers, timeout):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return completed_api_response()

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        maximum_requests=3,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=post_json,
    )

    async def run():
        await asyncio.gather(
            transport(responses_payload()),
            transport(responses_payload()),
            transport(responses_payload()),
        )

    asyncio.run(run())
    assert maximum == 1
    assert transport.maximum_active_requests == 1
    assert transport.request_count == 3


def test_openai_schema_uses_provider_supported_subset_and_local_validation_remains_strict():
    schema = CloudProviderSandbox._openai_json_schema("Backend", ("one", "two", "three"))
    encoded = json.dumps(schema)
    for unsupported in ("minLength", "maxLength", "minItems", "maxItems", "pattern"):
        assert unsupported not in encoded
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_budget_governor_and_budget_account_are_mandatory():
    with pytest.raises(ValueError, match="BudgetAccount and CostGovernor"):
        CloudProviderSandbox(
            FakeRawTransport(),
            model=MODEL,
            input_cost_per_million=INPUT_RATE,
            output_cost_per_million=OUTPUT_RATE,
            cost_governor=None,
            budget_account=BudgetAccount(1.0),
        )
    with pytest.raises(ValueError, match="BudgetAccount and CostGovernor"):
        CloudProviderSandbox(
            FakeRawTransport(),
            model=MODEL,
            input_cost_per_million=INPUT_RATE,
            output_cost_per_million=OUTPUT_RATE,
            cost_governor=CostGovernor(),
            budget_account=None,
        )


def test_secret_loader_accepts_only_root_owned_mode_600_exact_variables(tmp_path, monkeypatch):
    secret_path = tmp_path / "phase22c-openai.env"
    secret_path.write_text(
        "OPENAI_API_KEY=" + API_KEY + "\nAIOS_PHASE22C_MODEL=" + MODEL + "\n",
        encoding="utf-8",
    )
    secret_path.chmod(0o600)
    monkeypatch.setattr(cloud_module, "PHASE22C_SECRET_PATH", secret_path)
    _pretend_root_owned(monkeypatch, secret_path)
    secret = load_phase22c_secret(secret_path)
    assert secret.model == MODEL
    assert secret.key_last4 == API_KEY[-4:]
    assert API_KEY not in repr(secret)

    secret_path.chmod(0o644)
    with pytest.raises(SecretConfigurationError, match="permissions must be 600"):
        load_phase22c_secret(secret_path)


def test_secret_loader_rejects_unknown_or_duplicate_variables(tmp_path, monkeypatch):
    secret_path = tmp_path / "phase22c-openai.env"
    monkeypatch.setattr(cloud_module, "PHASE22C_SECRET_PATH", secret_path)
    _pretend_root_owned(monkeypatch, secret_path)
    secret_path.write_text(
        "OPENAI_API_KEY=" + API_KEY + "\nAIOS_PHASE22C_MODEL=" + MODEL + "\nEXTRA=value\n",
        encoding="utf-8",
    )
    secret_path.chmod(0o600)
    with pytest.raises(SecretConfigurationError, match="unsupported variables"):
        load_phase22c_secret(secret_path)

    secret_path.write_text(
        "OPENAI_API_KEY=" + API_KEY + "\nOPENAI_API_KEY=duplicate\nAIOS_PHASE22C_MODEL=" + MODEL + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SecretConfigurationError, match="duplicate variable"):
        load_phase22c_secret(secret_path)


def test_run_stops_before_first_request_when_budget_cannot_cover_six_requests(tmp_path):
    transport = FakeRawTransport()
    sandbox = make_sandbox(transport, account=BudgetAccount(0.001), governor=CostGovernor())
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    root = tmp_path / "cloud-root"
    with pytest.raises(CloudBudgetExceeded, match="six worst-case requests"):
        sandbox.execute(
            execution_id="cloud",
            project="AIONEX-AIOS",
            objective="Compare controlled cloud execution",
            output_root=root,
            offline_result=offline,
            local_result_directory=local,
        )
    assert transport.calls == []
    assert not root.exists() or list(root.iterdir()) == []


def test_accumulated_actual_cost_stops_before_budget_exceed(tmp_path):
    transport = FakeRawTransport(cost=0.2)
    sandbox = make_sandbox(transport)
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    root = tmp_path / "cloud-root"
    with pytest.raises(CloudBudgetExceeded, match="remaining departments"):
        sandbox.execute(
            execution_id="cloud",
            project="AIONEX-AIOS",
            objective="Compare controlled cloud execution",
            output_root=root,
            offline_result=offline,
            local_result_directory=local,
        )
    assert len(transport.calls) == 5
    assert sandbox.budget_account.spent == pytest.approx(1.0)
    assert not (root / "cloud").exists()
    assert not (root / ".staging-cloud").exists()


def test_complete_cycle_creates_six_artifacts_manifest_reports_and_three_way_comparison(tmp_path):
    transport = FakeRawTransport(cost=0.001)
    sandbox, result, _, _ = execute_success(tmp_path, transport=transport)
    assert isinstance(sandbox.provider, OpenAIProvider)
    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.blocking_findings == ()
    assert result.rework_plan == ()
    assert result.requests_count == 6
    assert result.retries_count == 0
    assert result.input_tokens == 600
    assert result.output_tokens == 300
    assert result.total_tokens == 900
    assert result.calculated_cost == pytest.approx(0.006)
    assert len(result.artifact_paths) == 6
    assert transport.maximum_active == 1

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider"] == "openai"
    assert manifest["model"] == MODEL
    assert manifest["requests_count"] == 6
    assert manifest["retries_count"] == 0
    assert manifest["maximum_requests"] == 6
    assert manifest["parallel_requests"] == 1
    assert manifest["maximum_output_tokens_per_request"] == 1200
    assert manifest["temperature"] == 0
    assert manifest["fallback_used"] is False
    assert manifest["production_modified"] is False
    assert manifest["schema_validation"]["all_valid"] is True
    assert manifest["acceptance_coverage"]["overall"] == 1.0
    assert manifest["reported_cost"] is None
    assert manifest["calculated_cost"] == pytest.approx(0.006)
    assert manifest["budget_cap"] == 1.0
    assert manifest["data_policy"]["api_key_stored"] is False
    assert API_KEY not in json.dumps(manifest)

    for record in manifest["artifacts"]:
        path = result.output_directory / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["provider"] == "openai"
        assert payload["schema_valid"] is True
        assert payload["acceptance_coverage"] == 1.0
        assert payload["data_policy"]["raw_prompt_stored"] is False
        assert API_KEY not in path.read_text(encoding="utf-8")

    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    assert set(comparison) >= {"offline_mock", "local_qwen3_8b", "openai"}
    assert comparison["offline_mock"]["artifact_count"] == 6
    assert comparison["local_qwen3_8b"]["artifact_count"] == 6
    assert comparison["openai"]["artifact_count"] == 6
    assert comparison["openai"]["calculated_cost"] == pytest.approx(0.006)
    assert comparison["openai"]["value_per_cost"] is not None
    assert result.report_path.is_file()
    assert result.comparison_report_path.is_file()


def test_unit_cycle_uses_no_network_with_fake_transport(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", blocked)
    _, result, _, _ = execute_success(tmp_path)
    assert result.manifest_path.is_file()


@pytest.mark.parametrize("mode", ("invalid-json", "missing-key", "missing-criterion", "extra-key"))
def test_invalid_outputs_fail_and_staging_is_cleaned(tmp_path, mode):
    transport = FakeRawTransport(mode=mode)
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    sandbox = make_sandbox(transport)
    root = tmp_path / "cloud-root"
    with pytest.raises((RuntimeError, CloudRequestLimitExceeded)):
        sandbox.execute(
            execution_id="failed",
            project="AIONEX-AIOS",
            objective="Compare controlled cloud execution",
            output_root=root,
            offline_result=offline,
            local_result_directory=local,
        )
    assert not (root / "failed").exists()
    assert not (root / ".staging-failed").exists()
    assert list(root.iterdir()) == []
    assert len(transport.calls) <= 2


def test_false_model_evidence_flows_to_engineering_review_without_fabrication(tmp_path):
    transport = FakeRawTransport(tests_passed=False, security_reviewed=False)
    _, result, _, _ = execute_success(tmp_path, transport=transport)
    assert result.approved is False
    assert result.readiness_score == 0.82
    assert any("tests have not passed" in item for item in result.blocking_findings)
    assert any("security review is missing" in item for item in result.blocking_findings)
    assert result.rework_plan


@pytest.mark.parametrize("execution_id", ("../escape", "nested/path", "/absolute", "..", ".", "a\\b"))
def test_path_traversal_is_rejected(tmp_path, execution_id):
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    root = tmp_path / "cloud-root"
    with pytest.raises(ValueError):
        make_sandbox().execute(
            execution_id=execution_id,
            project="p",
            objective="o",
            output_root=root,
            offline_result=offline,
            local_result_directory=local,
        )
    assert not any(root.iterdir()) if root.exists() else True


def test_output_root_must_be_absolute(tmp_path, monkeypatch):
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        make_sandbox().execute(
            execution_id="cloud",
            project="p",
            objective="o",
            output_root=Path("relative"),
            offline_result=offline,
            local_result_directory=local,
        )
    assert not (tmp_path / "relative").exists()


def test_existing_execution_is_never_replaced(tmp_path):
    sandbox, result, offline, local = execute_success(tmp_path)
    before = {
        path.relative_to(result.output_directory): path.read_bytes()
        for path in result.output_directory.rglob("*")
        if path.is_file()
    }
    with pytest.raises(FileExistsError):
        sandbox.execute(
            execution_id="cloud",
            project="second",
            objective="second",
            output_root=tmp_path / "cloud-root",
            offline_result=offline,
            local_result_directory=local,
        )
    after = {
        path.relative_to(result.output_directory): path.read_bytes()
        for path in result.output_directory.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_atomic_write_failure_cleans_staging(tmp_path, monkeypatch):
    offline = create_offline(tmp_path)
    local = create_local_reference(tmp_path)
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
    root = tmp_path / "cloud-root"
    with pytest.raises(RuntimeError, match="simulated atomic failure"):
        sandbox.execute(
            execution_id="atomic-failure",
            project="AIONEX-AIOS",
            objective="Compare controlled cloud execution",
            output_root=root,
            offline_result=offline,
            local_result_directory=local,
        )
    assert not (root / "atomic-failure").exists()
    assert not (root / ".staging-atomic-failure").exists()
    assert list(root.iterdir()) == []


def test_no_file_outside_output_root_is_modified(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    before = sentinel.stat().st_mtime_ns, sentinel.read_bytes()
    _, result, _, _ = execute_success(tmp_path)
    after = sentinel.stat().st_mtime_ns, sentinel.read_bytes()
    assert after == before
    assert all(result.output_directory in path.parents for path in result.artifact_paths)


def test_no_fallback_provider_is_constructed_or_used(tmp_path):
    policy = ProviderPolicy()
    sandbox = make_sandbox(policy=policy)
    sandbox, result, _, _ = execute_success(tmp_path, sandbox=sandbox)
    assert sandbox.provider.name == "openai"
    assert set(policy.allowed_by_project["AIONEX-AIOS"]) == {"openai"}
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["fallback_used"] is False
    assert all(json.loads(path.read_text())["provider"] == "openai" for path in result.artifact_paths)


def test_secret_loader_requires_exact_external_path_root_owner_and_mode_600(tmp_path):
    with pytest.raises(SecretConfigurationError, match="secret path"):
        load_phase22c_secret(tmp_path / "secret.env")


def test_secret_objects_and_transport_errors_do_not_leak_key():
    secret = Phase22CSecret(api_key=API_KEY, model=MODEL)
    assert API_KEY not in repr(secret)
    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=lambda *args: (_ for _ in ()).throw(OpenAITransportError("safe failure", status_code=401)),
    )
    with pytest.raises(OpenAITransportError) as raised:
        asyncio.run(transport(responses_payload()))
    assert API_KEY not in str(raised.value)
    assert API_KEY not in repr(transport)


def test_executor_source_contains_no_shell_or_subprocess_calls_and_no_cloud_fallback():
    source = inspect.getsource(cloud_module)
    forbidden = (
        "import subprocess",
        "from subprocess",
        "os.system(",
        "Popen(",
        "shell=True",
        "OllamaProvider(",
        "OpenRouterProvider(",
        "ClaudeProvider(",
        "GeminiProvider(",
    )
    assert not any(item in source for item in forbidden)


def test_manifest_and_reports_never_contain_authorization_or_secret(tmp_path):
    _, result, _, _ = execute_success(tmp_path)
    for path in result.output_directory.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert API_KEY not in text
            assert "Authorization" not in text
            assert "Bearer " not in text


def test_transport_supports_explicit_implementation_output_ceiling() -> None:
    captured = {}

    def post_json(url, payload, headers, timeout):
        captured["max_output_tokens"] = payload["max_output_tokens"]
        return completed_api_response()

    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        maximum_requests=1,
        maximum_output_tokens=3000,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=post_json,
    )
    payload = responses_payload()
    payload["max_output_tokens"] = 3000
    asyncio.run(transport(payload))
    assert transport.maximum_output_tokens == 3000
    assert captured["max_output_tokens"] == 3000


def test_transport_default_output_ceiling_remains_phase22c_limit() -> None:
    transport = OpenAIOfficialHTTPTransport(
        API_KEY,
        input_cost_per_million=INPUT_RATE,
        output_cost_per_million=OUTPUT_RATE,
        post_json=lambda *args: completed_api_response(),
    )
    payload = responses_payload()
    payload["max_output_tokens"] = 1201
    with pytest.raises(CloudSandboxValidationError, match="configured transport limit"):
        asyncio.run(transport(payload))
