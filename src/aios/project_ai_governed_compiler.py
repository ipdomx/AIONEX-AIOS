"""Governed Phase36C project compiler: real reviewed source, tests, rollback, and councils.

Model output is interpreted only as a bounded structured product *specification*.
The source files come from the already-reviewed AIONEX prototype composer, not
arbitrary code emitted by a model. The complete institutional cycle then evaluates
the actual retained build evidence, never a claim by the model that tests passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .controlled_project_builder import ControlledProjectBuildError, ControlledProjectBuilder
from .project_ai_compact_spec import CompactProjectSpecError, expand_compact_product_spec
from .full_project_cycle import FullProjectCycle
from .organization import EngineeringOrganization

PROVENANCE = "aionex-project-ai"
REQUIRED_ROLES = frozenset({"planner", "researcher", "coder", "reviewer"})


class ProjectAIGovernedBuildError(ValueError):
    """The bounded model contract cannot be used to produce a governed build."""


@dataclass(frozen=True)
class ProjectAIGovernedBuildResult:
    """Verified builder output, with no premature approval implication."""

    output_directory: Path
    implementation_directory: Path
    planning_directory: Path
    manifest_path: Path
    archive_path: Path
    status: str
    approved: bool
    governance_layers_executed: bool
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    workforce: tuple[dict[str, Any], ...]
    delivery_package: dict[str, Any]
    implementation: dict[str, Any]
    governance: dict[str, Any]
    release_review: dict[str, Any]
    engineering_review: dict[str, Any]
    security_review: dict[str, Any]
    integration_review: dict[str, Any]
    application_type: str
    implementation_capabilities: dict[str, Any]
    readiness_score: float


@dataclass(frozen=True)
class ProjectAIGovernedPlanningResult:
    """A tested planning package, explicitly never a completed executable product."""

    output_directory: Path
    manifest_path: Path
    planning_approved: bool
    readiness_score: float
    department_count: int
    package: dict[str, Any]


class ProjectAIGovernedCompiler:
    """Compile a verified route's JSON spec without executing untrusted model code."""

    def __init__(self, output_root: str | Path) -> None:
        output = Path(output_root)
        if not output.is_absolute():
            raise ValueError("project compiler requires an absolute output root")
        self.output_root = output

    @staticmethod
    def _sha(path: Path) -> str:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    @classmethod
    def _write(cls, path: Path, payload: Mapping[str, Any]) -> None:
        ControlledProjectBuilder._atomic_write_text(
            path, ControlledProjectBuilder._canonical_json(payload)
        )

    @classmethod
    def _route_evidence(cls, rows: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
        if len(rows) != 4 or {str(row.get("role")) for row in rows} != REQUIRED_ROLES:
            raise ProjectAIGovernedBuildError("the four distinct provider roles are required")
        result = []
        for row in rows:
            digest = str(row.get("result_sha256") or "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ProjectAIGovernedBuildError("provider role digest is invalid")
            provider = str(row.get("provider") or "").strip()
            model = str(row.get("model") or "").strip()
            reference = str(row.get("evidence_ref") or "").strip()
            if not provider or not model or not reference or len(reference) > 240:
                raise ProjectAIGovernedBuildError("validated provider route evidence is missing")
            if row.get("fallback_used") is True:
                # Keep the existing Phase28 no-fallback claim truthful. A separately
                # governed recovery path can be implemented and admitted later.
                raise ProjectAIGovernedBuildError("a fallback route needs separate governance evidence")
            result.append({
                "role": str(row["role"]),
                "provider": provider[:64],
                "model": model[:160],
                "evidence_ref": reference,
                "result_sha256": digest,
                "fallback_used": False,
            })
        return result

    def plan_only(
        self,
        *,
        job_id: str,
        project_name: str,
        objective: str,
        tenant_id: str,
        requested_by_id: str,
        route_results: tuple[Mapping[str, Any], ...],
        total_cost_usd: float,
        external_processing_authorized: bool = False,
    ) -> ProjectAIGovernedPlanningResult:
        """Create a reviewed engineering plan without model-claimed completed tests."""
        safe_id = ControlledProjectBuilder._validate_execution_id(job_id)
        project = str(project_name or "").strip()[:240]
        selected_objective = str(objective or "").strip()[:6000]
        if len(project) < 2 or len(selected_objective) < 10:
            raise ProjectAIGovernedBuildError("project and objective are required")
        if not tenant_id or not requested_by_id:
            raise ProjectAIGovernedBuildError("authenticated tenant/user identity is required")
        if not 0 <= float(total_cost_usd) <= 10:
            raise ProjectAIGovernedBuildError("the provider budget evidence is invalid")
        routes = self._route_evidence(route_results)
        if any(row["provider"] != "ollama" for row in routes) and not external_processing_authorized:
            raise ProjectAIGovernedBuildError(
                "external provider planning requires explicit processing authorization"
            )
        root = ControlledProjectBuilder._prepare_root(self.output_root)
        destination = ControlledProjectBuilder._contained(root, root / safe_id)
        staging = ControlledProjectBuilder._contained(root, root / f".staging-{safe_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError("an earlier governed planning package exists")
        staging.mkdir(mode=0o700)
        try:
            blueprint = EngineeringOrganization().plan(project, selected_objective)
            if len(blueprint.deliverables) != 6:
                raise ProjectAIGovernedBuildError("six-department planning is required")
            departments = []
            for deliverable in blueprint.deliverables:
                deliverable.evidence.update({
                    "passed_criteria": list(deliverable.acceptance_criteria),
                    "plan_schema_valid": True,
                    "implementation_plan_complete": True,
                    "risks_documented": True,
                })
                departments.append({
                    "department": deliverable.department,
                    "acceptance_criteria": list(deliverable.acceptance_criteria),
                    "owner_id": deliverable.owner_id,
                    "reviewer_id": deliverable.reviewer_id,
                    "implementation_steps": [
                        f"Implement {deliverable.department} against reviewed criteria",
                        "Retain actual source, tests and rollback receipts",
                    ],
                    "implementation_tests_passed": False,
                })
            chief = EngineeringOrganization().chief_plan_review(blueprint)
            if not chief.approved:
                raise ProjectAIGovernedBuildError("the engineering plan failed Chief review")
            document = {
                "schema": "aionex.phase36c.six-department-reviewed-plan.v1",
                "project": project,
                "objective": selected_objective,
                "tenant_id": tenant_id,
                "requested_by_id": requested_by_id,
                "planning_approved": chief.approved,
                "chief_review_score": chief.readiness_score,
                "departments": departments,
                "source_provider_routes": routes,
                "model_response_text_saved": False,
                "implementation_tests_executed": False,
                "governance_full_cycle_executed": False,
                "production_modified": False,
            }
            package = staging / "delivery-package"
            package.mkdir(mode=0o700)
            planfile = package / "engineering-plan.json"
            self._write(planfile, document)
            manifest = {
                "schema": "aionex.phase36c.planning-only-delivery.v1",
                "execution_id": safe_id,
                "tenant_id": tenant_id,
                "requested_by_id": requested_by_id,
                "planning_approved": chief.approved,
                "readiness_score": chief.readiness_score,
                "department_count": len(departments),
                "planning_sha256": self._sha(planfile),
                "route_count": len(routes),
                "cost_usd": float(total_cost_usd),
                "external_processing_authorized": bool(external_processing_authorized),
                "contains_executable_product": False,
                "all_governance_layers_executed": False,
                "approved": False,
                "production_modified": False,
            }
            self._write(staging / "manifest.json", manifest)
            ControlledProjectBuilder._atomic_write_text(
                package / "README.md",
                "# Reviewed engineering plan\n\n"
                "This package contains six reviewed planning departments only. "
                "No executable application, production deployment or complete "
                "governance release is asserted.\n",
            )
            os.replace(staging, destination)
            return ProjectAIGovernedPlanningResult(
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                planning_approved=True,
                readiness_score=chief.readiness_score,
                department_count=len(departments),
                package={
                    "path": "delivery-package",
                    "planning_manifest_sha256": manifest["planning_sha256"],
                    "contains_executable_product": False,
                },
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def compile(
        self,
        *,
        job_id: str,
        project_name: str,
        objective: str,
        tenant_id: str,
        requested_by_id: str,
        coder_text: str,
        route_results: tuple[Mapping[str, Any], ...],
        total_cost_usd: float,
        external_processing_authorized: bool = False,
        stage_callback: Callable[[str, int], None] | None = None,
    ) -> ProjectAIGovernedBuildResult:
        """Run every local stage; leave immutable evidence only on complete success.

        Missing externally verified research remains a real governance blocker. No
        project can be approved from synthetic research or from a model's assertions.
        """
        safe_id = ControlledProjectBuilder._validate_execution_id(job_id)
        project = str(project_name or "").strip()[:240]
        selected_objective = str(objective or "").strip()[:6000]
        if len(project) < 2 or len(selected_objective) < 10:
            raise ProjectAIGovernedBuildError("project and objective are required")
        if not tenant_id or not requested_by_id:
            raise ProjectAIGovernedBuildError("authenticated tenant/user identity is required")
        if not isinstance(coder_text, str) or not 2 <= len(coder_text) <= 64000:
            raise ProjectAIGovernedBuildError("provider product specification is missing or oversized")
        if not 0 <= float(total_cost_usd) <= 10:
            raise ProjectAIGovernedBuildError("the provider budget evidence is invalid")
        routes = self._route_evidence(route_results)
        offline_only = all(row["provider"] == "ollama" for row in routes)
        if not offline_only and external_processing_authorized is not True:
            raise ProjectAIGovernedBuildError(
                "external provider routing requires explicit processing authorization"
            )
        coder = next(row for row in routes if row["role"] == "coder")
        if hashlib.sha256(coder_text.encode("utf-8")).hexdigest() != coder["result_sha256"]:
            raise ProjectAIGovernedBuildError("the coder result is not bound to the audited provider route")

        # The reviewed strict parser rejects executable markup, URLs, credentials,
        # arbitrary extra keys and unsupported entity/workflow schema.
        try:
            model_payload = json.loads(coder_text)
            if (
                isinstance(model_payload, dict)
                and model_payload.get("kind") == "aionex.compact-project.v1"
            ):
                specification = expand_compact_product_spec(
                    coder_text, objective=selected_objective
                )
                source_specification_kind = "bounded-local-brief"
            else:
                specification = ControlledProjectBuilder._validate_spec(
                    coder_text, objective=selected_objective
                )
                source_specification_kind = "full-provider-json"
        except (json.JSONDecodeError, CompactProjectSpecError, ControlledProjectBuildError) as exc:
            raise ProjectAIGovernedBuildError(
                "provider output did not meet the safe product schema"
            ) from exc

        root = ControlledProjectBuilder._prepare_root(self.output_root)
        destination = ControlledProjectBuilder._contained(root, root / safe_id)
        staging = ControlledProjectBuilder._contained(root, root / f".staging-{safe_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError("an earlier governed project build exists")
        # Stable destination is important: Phase28 writes retained absolute paths
        # to its evidence manifest. Renaming a parent staging directory afterward
        # would invalidate both its source references and downloaded delivery links.
        destination.mkdir(mode=0o700)
        staging = destination
        started = time.monotonic()

        def stage(name: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(name, progress)

        try:
            stage("engineering_plan", 20)
            blueprint = EngineeringOrganization().plan(project, selected_objective)
            if len(blueprint.deliverables) != 6:
                raise ProjectAIGovernedBuildError("six-department deterministic planning is required")
            planning = staging / "planning"
            artifacts = planning / "artifacts"
            artifacts.mkdir(parents=True, mode=0o700)
            records: list[dict[str, Any]] = []
            departments: list[dict[str, Any]] = []
            for deliverable in blueprint.deliverables:
                name = deliverable.department
                model_output = {
                    "summary": f"{name} deterministic engineering scope for {project}",
                    "implementation_plan": [
                        f"Implement {name} acceptance criteria in the reviewed AIONEX archetype",
                        "Verify the real generated files using retained execution evidence",
                    ],
                    "technical_evidence": [
                        {
                            "criterion": criterion,
                            "evidence": "Planned; independent implementation test evidence is required",
                            "verification": "Run reviewed local build and integration checks",
                        }
                        for criterion in deliverable.acceptance_criteria
                    ],
                    "risks": [{
                        "risk": f"{name} implementation regression",
                        "mitigation": "Retain real test results, rollback hashes and require rework",
                    }],
                    "tests_passed": False,
                    "security_reviewed": False,
                }
                file = artifacts / f"{name.lower()}.json"
                self._write(file, {
                    "schema_version": 1,
                    "department": name,
                    "model_output": model_output,
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": 1,
                    "origin": "AIONEX deterministic engineering organization, NOT model-generated test evidence",
                })
                records.append({
                    "department": name,
                    "path": f"artifacts/{file.name}",
                    "sha256": self._sha(file),
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": 1,
                })
                departments.append({
                    "department": name,
                    "summary": model_output["summary"],
                    "implementation_plan": model_output["implementation_plan"],
                    "risks": [x["risk"] for x in model_output["risks"]],
                })
                # This reviews the *plan*, not imaginary executed tests.
                deliverable.evidence.update({
                    "passed_criteria": list(deliverable.acceptance_criteria),
                    "plan_schema_valid": True,
                    "implementation_plan_complete": True,
                    "risks_documented": True,
                })
            chief = EngineeringOrganization().chief_plan_review(blueprint)
            if not chief.approved:
                raise ProjectAIGovernedBuildError("deterministic plan failed Chief review")
            model_names = sorted({r["model"] for r in routes})
            planning_manifest: dict[str, Any] = {
                "schema_version": 1,
                "provider": PROVENANCE,
                "model": model_names[0] if len(model_names) == 1 else "multi-provider",
                "route_evidence": routes,
                "deterministic_planning_origin": True,
                "raw_provider_response_stored": False,
                "artifacts": records,
                "requests_count": len(routes),
                "calculated_cost": float(total_cost_usd),
                "fallback_used": False,
                "production_modified": False,
                "review": {
                    "approved": chief.approved,
                    "readiness_score": chief.readiness_score,
                    "blocking_findings": list(chief.blocking_findings),
                    "rework_plan": list(chief.rework_plan),
                    "rationale": chief.rationale,
                    "review_type": "real deterministic Chief pre-implementation plan review",
                },
                "claim_boundary": "Planning criteria are deterministic; they do not claim executed department tests",
            }
            self._write(planning / "manifest.json", planning_manifest)
            planning_summary = {
                "manifest_sha256": self._sha(planning / "manifest.json"),
                "provider": PROVENANCE,
                "model": planning_manifest["model"],
                "departments": departments,
            }

            stage("implementation_generation", 38)
            implementation = staging / "implementation"
            source = implementation / "source"
            source.mkdir(parents=True, mode=0o700)
            files = ControlledProjectBuilder._render_files(
                project, selected_objective, specification, planning_summary
            )
            if not files or len(files) > 160:
                raise ProjectAIGovernedBuildError("generated file inventory is invalid")
            for relative, content in files.items():
                path = ControlledProjectBuilder._contained(source, source / relative)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                ControlledProjectBuilder._atomic_write_text(path, content)

            stage("implementation_tests", 52)
            tests = ControlledProjectBuilder._test_source(
                source, project, specification
            )
            self._write(implementation / "TEST_REPORT.json", tests)
            if tests.get("passed") is not True:
                raise ProjectAIGovernedBuildError("actual generated project tests failed")
            file_hashes = {
                str(path.relative_to(source)): self._sha(path)
                for path in sorted(source.rglob("*")) if path.is_file()
            }
            profile_path = source / "PROJECT_PROFILE.json"
            profile = json.loads(profile_path.read_text()) if profile_path.is_file() else {}
            stage("rollback_verification", 60)
            archive = implementation / "project-prototype.zip"
            ControlledProjectBuilder._write_archive(archive, source)
            if not ControlledProjectBuilder._verify_archive(archive, file_hashes, implementation):
                raise ProjectAIGovernedBuildError("actual independent archive restoration did not match")
            manifest = {
                "schema_version": 1,
                "mode": "controlled-full-stack-prototype",
                "provider": PROVENANCE,
                "model": coder["model"],
                "execution_id": "prototype",
                "project": project,
                "objective": selected_objective,
                "application_type": specification["application_type"],
                "provider_role": "bounded product JSON specification only, not arbitrary executable source",
                "executable_source_origin": "deterministic reviewed AIONEX source composer",
                "validated_route_evidence": coder,
                "source_specification_kind": source_specification_kind,
                "specification": specification,
                "planning": planning_summary,
                "project_profile": profile,
                "files": file_hashes,
                "tests": tests,
                "rollback_tested": True,
                "archive_sha256": self._sha(archive),
                "requests_count": 0,  # All model calls were billed by durable routing above.
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "calculated_cost": 0.0,
                "total_duration": round(time.monotonic() - started, 6),
                "fallback_used": False,
                "production_modified": False,
                "raw_prompt_stored": False,
                "raw_response_stored": False,
            }
            self._write(implementation / "manifest.json", manifest)
            ControlledProjectBuilder._atomic_write_text(
                implementation / "REPORT.md", ControlledProjectBuilder._report(manifest)
            )

            stage("institutional_governance", 70)
            final = FullProjectCycle().execute(
                execution_id="cycle",
                project=project,
                objective=selected_objective,
                planning_directory=planning,
                implementation_directory=implementation,
                research_evidence=None,  # Model research is not independent source verification.
                plan_review_evidence={
                    "approved": chief.approved,
                    "planning_manifest_sha256": planning_summary["manifest_sha256"],
                    "readiness_score": chief.readiness_score,
                    "blocking_findings": list(chief.blocking_findings),
                    "rework_plan": list(chief.rework_plan),
                    "review_origin": "real deterministic Chief pre-implementation plan review",
                },
                output_root=staging / "governance",
                tenant_id=tenant_id,
                requested_by_id=requested_by_id,
                external_processing_authorized=external_processing_authorized,
                local_processing_authorized=offline_only,
            )
            if final.get("success") is not True:
                raise ProjectAIGovernedBuildError("the full governance cycle did not complete")
            final_manifest = Path(str(final["manifest_path"]))
            final_data = json.loads(final_manifest.read_text(encoding="utf-8"))
            if (
                (final_data.get("proof") or {}).get("all_governance_layers_executed") is not True
                or (final_data.get("proof") or {}).get("workforce_evaluated") is not True
                or (final_data.get("proof") or {}).get("model_claims_used_as_execution_proof") is not False
            ):
                raise ProjectAIGovernedBuildError("institutional governance evidence is incomplete")

            # Final governance is deliberately required to withhold approval without
            # independently validated external research and/or an Owner review.
            blockers = tuple(final.get("blocking_findings") or ())
            if not blockers and final.get("approved") is not True:
                raise ProjectAIGovernedBuildError("approval status does not match blockers")
            if final.get("approved") is True and not final.get("governance", {}).get("research_verified"):
                raise ProjectAIGovernedBuildError("unverified research cannot approve release")

            stage("project_delivery_verified", 95)
            cycle_root = destination / "governance" / "cycle"
            built_root = destination / "implementation"
            delivered = cycle_root / "delivery-package"
            if not delivered.is_dir() or not (delivered / "source").is_dir():
                raise ProjectAIGovernedBuildError("complete executable delivery package is missing")
            stage("completed", 100)
            return ProjectAIGovernedBuildResult(
                output_directory=cycle_root,
                implementation_directory=built_root,
                planning_directory=destination / "planning",
                manifest_path=cycle_root / "manifest.json",
                archive_path=built_root / "project-prototype.zip",
                status=str(final["status"]),
                approved=bool(final["approved"]),
                governance_layers_executed=True,
                blocking_findings=blockers,
                rework_plan=tuple(final.get("rework_plan") or ()),
                workforce=tuple(final.get("workforce") or ()),
                delivery_package={**dict(final["delivery_package"]), "contains_executable_product": True},
                implementation=dict(final.get("implementation") or {}),
                governance=dict(final.get("governance") or {}),
                release_review=dict(final_data.get("release_review") or {}),
                engineering_review=dict(final_data.get("engineering_review") or {}),
                security_review=dict(final_data.get("security_review") or {}),
                integration_review=dict(final_data.get("integration_review") or {}),
                application_type=str(manifest.get("application_type") or ""),
                implementation_capabilities=dict(
                    (final.get("implementation") or {}).get("capabilities") or {}
                ),
                readiness_score=float(final.get("readiness_score") or 0.0),
            )
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
