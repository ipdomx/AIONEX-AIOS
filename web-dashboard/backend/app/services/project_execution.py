"""Controlled full-governed OpenAI project lifecycle for durable user jobs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, Mapping

from aios.cloud_provider_sandbox import (
    ALLOWED_OPENAI_ENDPOINT,
    ALLOWED_OPENAI_MODELS_ENDPOINT,
    CloudBudgetExceeded,
    CloudProviderSandbox,
    CloudRequestLimitExceeded,
    CloudSandboxValidationError,
    OpenAIOfficialHTTPTransport,
    OpenAITransportError,
)
from aios.offline_execution import (
    OfflineExecutionResult,
    OfflineMockExecutor,
)
from aios.controlled_project_builder import (
    ControlledProjectBuildError,
    ControlledProjectBuilder,
)
from aios.controlled_research import (
    ControlledResearchError,
    ControlledWebResearch,
)
from aios.full_project_cycle import FullProjectCycle, FullProjectCycleValidationError
from aios.providers import BudgetAccount, CostGovernor, ProviderPolicy

from app.core.config import settings

MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-mini-2025-08-07": (0.25, 2.00),
}
RESEARCH_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-nano-2026-03-17": (0.20, 1.25),
}
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ProjectExecutionConfigurationError(RuntimeError):
    """The project worker is not safely configured."""


class ProjectExecutionAlreadyStarted(RuntimeError):
    """A previous attempt left evidence that must not be overwritten."""


@dataclass(frozen=True, slots=True, repr=False)
class ProjectProviderSecret:
    api_key: str
    model: str

    def __repr__(self) -> str:
        return f"ProjectProviderSecret(api_key='[REDACTED]', model={self.model!r})"


def load_project_provider_secret(path: str | Path) -> ProjectProviderSecret:
    secret_path = Path(path)
    if not secret_path.is_absolute():
        raise ProjectExecutionConfigurationError("project provider secret path must be absolute")
    if not secret_path.is_file() or secret_path.is_symlink():
        raise ProjectExecutionConfigurationError("project provider secret is missing or unsafe")
    info = secret_path.stat()
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise ProjectExecutionConfigurationError("project provider secret must not be group/world accessible")
    if info.st_size <= 0 or info.st_size > 16_384:
        raise ProjectExecutionConfigurationError("project provider secret size is invalid")

    values: dict[str, str] = {}
    for raw_line in secret_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ProjectExecutionConfigurationError("project provider secret contains an invalid line")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name in values:
            raise ProjectExecutionConfigurationError("project provider secret contains a duplicate variable")
        values[name] = value
    allowed = {"OPENAI_API_KEY", "AIOS_PHASE22C_MODEL"}
    if set(values) != allowed:
        raise ProjectExecutionConfigurationError("project provider secret variables are invalid")
    api_key = values["OPENAI_API_KEY"]
    model = values["AIOS_PHASE22C_MODEL"]
    if not api_key or model not in MODEL_PRICING:
        raise ProjectExecutionConfigurationError("project provider model or key is not allowed")
    return ProjectProviderSecret(api_key=api_key, model=model)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(payload))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_comparison(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False}
    return {
        "available": True,
        "winner_by_quality": payload.get("winner_by_quality"),
        "offline_mock_readiness": (payload.get("offline_mock") or {}).get("readiness_score"),
        "local_model_readiness": (payload.get("local_qwen3_8b") or {}).get("readiness_score"),
        "openai_readiness": (payload.get("openai") or {}).get("readiness_score"),
    }


def _load_research_evidence(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectExecutionAlreadyStarted(
            "existing controlled research evidence is invalid"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("mode") != "controlled-web-research"
        or payload.get("provider") != "openai"
        or int(payload.get("request_count") or 0) != 1
        or int(payload.get("search_calls") or 0) != 1
        or payload.get("fallback_used") is not False
        or payload.get("production_modified") is not False
        or len(payload.get("sources") or []) < 2
        or len(payload.get("verified_facts") or []) < 2
    ):
        raise ProjectExecutionAlreadyStarted(
            "existing controlled research evidence is not trusted"
        )
    return payload


def _planning_objective(
    objective: str, research: Mapping[str, Any]
) -> str:
    facts = [
        str(item.get("claim") or "")[:500]
        for item in (research.get("verified_facts") or [])[:6]
        if isinstance(item, Mapping) and str(item.get("claim") or "").strip()
    ]
    constraints = [
        str(item)[:400]
        for item in (research.get("recommended_constraints") or [])[:6]
        if str(item).strip()
    ]
    source_domains = sorted(
        {
            str(item.get("domain") or "")
            for item in (research.get("sources") or [])
            if isinstance(item, Mapping) and str(item.get("domain") or "").strip()
        }
    )
    context = [
        objective,
        "",
        "Independent current research context verified by AIOS:",
        *[f"- Verified fact: {item}" for item in facts],
        *[f"- Engineering constraint: {item}" for item in constraints],
        f"- Independent source domains: {', '.join(source_domains)}",
        "Use these facts as constraints, but do not claim unexecuted tests, security reviews, deployments, or integrations.",
    ]
    return "\n".join(context)[:6000]


def _summary_from_manifest(manifest_path: Path, *, recovered: bool) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectExecutionAlreadyStarted("existing project execution manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("provider") != "openai":
        raise ProjectExecutionAlreadyStarted("existing project execution manifest is not trusted")
    review = manifest.get("review") or {}
    output_directory = manifest_path.parent
    return {
        "success": True,
        "status": "completed" if review.get("approved") is True else "completed_with_rework",
        "provider": "openai",
        "model": manifest.get("model"),
        "execution_id": manifest.get("execution_id"),
        "output_directory": str(output_directory),
        "manifest_path": str(manifest_path),
        "report_path": str(output_directory / "REPORT.md"),
        "comparison_path": str(output_directory / "comparison.json"),
        "comparison_report_path": str(output_directory / "COMPARISON_REPORT.md"),
        "artifacts_count": len(manifest.get("artifacts") or []),
        "requests_count": int(manifest.get("requests_count") or 0),
        "retries_count": int(manifest.get("retries_count") or 0),
        "input_tokens": int(manifest.get("input_tokens") or 0),
        "output_tokens": int(manifest.get("output_tokens") or 0),
        "total_tokens": int(manifest.get("total_tokens") or 0),
        "calculated_cost": float(manifest.get("calculated_cost") or 0.0),
        "budget_cap": float(manifest.get("budget_cap") or 0.0),
        "total_duration": float(manifest.get("total_duration") or 0.0),
        "approved": bool(review.get("approved")),
        "readiness_score": float(review.get("readiness_score") or 0.0),
        "blocking_findings": list(review.get("blocking_findings") or []),
        "rework_plan": list(review.get("rework_plan") or []),
        "comparison": _safe_comparison(output_directory / "comparison.json"),
        "recovered_from_existing_evidence": recovered,
        "fallback_used": False,
        "production_modified": False,
        "raw_prompt_returned": False,
        "raw_response_returned": False,
        "authorization_header_returned": False,
        "secret_returned": False,
    }


def _summary_from_full_manifest(
    manifest_path: Path,
    planning: Mapping[str, Any],
    *,
    recovered: bool,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectExecutionAlreadyStarted(
            "existing full project cycle manifest is invalid"
        ) from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("mode") != "full-governed-project-cycle"
        or manifest.get("phase") != 28
    ):
        raise ProjectExecutionAlreadyStarted(
            "existing full project cycle manifest is not trusted"
        )
    cycle_summary = manifest.get("summary") or {}
    release = manifest.get("release_review") or {}
    source = manifest.get("source_planning") or {}
    implementation = manifest.get("implementation") or {}
    external_research = manifest.get("external_research") or {}
    implementation_requests = int(implementation.get("requests_count") or 0)
    research_requests = int(external_research.get("request_count") or 0)
    output_directory = manifest_path.parent
    return {
        "success": True,
        "phase": 28,
        "mode": "full",
        "status": str(cycle_summary.get("status") or "rework_required"),
        "provider": str(planning.get("provider") or "openai"),
        "model": planning.get("model") or source.get("model"),
        "execution_id": manifest.get("execution_id"),
        "output_directory": str(output_directory),
        "manifest_path": str(manifest_path),
        "report_path": str(output_directory / "REPORT.md"),
        "planning_output_directory": planning.get("output_directory"),
        "planning_manifest_path": planning.get("manifest_path"),
        "planning_report_path": planning.get("report_path"),
        "comparison_path": planning.get("comparison_path"),
        "comparison_report_path": planning.get("comparison_report_path"),
        "artifacts_count": int(planning.get("artifacts_count") or 0),
        "requests_count": int(planning.get("requests_count") or 0)
        + implementation_requests
        + research_requests,
        "retries_count": int(planning.get("retries_count") or 0),
        "input_tokens": int(planning.get("input_tokens") or 0)
        + int(implementation.get("input_tokens") or 0)
        + int(external_research.get("input_tokens") or 0),
        "output_tokens": int(planning.get("output_tokens") or 0)
        + int(implementation.get("output_tokens") or 0)
        + int(external_research.get("output_tokens") or 0),
        "total_tokens": int(planning.get("total_tokens") or 0)
        + int(implementation.get("total_tokens") or 0)
        + int(external_research.get("total_tokens") or 0),
        "calculated_cost": float(planning.get("calculated_cost") or 0.0)
        + float(implementation.get("calculated_cost") or 0.0)
        + float(external_research.get("calculated_cost") or 0.0),
        "budget_cap": float(planning.get("budget_cap") or 0.0),
        "total_duration": float(planning.get("total_duration") or 0.0)
        + float(implementation.get("total_duration") or 0.0)
        + float(external_research.get("total_duration") or 0.0)
        + float(cycle_summary.get("duration_seconds") or 0.0),
        "approved": bool(cycle_summary.get("approved")),
        "readiness_score": float(cycle_summary.get("readiness_score") or 0.0),
        "blocking_findings": list(release.get("blocking_findings") or []),
        "rework_plan": list(release.get("rework_plan") or []),
        "governance": {
            "cognitive": manifest.get("cognitive_review"),
            "constitution": manifest.get("constitutional_review"),
            "research": manifest.get("research_verification"),
            "wisdom": manifest.get("wisdom_deliberation"),
            "government": manifest.get("government_review"),
            "ministries": manifest.get("ministry_routing"),
        },
        "workforce": list(manifest.get("workforce") or []),
        "engineering_review": manifest.get("engineering_review"),
        "security_review": manifest.get("security_review"),
        "integration_review": manifest.get("integration_review"),
        "release_review": release,
        "delivery_package": manifest.get("delivery_package"),
        "implementation": implementation or None,
        "external_research": external_research or None,
        "web_search_calls": int(external_research.get("search_calls") or 0),
        "comparison": planning.get("comparison") or {},
        "recovered_from_existing_evidence": recovered,
        "all_governance_layers_executed": bool(
            (manifest.get("proof") or {}).get("all_governance_layers_executed")
        ),
        "model_claims_used_as_execution_proof": False,
        "fallback_used": False,
        "production_modified": False,
        "raw_prompt_returned": False,
        "raw_response_returned": False,
        "authorization_header_returned": False,
        "secret_returned": False,
    }


def _load_offline_result(directory: Path) -> OfflineExecutionResult:
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectExecutionAlreadyStarted("existing offline reference is invalid") from exc
    review = manifest.get("review") or {}
    artifacts = manifest.get("artifacts") or []
    return OfflineExecutionResult(
        execution_id=str(manifest.get("execution_id") or "offline"),
        output_directory=directory,
        manifest_path=manifest_path,
        report_path=directory / "REPORT.md",
        artifact_paths=tuple(directory / str(item["path"]) for item in artifacts),
        approved=bool(review.get("approved")),
        readiness_score=float(review.get("readiness_score") or 0.0),
        blocking_findings=tuple(str(item) for item in review.get("blocking_findings") or []),
        rework_plan=tuple(str(item) for item in review.get("rework_plan") or []),
    )


class ProjectPlanningRunner:
    """Run bounded planning, implementation and complete governance with evidence."""

    def __init__(self) -> None:
        self.output_root = Path(settings.PROJECT_EXECUTION_OUTPUT_ROOT)
        self.local_reference = Path(settings.PROJECT_EXECUTION_LOCAL_REFERENCE)
        self.secret_path = Path(settings.PROJECT_EXECUTION_SECRET_FILE)
        self.budget_cap = float(settings.PROJECT_EXECUTION_BUDGET_CAP_USD)
        self.web_search_tool_cost = float(
            settings.PROJECT_EXECUTION_WEB_SEARCH_COST_USD
        )
        self.research_model = settings.PROJECT_EXECUTION_RESEARCH_MODEL.strip()
        if not self.output_root.is_absolute() or not self.local_reference.is_absolute():
            raise ProjectExecutionConfigurationError("project execution paths must be absolute")
        if not 0 < self.budget_cap <= 0.05:
            raise ProjectExecutionConfigurationError(
                "project execution budget cap must be at most 0.05 USD"
            )
        if not 0 < self.web_search_tool_cost <= self.budget_cap:
            raise ProjectExecutionConfigurationError(
                "project web search tool cost must fit inside the execution budget"
            )
        if self.research_model not in RESEARCH_MODEL_PRICING:
            raise ProjectExecutionConfigurationError(
                "project research model is not in the fixed allowlist"
            )
        planning_model = "gpt-5-mini"
        planning_prices = MODEL_PRICING[planning_model]
        research_prices = RESEARCH_MODEL_PRICING[self.research_model]
        planning_worst_case = 6 * (
            4096 * planning_prices[0] + 1200 * planning_prices[1]
        ) / 1_000_000
        research_worst_case = self.web_search_tool_cost + (
            16_384 * research_prices[0] + 3000 * research_prices[1]
        ) / 1_000_000
        implementation_worst_case = (
            4096 * planning_prices[0] + 1200 * planning_prices[1]
        ) / 1_000_000
        if (
            planning_worst_case
            + research_worst_case
            + implementation_worst_case
            > self.budget_cap + 1e-12
        ):
            raise ProjectExecutionConfigurationError(
                "complete project lifecycle worst-case cost exceeds the fixed budget"
            )

    def run(
        self,
        *,
        job_id: str,
        project_name: str,
        objective: str,
        tenant_id: str = "platform",
        requested_by_id: str = "system",
        stage_callback: Callable[[str, int], None] | None = None,
    ) -> dict[str, Any]:
        if not _EXECUTION_ID.fullmatch(job_id):
            raise ValueError("project execution id is invalid")
        normalized_project = project_name.strip()[:240]
        normalized_objective = objective.strip()[:6000]
        if len(normalized_project) < 2 or len(normalized_objective) < 10:
            raise ValueError("project name and objective are required")

        def report_stage(stage: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(stage, max(0, min(100, int(progress))))

        job_root = (self.output_root / job_id).resolve(strict=False)
        expected_root = self.output_root.resolve(strict=False)
        if expected_root not in job_root.parents:
            raise ValueError("project execution path escapes the output root")
        receipt_path = job_root / "execution-receipt.json"
        research_manifest = job_root / "research" / "manifest.json"
        cloud_manifest = job_root / "cloud" / "manifest.json"
        implementation_directory = job_root / "implementation" / "prototype"
        implementation_manifest = implementation_directory / "manifest.json"
        full_manifest = job_root / "full-cycle" / "cycle" / "manifest.json"
        if receipt_path.is_file():
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ProjectExecutionAlreadyStarted(
                    "existing project execution receipt is invalid"
                )
            payload = dict(payload)
            payload["recovered_from_existing_evidence"] = True
            return payload
        if full_manifest.is_file() and cloud_manifest.is_file():
            planning = _summary_from_manifest(cloud_manifest, recovered=True)
            summary = _summary_from_full_manifest(
                full_manifest, planning, recovered=True
            )
            _atomic_json(receipt_path, summary)
            return summary
        if (job_root / ".staging-cloud").exists():
            raise ProjectExecutionAlreadyStarted(
                "an incomplete cloud execution already exists"
            )

        if (
            not self.local_reference.is_dir()
            or not (self.local_reference / "manifest.json").is_file()
        ):
            raise ProjectExecutionConfigurationError(
                "retained local-model reference is missing"
            )
        job_root.mkdir(parents=True, exist_ok=True, mode=0o700)

        lifecycle = FullProjectCycle()
        lifecycle.preflight(
            execution_id="preflight",
            project=normalized_project,
            objective=normalized_objective,
            output_root=job_root / "governance-intake",
            requested_by_id=requested_by_id,
            external_processing_authorized=True,
            stage_callback=lambda stage, progress: report_stage(stage, progress),
        )

        if research_manifest.is_file():
            research_evidence = _load_research_evidence(research_manifest)
        else:
            secret = load_project_provider_secret(self.secret_path)
            pricing = MODEL_PRICING[secret.model]
            report_stage("provider_model_validation", 20)
            validation_transport = OpenAIOfficialHTTPTransport(
                secret.api_key,
                endpoint=ALLOWED_OPENAI_ENDPOINT,
                models_endpoint=ALLOWED_OPENAI_MODELS_ENDPOINT,
                timeout_seconds=180.0,
                maximum_requests=1,
                input_cost_per_million=pricing[0],
                output_cost_per_million=pricing[1],
            )
            model_status = asyncio.run(
                validation_transport.validate_model(secret.model)
            )
            if model_status.get("id") != secret.model:
                raise OpenAITransportError(
                    "configured OpenAI model is unavailable"
                )
            research_pricing = RESEARCH_MODEL_PRICING[self.research_model]
            report_stage("research_model_validation", 24)
            research_model_status = asyncio.run(
                validation_transport.validate_model(self.research_model)
            )
            if research_model_status.get("id") != self.research_model:
                raise OpenAITransportError(
                    "configured OpenAI research model is unavailable"
                )
            report_stage("external_research", 28)
            research_result = ControlledWebResearch(
                secret.api_key,
                model=self.research_model,
                input_cost_per_million=research_pricing[0],
                output_cost_per_million=research_pricing[1],
                remaining_budget_usd=self.budget_cap,
                web_search_tool_cost_usd=self.web_search_tool_cost,
            ).execute(
                project=normalized_project,
                objective=normalized_objective,
            )
            research_evidence = {
                "schema_version": 1,
                "mode": "controlled-web-research",
                "request_count": 1,
                **research_result.sanitized(),
            }
            _atomic_json(research_manifest, research_evidence)

        governed_planning_objective = _planning_objective(
            normalized_objective, research_evidence
        )

        if cloud_manifest.is_file():
            planning = _summary_from_manifest(cloud_manifest, recovered=True)
        else:
            secret = load_project_provider_secret(self.secret_path)
            pricing = MODEL_PRICING[secret.model]
            offline_directory = job_root / "offline"
            if offline_directory.is_dir():
                offline_result = _load_offline_result(offline_directory)
                offline_duration = 0.0
            else:
                offline_started = time.monotonic()
                offline_result = OfflineMockExecutor().execute(
                    execution_id="offline",
                    project=normalized_project,
                    objective=normalized_objective,
                    output_root=job_root,
                )
                offline_duration = time.monotonic() - offline_started

            report_stage("provider_execution", 36)
            transport = OpenAIOfficialHTTPTransport(
                secret.api_key,
                endpoint=ALLOWED_OPENAI_ENDPOINT,
                models_endpoint=ALLOWED_OPENAI_MODELS_ENDPOINT,
                timeout_seconds=180.0,
                maximum_requests=6,
                input_cost_per_million=pricing[0],
                output_cost_per_million=pricing[1],
            )
            sandbox = CloudProviderSandbox(
                transport,
                model=secret.model,
                input_cost_per_million=pricing[0],
                output_cost_per_million=pricing[1],
                cost_governor=CostGovernor(),
                budget_account=BudgetAccount(limit=self.budget_cap),
                provider_policy=ProviderPolicy(),
                maximum_requests=6,
                maximum_output_tokens=1200,
                maximum_input_tokens=4096,
                timeout_seconds=180.0,
                maximum_attempts_per_department=1,
            )
            result = sandbox.execute(
                execution_id="cloud",
                project=normalized_project,
                objective=governed_planning_objective,
                output_root=job_root,
                offline_result=offline_result,
                local_result_directory=self.local_reference,
                offline_run_metrics={"total_duration": offline_duration},
            )
            planning = _summary_from_manifest(
                result.manifest_path, recovered=False
            )
            report_stage("provider_execution_completed", 52)

        if implementation_manifest.is_file():
            implementation_result = ControlledProjectBuilder.load_result(
                implementation_directory
            )
        else:
            secret = load_project_provider_secret(self.secret_path)
            pricing = MODEL_PRICING[secret.model]
            remaining_budget = (
                self.budget_cap
                - float(planning.get("calculated_cost") or 0.0)
                - float(research_evidence.get("calculated_cost") or 0.0)
            )
            if remaining_budget <= 0:
                raise CloudBudgetExceeded(
                    "planning consumed the complete project execution budget"
                )
            implementation_transport = OpenAIOfficialHTTPTransport(
                secret.api_key,
                endpoint=ALLOWED_OPENAI_ENDPOINT,
                models_endpoint=ALLOWED_OPENAI_MODELS_ENDPOINT,
                timeout_seconds=180.0,
                maximum_requests=1,
                input_cost_per_million=pricing[0],
                output_cost_per_million=pricing[1],
            )
            implementation_result = ControlledProjectBuilder(
                implementation_transport,
                model=secret.model,
                input_cost_per_million=pricing[0],
                output_cost_per_million=pricing[1],
                remaining_budget_usd=remaining_budget,
            ).execute(
                execution_id="prototype",
                project=normalized_project,
                objective=normalized_objective,
                planning_directory=Path(str(planning["output_directory"])),
                output_root=job_root / "implementation",
                stage_callback=lambda stage, progress: report_stage(
                    stage, 52 + round((progress - 60) * 0.55)
                ),
            )
            if (
                float(planning.get("calculated_cost") or 0.0)
                + float(research_evidence.get("calculated_cost") or 0.0)
                + implementation_result.calculated_cost
                > self.budget_cap + 1e-12
            ):
                raise CloudBudgetExceeded(
                    "combined planning and implementation cost exceeded the budget"
                )

        final_result = lifecycle.execute(
            execution_id="cycle",
            project=normalized_project,
            objective=normalized_objective,
            planning_directory=Path(str(planning["output_directory"])),
            implementation_directory=implementation_result.output_directory,
            research_evidence=research_evidence,
            output_root=job_root / "full-cycle",
            tenant_id=tenant_id,
            requested_by_id=requested_by_id,
            external_processing_authorized=True,
            stage_callback=lambda stage, progress: report_stage(
                stage, 70 + round(progress * 0.3)
            ),
        )
        summary = _summary_from_full_manifest(
            Path(final_result["manifest_path"]), planning, recovered=False
        )
        _atomic_json(receipt_path, summary)
        return summary


def sanitized_execution_error(exc: BaseException) -> tuple[str, str]:
    """Return a stable public error code and non-sensitive message."""
    if isinstance(exc, ProjectExecutionConfigurationError):
        return "configuration", str(exc)[:300]
    if isinstance(exc, ProjectExecutionAlreadyStarted):
        return "duplicate_or_incomplete_execution", str(exc)[:300]
    if isinstance(exc, CloudBudgetExceeded):
        return "budget_exceeded", "The fixed project execution budget was exceeded."
    if isinstance(exc, CloudRequestLimitExceeded):
        return "request_limit", "The fixed project execution request limit was reached."
    if isinstance(
        exc,
        (
            CloudSandboxValidationError,
            ControlledProjectBuildError,
            ControlledResearchError,
            FullProjectCycleValidationError,
        ),
    ):
        return (
            "validation",
            "The project evidence did not satisfy the full governed execution contract.",
        )
    if isinstance(exc, OpenAITransportError):
        if exc.error_code == "response_incomplete":
            return (
                "provider_incomplete",
                "The provider response ended before the governed result was complete.",
            )
        if exc.status_code in {401, 403}:
            return "provider_authentication", "The configured provider rejected authentication."
        if exc.status_code == 404:
            return "model_unavailable", "The configured provider model is unavailable."
        if exc.status_code == 429:
            return "provider_quota", "The provider rate or quota limit was reached."
        return "provider_transport", "The provider request could not be completed."
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "network_or_timeout", "The project execution timed out or lost connectivity."
    return "execution_failed", "The project execution failed safely."
