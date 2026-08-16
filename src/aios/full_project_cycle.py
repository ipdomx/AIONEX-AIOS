from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .academy import Academy, Course
from .cognitive import CognitiveCore
from .government import GovernanceCase, GovernmentRuntime
from .hr import CareerSystem, EmployeeRecord, EmploymentState
from .intelligence import ConstitutionEngine, Strategy, WisdomEngine
from .knowledge_learning import KnowledgeLearningPlatform, MemoryScope, ResearchClaim
from .ministries import build_default_ministry_registry
from .organization import EngineeringOrganization
from .orchestration import MasterOrchestrator
from .security_platform import SecurityPlatform
from .workers import WorkRequest, WorkerRuntime
from .workforce_health import OperationalHealthInstitute, WorkerObservation


DEFAULT_OUTPUT_ROOT = Path("/var/tmp/aionex-full-project-cycles")
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
StageCallback = Callable[[str, int], None]


class FullProjectCycleValidationError(ValueError):
    """Raised when retained project-planning evidence is unsafe or incomplete."""


class FullProjectCycle:
    """Run one project through AIOS cognition, government, engineering and workforce gates.

    The cycle deliberately does not turn model claims into executed test evidence. It
    completes every institutional review and returns an approved release only when the
    supplied project evidence genuinely satisfies every gate.
    """

    STAGES: tuple[tuple[str, int], ...] = (
        ("intake", 5),
        ("cognitive_review", 12),
        ("constitutional_review", 20),
        ("research_verification", 28),
        ("wisdom_deliberation", 36),
        ("government_review", 44),
        ("ministry_routing", 52),
        ("workforce_execution", 64),
        ("engineering_review", 74),
        ("security_review", 82),
        ("integration_review", 90),
        ("release_review", 96),
        ("completed", 100),
    )

    def preflight(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
        requested_by_id: str,
        external_processing_authorized: bool,
        stage_callback: StageCallback | None = None,
    ) -> dict[str, Any]:
        """Run the institutional intake before any paid provider request."""
        safe_id = self._validate_execution_id(execution_id)
        selected_project = project.strip()
        selected_objective = objective.strip()
        if len(selected_project) < 2 or len(selected_objective) < 10:
            raise FullProjectCycleValidationError(
                "project and objective are required for governance preflight"
            )
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / safe_id)
        manifest_path = destination / "manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("mode") != "governance-preflight":
                raise FullProjectCycleValidationError(
                    "existing governance preflight is invalid"
                )
            if payload.get("allowed_for_controlled_planning") is not True:
                raise FullProjectCycleValidationError(
                    "existing governance preflight did not authorize controlled planning"
                )
            return payload
        if destination.exists():
            raise FileExistsError(f"governance preflight already exists: {safe_id}")
        staging = self._contained(root, root / f".staging-{safe_id}")
        if staging.exists():
            raise FileExistsError(f"governance preflight staging exists: {safe_id}")
        staging.mkdir(mode=0o700)

        def stage(name: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(name, progress)

        try:
            stage("intake", 5)
            objective_hash = hashlib.sha256(
                selected_objective.encode("utf-8")
            ).hexdigest()
            stage("cognitive_review", 12)
            cognitive = CognitiveCore(staging / "decision-ledger.jsonl").decide(
                "Authorize controlled project planning",
                self._governance_objective(selected_objective),
                project=selected_project,
                risk_level=self._risk_level(selected_objective),
                metadata={
                    "objective_sha256": objective_hash,
                    "external_processing_authorized": external_processing_authorized,
                },
            )
            stage("constitutional_review", 20)
            constitution = ConstitutionEngine().evaluate(
                "prepare a controlled provider-backed project plan",
                evidence=(
                    f"objective:{objective_hash}",
                    "user-confirmed-external-processing",
                ),
                dry_run_passed=True,
                rollback_available=True,
                authorization=bool(external_processing_authorized),
                environment="sandbox",
                destructive=False,
                self_modifying=False,
                security_sensitive=False,
            )
            stage("wisdom_deliberation", 28)
            wisdom = WisdomEngine().decide(
                (
                    Strategy(
                        "controlled-evidence-first-planning",
                        0.92,
                        0.90,
                        0.96,
                        0.94,
                        0.95,
                        0.30,
                        0.50,
                        0.96,
                    ),
                    Strategy(
                        "direct-unreviewed-provider-call",
                        0.55,
                        0.25,
                        0.30,
                        0.30,
                        0.25,
                        0.20,
                        0.20,
                        0.20,
                    ),
                )
            )
            stage("government_review", 36)
            government = GovernmentRuntime("platform-owner").review(
                GovernanceCase(
                    case_id=safe_id,
                    title=f"Planning authorization for {selected_project}",
                    action="controlled_provider_planning",
                    proposer=requested_by_id,
                    evidence=(
                        f"objective:{objective_hash}",
                        f"cognitive:{cognitive.status.value}",
                        f"wisdom:{wisdom.selected.name if wisdom.selected else 'abstained'}",
                        "explicit-user-consent",
                    ),
                    risks=tuple(cognitive.risks[:2]),
                    requires_owner_approval=False,
                    metadata={
                        "authorization": external_processing_authorized,
                        "rollback_plan": "cancel before provider request or retain immutable evidence",
                        "irreversible": False,
                    },
                )
            )
            allowed = (
                external_processing_authorized
                and not constitution.violations
                and government["verdict"] == "approved"
                and wisdom.selected is not None
            )
            payload = {
                "schema_version": 1,
                "mode": "governance-preflight",
                "execution_id": safe_id,
                "project": selected_project,
                "objective_sha256": objective_hash,
                "requested_by_id": requested_by_id,
                "allowed_for_controlled_planning": allowed,
                "cognitive_review": {
                    "status": cognitive.status.value,
                    "score": cognitive.score,
                    "confidence": cognitive.confidence,
                    "quorum_reached": cognitive.quorum_reached,
                    "human_approval_required_for_release": cognitive.human_approval_required,
                    "conditions": list(cognitive.conditions),
                    "risks": list(cognitive.risks),
                    "opinions": [
                        {
                            "cell": item.cell_id,
                            "vote": item.vote.value,
                            "confidence": item.confidence,
                        }
                        for item in cognitive.opinions
                    ],
                },
                "constitutional_review": {
                    "allowed": constitution.allowed,
                    "violations": list(constitution.violations),
                    "conditions": list(constitution.conditions),
                    "rationale": constitution.rationale,
                },
                "wisdom_deliberation": {
                    "selected": wisdom.selected.name if wisdom.selected else None,
                    "ranking": [list(item) for item in wisdom.ranking],
                    "confidence": wisdom.confidence,
                    "abstained": wisdom.abstained,
                    "rationale": wisdom.rationale,
                },
                "government_review": government,
                "proof": {
                    "paid_provider_request_sent": False,
                    "external_processing_authorized": bool(
                        external_processing_authorized
                    ),
                    "production_modified": False,
                },
            }
            self._atomic_write_text(
                staging / "manifest.json", self._canonical_json(payload)
            )
            os.replace(staging, destination)
            if not allowed:
                raise FullProjectCycleValidationError(
                    "institutional preflight did not authorize controlled planning"
                )
            return payload
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def execute(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        planning_directory: str | Path,
        implementation_directory: str | Path | None = None,
        research_evidence: Mapping[str, Any] | None = None,
        plan_review_evidence: Mapping[str, Any] | None = None,
        output_root: str | Path = DEFAULT_OUTPUT_ROOT,
        tenant_id: str = "platform",
        requested_by_id: str = "system",
        external_processing_authorized: bool = True,
        stage_callback: StageCallback | None = None,
    ) -> dict[str, Any]:
        safe_id = self._validate_execution_id(execution_id)
        selected_project = project.strip()
        selected_objective = objective.strip()
        if len(selected_project) < 2 or len(selected_objective) < 10:
            raise FullProjectCycleValidationError(
                "project and objective are required for the full project cycle"
            )
        root = self._prepare_root(output_root)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")
        if destination.exists() or staging.exists():
            raise FileExistsError(f"full project cycle already exists: {safe_id}")

        source = Path(planning_directory).resolve(strict=True)
        manifest, artifacts = self._validate_planning_source(source)
        planning_manifest_sha256 = self._sha256(source / "manifest.json")
        if plan_review_evidence is not None:
            if (
                plan_review_evidence.get("approved") is not True
                or str(plan_review_evidence.get("planning_manifest_sha256") or "")
                != planning_manifest_sha256
            ):
                raise FullProjectCycleValidationError(
                    "pre-implementation plan review evidence is missing approval or does not bind the planning manifest"
                )
        implementation = (
            self._validate_implementation_source(
                Path(implementation_directory).resolve(strict=True),
                planning_manifest_sha256=self._sha256(source / "manifest.json"),
            )
            if implementation_directory is not None
            else None
        )
        staging.mkdir(mode=0o700)
        started = time.monotonic()

        def stage(name: str, progress: int) -> None:
            if stage_callback is not None:
                stage_callback(name, progress)

        try:
            stage("intake", 5)
            intake = {
                "project": selected_project,
                "objective": selected_objective,
                "tenant_id": tenant_id,
                "requested_by_id": requested_by_id,
                "external_processing_authorized": bool(external_processing_authorized),
                "planning_manifest_sha256": planning_manifest_sha256,
                "pre_implementation_plan_approved": bool(
                    plan_review_evidence is not None
                    and plan_review_evidence.get("approved") is True
                ),
                "planning_provider": manifest["provider"],
                "planning_model": manifest["model"],
                "department_count": len(artifacts),
                "implementation_manifest_sha256": (
                    implementation["manifest_sha256"] if implementation else None
                ),
                "executable_implementation_available": implementation is not None,
            }

            stage("cognitive_review", 12)
            risk_level = self._risk_level(selected_objective)
            cognitive = CognitiveCore(staging / "decision-ledger.jsonl").decide(
                "Execute full governed project cycle",
                self._governance_objective(selected_objective),
                project=selected_project,
                risk_level=risk_level,
                metadata={
                    "planning_manifest_sha256": intake["planning_manifest_sha256"],
                    "external_processing_authorized": external_processing_authorized,
                },
            )
            cognitive_payload: dict[str, Any] = {
                "status": cognitive.status.value,
                "score": cognitive.score,
                "confidence": cognitive.confidence,
                "quorum_reached": cognitive.quorum_reached,
                "round_number": cognitive.round_number,
                "human_approval_required": cognitive.human_approval_required,
                "conditions": list(cognitive.conditions),
                "risks": list(cognitive.risks),
                "opinions": [
                    {
                        "cell": opinion.cell_id,
                        "vote": opinion.vote.value,
                        "confidence": opinion.confidence,
                        "summary": opinion.summary,
                        "risks": list(opinion.risks),
                        "conditions": list(opinion.conditions),
                    }
                    for opinion in cognitive.opinions
                ],
            }

            stage("constitutional_review", 20)
            constitution = ConstitutionEngine().evaluate(
                "execute controlled project lifecycle",
                evidence=(
                    f"planning-manifest:{intake['planning_manifest_sha256']}",
                    "strict-department-schema-validated",
                    "explicit-external-processing-consent",
                ),
                dry_run_passed=True,
                rollback_available=True,
                authorization=bool(external_processing_authorized),
                environment="sandbox",
                destructive=False,
                security_sensitive=self._security_sensitive(selected_objective),
            )
            constitution_payload: dict[str, Any] = {
                "allowed": constitution.allowed,
                "requires_human_approval": constitution.requires_human_approval,
                "violations": list(constitution.violations),
                "conditions": list(constitution.conditions),
                "rationale": constitution.rationale,
            }

            stage("research_verification", 28)
            knowledge = KnowledgeLearningPlatform(staging / "knowledge")
            scope_verification = knowledge.verify_claim(
                "The user scope is represented by independently attributable project evidence.",
                (
                    ResearchClaim(
                        claim="The objective was explicitly supplied by the requesting user.",
                        source=f"user:{requested_by_id}",
                        source_quality=0.98,
                        corroboration=4,
                        direct_evidence=True,
                    ),
                    ResearchClaim(
                        claim="Six schema-validated departments interpreted the objective.",
                        source=f"planning:{intake['planning_manifest_sha256']}",
                        source_quality=0.92,
                        corroboration=6,
                        direct_evidence=True,
                    ),
                    *(
                        (
                            ResearchClaim(
                                claim="A deterministic executable prototype passed retained tests and rollback verification.",
                                source=f"implementation:{implementation['manifest_sha256']}",
                                source_quality=0.96,
                                corroboration=4,
                                direct_evidence=True,
                            ),
                        )
                        if implementation is not None
                        else ()
                    ),
                ),
            )
            external_research = (
                self._validate_research_evidence(research_evidence)
                if research_evidence is not None
                else None
            )
            if external_research is not None:
                fact_confidences = [
                    float(item["confidence"])
                    for item in external_research["verified_facts"]
                ]
                research_confidence = round(
                    sum(fact_confidences) / len(fact_confidences), 4
                )
                research_sources = tuple(
                    str(item["url"]) for item in external_research["sources"]
                )
                research_accepted = True
                research_payload = {
                    **external_research,
                    "accepted": True,
                    "confidence": research_confidence,
                    "external_fact_claims_verified": True,
                    "scope_verification_only": False,
                    "scope_evidence": {
                        "accepted": scope_verification.accepted,
                        "confidence": scope_verification.confidence,
                        "sources": list(scope_verification.evidence_sources),
                    },
                }
            else:
                research_confidence = scope_verification.confidence
                research_sources = tuple(scope_verification.evidence_sources)
                research_accepted = False
                research_payload = {
                    "claim": scope_verification.claim,
                    "accepted": False,
                    "confidence": scope_verification.confidence,
                    "sources": list(scope_verification.evidence_sources),
                    "conflicts": list(scope_verification.conflicts),
                    "rationale": scope_verification.rationale,
                    "external_fact_claims_verified": False,
                    "scope_verification_only": True,
                    "verified_facts": [],
                    "risks": [],
                    "unknowns": [
                        "Independent current web research evidence is missing."
                    ],
                    "recommended_constraints": [
                        "Run the controlled external research stage before release review."
                    ],
                    "search_calls": 0,
                    "request_count": 0,
                    "calculated_cost": 0.0,
                }
            knowledge.learn_fact(
                MemoryScope.PROJECT,
                tenant_id,
                safe_id,
                "verified-project-research",
                research_payload,
                confidence=research_confidence,
                sources=research_sources,
                tags=("research", "governance", "phase-28"),
                verified=research_accepted,
            )

            stage("wisdom_deliberation", 36)
            wisdom = WisdomEngine().decide(
                (
                    Strategy(
                        "controlled-staged-delivery",
                        0.92,
                        research_confidence,
                        0.95,
                        0.92,
                        0.94,
                        0.35,
                        0.55,
                        0.96,
                    ),
                    Strategy(
                        "direct-unreviewed-release",
                        0.65,
                        0.35,
                        0.15,
                        0.30,
                        0.18,
                        0.20,
                        0.25,
                        0.20,
                    ),
                    Strategy(
                        "defer-without-evidence",
                        0.20,
                        0.20,
                        1.0,
                        0.50,
                        0.85,
                        0.05,
                        0.10,
                        0.15,
                    ),
                )
            )
            wisdom_payload: dict[str, Any] = {
                "selected": wisdom.selected.name if wisdom.selected else None,
                "ranking": [list(item) for item in wisdom.ranking],
                "confidence": wisdom.confidence,
                "rationale": wisdom.rationale,
                "abstained": wisdom.abstained,
            }

            stage("government_review", 44)
            consolidated_risks = tuple(
                dict.fromkeys(
                    [*cognitive.risks, *manifest["review"].get("blocking_findings", [])]
                )
            )[:2]
            government = GovernmentRuntime("platform-owner")
            government_payload = government.review(
                GovernanceCase(
                    case_id=safe_id,
                    title=f"Governed execution for {selected_project}",
                    action="controlled_project_progression",
                    proposer=requested_by_id,
                    evidence=(
                        f"planning:{intake['planning_manifest_sha256']}",
                        f"cognitive:{cognitive.status.value}",
                        f"research-confidence:{research_confidence:.4f}",
                        f"wisdom:{wisdom_payload['selected']}",
                    ),
                    risks=consolidated_risks,
                    requires_owner_approval=(
                        cognitive.human_approval_required
                        or constitution.requires_human_approval
                    ),
                    metadata={
                        "authorization": external_processing_authorized,
                        "rollback_plan": "retain immutable evidence and create a new execution",
                        "irreversible": False,
                    },
                )
            )

            stage("ministry_routing", 52)
            ministries = build_default_ministry_registry()
            ministry_map = {
                "Architecture": "engineering",
                "Backend": "engineering",
                "Frontend": "engineering",
                "Security": "security",
                "Quality": "quality",
                "DevOps": "engineering",
            }
            ministry_payload = [
                {
                    "department": artifact["department"],
                    "ministry_id": ministry_map[artifact["department"]],
                    "ministry": ministries.require(ministry_map[artifact["department"]]).name,
                }
                for artifact in artifacts
            ]

            stage("workforce_execution", 64)
            workforce_payload = self._evaluate_workforce(
                safe_id,
                artifacts,
                staging / "workforce-ledger.jsonl",
                ministry_map,
                executed_tests_passed=(
                    bool(implementation["tests_passed"])
                    if implementation is not None
                    else False
                ),
                executed_security_reviewed=(
                    implementation is not None
                ),
            )

            stage("engineering_review", 74)
            organization = EngineeringOrganization()
            blueprint = organization.plan(selected_project, selected_objective)
            artifact_by_department = {
                artifact["department"]: artifact for artifact in artifacts
            }
            for deliverable in blueprint.deliverables:
                artifact = artifact_by_department[deliverable.department]
                model_output = artifact["model_output"]
                deliverable.evidence.update(
                    {
                        "passed_criteria": [
                            item["criterion"]
                            for item in model_output["technical_evidence"]
                        ],
                        "tests_passed": (
                            bool(implementation["tests_passed"])
                            if implementation is not None
                            else False
                        ),
                        "security_reviewed": (
                            implementation is not None
                        ),
                        "artifact_sha256": artifact["sha256"],
                    }
                )
            chief = organization.chief_review(blueprint)
            engineering_payload: dict[str, Any] = {
                "approved": chief.approved,
                "readiness_score": chief.readiness_score,
                "blocking_findings": list(chief.blocking_findings),
                "rework_plan": list(chief.rework_plan),
                "rationale": chief.rationale,
                "departments": [
                    {
                        "department": item.department,
                        "approved": item.approved,
                        "score": item.score,
                        "findings": list(item.findings),
                        "required_actions": list(item.required_actions),
                        "manager_id": item.manager_id,
                    }
                    for item in chief.department_decisions
                ],
            }

            stage("security_review", 82)
            security_target = (
                Path(implementation["source_directory"])
                if implementation is not None
                else source
            )
            security = SecurityPlatform(staging / "security-ledger.jsonl").assess(
                selected_project,
                security_target,
                authorization=True,
            )
            security_payload: dict[str, Any] = {
                "authorized": security.authorized,
                "risk_score": security.risk.score,
                "risk_level": security.risk.grade,
                "findings": [
                    {
                        "title": item.title,
                        "category": item.category,
                        "severity": item.severity.value,
                        "location": item.location,
                        "evidence": item.evidence,
                        "remediation": list(item.remediation),
                        "verification": list(item.verification),
                    }
                    for item in security.findings
                ],
                "remediation": list(security.remediation_plan),
                "verification": list(security.verification_plan),
            }

            stage("integration_review", 90)
            integration_artifacts: dict[str, dict[str, Any]] = {}
            for artifact in artifacts:
                model_output = artifact["model_output"]
                integration_artifacts[artifact["department"]] = {
                    "tests_passed": (
                        bool(implementation["tests_passed"])
                        if implementation is not None
                        else False
                    ),
                    "security_reviewed": (
                        implementation is not None
                        and not any(
                            item.severity.value in {"critical", "high"}
                            for item in security.findings
                        )
                    ),
                    "documentation_complete": bool(model_output["summary"]),
                    "rollback_tested": (
                        bool(implementation["rollback_tested"])
                        if implementation is not None
                        else False
                    ),
                    "acceptance_proven": artifact["acceptance_coverage"] == 1.0,
                    "interface_conflicts": False,
                    "security_regression": any(
                        item.severity.value in {"critical", "high"}
                        for item in security.findings
                    ),
                }
            integration_payload: dict[str, Any] = MasterOrchestrator(
                organization
            ).delivery_review(integration_artifacts)

            stage("release_review", 96)
            release_blockers = list(
                dict.fromkeys(
                    [
                        *constitution.violations,
                        *constitution.conditions,
                        *([] if research_accepted else ["research verification failed"]),
                        *(
                            []
                            if government_payload["verdict"] == "approved"
                            else ["government review did not approve progression"]
                        ),
                        *engineering_payload["blocking_findings"],
                        *integration_payload["integration"]["findings"],
                        *[
                            f"definition-of-done:{department}:{missing}"
                            for department, verdict in integration_payload["definition_of_done"].items()
                            for missing in verdict["missing_evidence"]
                        ],
                        *[
                            f"security:{item['severity']}:{item['title']}"
                            for item in security_payload["findings"]
                            if item["severity"] in {"critical", "high"}
                        ],
                    ]
                )
            )
            release_blockers.extend(
                self._implementation_scope_blockers(
                    selected_objective, implementation
                )
            )
            release_blockers = list(dict.fromkeys(release_blockers))
            owner_approval_required = bool(
                government_payload["owner_approval_required"]
            )
            owner_approved = bool(government_payload["owner_approved"])
            if owner_approval_required and not owner_approved:
                release_blockers.append("owner approval is required")
            release_approved = not release_blockers
            release_payload = {
                "approved": release_approved,
                "status": "approved" if release_approved else "rework_required",
                "owner_approval_required": owner_approval_required,
                "owner_approved": owner_approved,
                "blocking_findings": release_blockers,
                "rework_plan": self._rework_plan(release_blockers),
                "claim_boundary": (
                    "Approval applies only to evidence actually executed and retained; "
                    "model statements are not treated as test or security receipts."
                ),
            }

            package = self._create_delivery_package(
                staging,
                selected_project,
                selected_objective,
                artifacts,
                release_payload,
                implementation=implementation,
                plan_review=plan_review_evidence,
            )
            duration = round(time.monotonic() - started, 6)
            final_manifest = {
                "schema_version": 1,
                "phase": 28,
                "mode": "full-governed-project-cycle",
                "execution_id": safe_id,
                "project": selected_project,
                "objective": selected_objective,
                "tenant_id": tenant_id,
                "requested_by_id": requested_by_id,
                "intake": intake,
                "cognitive_review": cognitive_payload,
                "constitutional_review": constitution_payload,
                "research_verification": research_payload,
                "external_research": external_research,
                "wisdom_deliberation": wisdom_payload,
                "government_review": government_payload,
                "ministry_routing": ministry_payload,
                "workforce": workforce_payload,
                "engineering_review": engineering_payload,
                "security_review": security_payload,
                "integration_review": integration_payload,
                "release_review": release_payload,
                "delivery_package": package,
                "implementation": implementation,
                "plan_review": dict(plan_review_evidence) if plan_review_evidence is not None else None,
                "source_planning": {
                    "directory": str(source),
                    "manifest_sha256": intake["planning_manifest_sha256"],
                    "provider": manifest["provider"],
                    "model": manifest["model"],
                    "requests_count": manifest["requests_count"],
                    "calculated_cost": manifest["calculated_cost"],
                    "immutable": True,
                },
                "summary": {
                    "status": release_payload["status"],
                    "approved": release_approved,
                    "readiness_score": engineering_payload["readiness_score"],
                    "blocking_findings": release_payload["blocking_findings"],
                    "rework_plan": release_payload["rework_plan"],
                    "workers_evaluated": len(workforce_payload),
                    "workers_retraining": sum(
                        item["employment_state"] == "retraining"
                        for item in workforce_payload
                    ),
                    "workers_supervised": sum(
                        item["employment_state"] == "supervised"
                        for item in workforce_payload
                    ),
                    "duration_seconds": duration,
                },
                "proof": {
                    "all_governance_layers_executed": True,
                    "all_six_departments_reviewed": len(artifacts) == 6,
                    "workforce_evaluated": len(workforce_payload) == 6,
                    "training_assessments_recorded": all(
                        "training" in item for item in workforce_payload
                    ),
                    "model_claims_used_as_execution_proof": False,
                    "fallback_used": False,
                    "production_modified": False,
                    "source_planning_modified": False,
                    "pre_implementation_plan_approved": bool(
                        plan_review_evidence is not None
                        and plan_review_evidence.get("approved") is True
                    ),
                },
            }
            self._atomic_write_text(
                staging / "manifest.json", self._canonical_json(final_manifest)
            )
            self._atomic_write_text(
                staging / "REPORT.md", self._report(final_manifest)
            )
            os.replace(staging, destination)
            stage("completed", 100)
            return {
                "success": True,
                "status": release_payload["status"],
                "execution_id": safe_id,
                "output_directory": str(destination),
                "manifest_path": str(destination / "manifest.json"),
                "report_path": str(destination / "REPORT.md"),
                "approved": release_approved,
                "readiness_score": engineering_payload["readiness_score"],
                "blocking_findings": release_payload["blocking_findings"],
                "rework_plan": release_payload["rework_plan"],
                "plan_review": dict(plan_review_evidence) if plan_review_evidence is not None else None,
                "governance": {
                    "cognitive_status": cognitive_payload["status"],
                    "councils_verdict": government_payload["verdict"],
                    "research_verified": research_accepted,
                    "research_sources": len(
                        external_research["sources"]
                        if external_research is not None
                        else []
                    ),
                    "wisdom_strategy": wisdom_payload["selected"],
                    "owner_approval_required": owner_approval_required,
                },
                "workforce": workforce_payload,
                "delivery_package": package,
                "implementation": implementation,
                "duration_seconds": duration,
                "fallback_used": False,
                "production_modified": False,
                "model_claims_used_as_execution_proof": False,
            }
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @classmethod
    def _validate_planning_source(
        cls, source: Path
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        manifest_path = source / "manifest.json"
        if (
            not source.is_dir()
            or source.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.is_symlink()
        ):
            raise FullProjectCycleValidationError(
                "planning source is missing or unsafe"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FullProjectCycleValidationError(
                "planning manifest is invalid"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("provider") != "openai":
            raise FullProjectCycleValidationError(
                "planning source must be an OpenAI controlled execution"
            )
        if manifest.get("fallback_used") is not False:
            raise FullProjectCycleValidationError("fallback planning is forbidden")
        if manifest.get("production_modified") is not False:
            raise FullProjectCycleValidationError(
                "planning source must not modify production"
            )
        records = manifest.get("artifacts")
        if not isinstance(records, list) or len(records) != 6:
            raise FullProjectCycleValidationError(
                "planning source must contain exactly six departments"
            )
        artifacts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise FullProjectCycleValidationError("artifact record is invalid")
            relative = Path(str(record.get("path") or ""))
            path = cls._contained(source, source / relative)
            digest = str(record.get("sha256") or "")
            if (
                not path.is_file()
                or path.is_symlink()
                or cls._sha256(path) != digest
            ):
                raise FullProjectCycleValidationError(
                    "planning artifact is missing or has a hash mismatch"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            department = str(payload.get("department") or "")
            model_output = payload.get("model_output")
            if (
                not department
                or department in seen
                or not isinstance(model_output, Mapping)
                or payload.get("schema_valid") is not True
                or float(payload.get("acceptance_coverage") or 0.0) != 1.0
            ):
                raise FullProjectCycleValidationError(
                    "planning artifact schema or acceptance coverage is invalid"
                )
            seen.add(department)
            artifacts.append(
                {
                    "department": department,
                    "path": str(relative),
                    "sha256": digest,
                    "schema_valid": True,
                    "acceptance_coverage": 1.0,
                    "attempts": int(payload.get("attempts") or 0),
                    "model_output": dict(model_output),
                }
            )
        expected = set(EngineeringOrganization.DEFAULT_DEPARTMENTS)
        if seen != expected:
            raise FullProjectCycleValidationError(
                "planning department set does not match AIOS engineering organization"
            )
        return manifest, sorted(artifacts, key=lambda item: item["department"])

    @staticmethod
    def _evaluate_workforce(
        project_id: str,
        artifacts: list[dict[str, Any]],
        ledger_path: Path,
        ministry_map: Mapping[str, str],
        *,
        executed_tests_passed: bool,
        executed_security_reviewed: bool,
    ) -> list[dict[str, Any]]:
        careers = CareerSystem()
        academy = Academy()
        health = OperationalHealthInstitute()
        runtime = WorkerRuntime(careers, academy, health, ledger_path)
        results: list[dict[str, Any]] = []
        for artifact in artifacts:
            department = artifact["department"]
            employee_id = f"{department.lower()}-specialist"
            skill = department.lower()
            careers.hire(
                EmployeeRecord(
                    employee_id=employee_id,
                    role=f"{department} Specialist",
                    ministry_id=ministry_map[department],
                    skills={skill, "evidence", "project-delivery"},
                )
            )
            course_id = f"{skill}-evidence-recertification"
            academy.register_course(
                Course(
                    course_id,
                    f"{department} evidence and release discipline",
                    (skill, "evidence", "policy-compliance"),
                    passing_score=80.0,
                )
            )
            criteria = tuple(
                str(item["criterion"])
                for item in artifact["model_output"]["technical_evidence"]
            )
            request = WorkRequest(
                project_id,
                f"Validate {department} project artifact",
                (skill,),
                ministry_map[department],
                criteria,
                risk="high" if department in {"Security", "DevOps"} else "normal",
            )
            assignment = runtime.assign(
                request, reviewer_id=f"{skill}-manager"
            )
            runtime.start(assignment.request.id)
            runtime.submit(
                assignment.request.id,
                {
                    "passed_criteria": list(criteria),
                    "artifact_sha256": artifact["sha256"],
                },
            )
            tests_passed = bool(executed_tests_passed)
            security_required = department in {"Backend", "Security", "DevOps"}
            security_reviewed = bool(executed_security_reviewed)
            approved = tests_passed and (
                security_reviewed or not security_required
            )
            defects: list[str] = []
            if not tests_passed:
                defects.append("executed department test receipt is missing")
            if security_required and not security_reviewed:
                defects.append("executed security review receipt is missing")
            runtime.review(
                assignment.request.id,
                approved=approved,
                defects=tuple(defects),
            )
            quality = 100.0 - (18.0 if not tests_passed else 0.0) - (
                12.0 if security_required and not security_reviewed else 0.0
            )
            incidents = tuple(defects)
            report = health.observe(
                WorkerObservation(
                    worker_id=employee_id,
                    project_id=project_id,
                    quality=quality,
                    reliability=95.0 if artifact["attempts"] <= 1 else 82.0,
                    collaboration=90.0,
                    policy_compliance=96.0,
                    learning=86.0,
                    incidents=incidents,
                )
            )
            record = careers.get(employee_id)
            training_score = max(0.0, min(100.0, quality))
            certification = academy.assess(
                employee_id, course_id, training_score
            )
            if not approved:
                careers.restrict(
                    employee_id,
                    "delivery evidence requires retraining and supervised rework",
                    EmploymentState.RETRAINING,
                )
                if certification.passed:
                    record.certifications.add(course_id)
                    careers.restrict(
                        employee_id,
                        "recertified; supervised execution required until successful rework",
                        EmploymentState.SUPERVISED,
                    )
            elif certification.passed:
                record.certifications.add(course_id)
            results.append(
                {
                    "worker_id": employee_id,
                    "role": record.role,
                    "department": department,
                    "ministry_id": record.ministry_id,
                    "employment_state": record.state.value,
                    "assignment_state": assignment.state.value,
                    "success_count": record.success_count,
                    "failure_count": record.failure_count,
                    "quality": report.performance,
                    "operational_health": report.operational_health,
                    "trust": report.trust,
                    "learning": report.learning,
                    "recommendation": report.recommendation,
                    "restrictions": list(report.restrictions),
                    "warnings": list(record.warnings),
                    "certifications": sorted(record.certifications),
                    "training": {
                        "course_id": course_id,
                        "score": certification.score,
                        "passed": certification.passed,
                    },
                    "artifact_sha256": artifact["sha256"],
                }
            )
        return sorted(results, key=lambda item: item["department"])

    @classmethod
    def _create_delivery_package(
        cls,
        staging: Path,
        project: str,
        objective: str,
        artifacts: list[dict[str, Any]],
        release: Mapping[str, Any],
        *,
        implementation: Mapping[str, Any] | None,
        plan_review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        package_dir = staging / "delivery-package"
        package_dir.mkdir(mode=0o700)
        files: list[dict[str, str]] = []
        overview = [
            f"# {project}",
            "",
            "## Objective",
            "",
            objective,
            "",
            "## Release status",
            "",
            f"- Status: `{release['status']}`",
            f"- Approved: `{str(release['approved']).lower()}`",
            "",
            "## Blocking findings",
            "",
            *([f"- {item}" for item in release.get("blocking_findings") or []] or ["- None"]),
            "",
            "## Rework plan",
            "",
            *([f"- {item}" for item in release.get("rework_plan") or []] or ["- None"]),
            "",
        ]
        cls._atomic_write_text(package_dir / "README.md", "\n".join(overview))
        files.append(
            {"path": "delivery-package/README.md", "sha256": cls._sha256(package_dir / "README.md")}
        )
        for artifact in artifacts:
            name = artifact["department"].lower()
            output = artifact["model_output"]
            lines = [
                f"# {artifact['department']} Delivery",
                "",
                output["summary"],
                "",
                "## Implementation plan",
                "",
                *[f"- {item}" for item in output["implementation_plan"]],
                "",
                "## Technical evidence",
                "",
            ]
            for evidence in output["technical_evidence"]:
                lines.extend(
                    [
                        f"### {evidence['criterion']}",
                        "",
                        evidence["evidence"],
                        "",
                        f"Verification: {evidence['verification']}",
                        "",
                    ]
                )
            lines.extend(
                [
                    "## Risks",
                    "",
                    *[
                        f"- {item['risk']} — Mitigation: {item['mitigation']}"
                        for item in output["risks"]
                    ],
                    "",
                    "## Evidence state",
                    "",
                    f"- Tests passed: `{str(output['tests_passed']).lower()}`",
                    f"- Security reviewed: `{str(output['security_reviewed']).lower()}`",
                    "",
                ]
            )
            path = package_dir / f"{name}.md"
            cls._atomic_write_text(path, "\n".join(lines))
            files.append(
                {"path": f"delivery-package/{path.name}", "sha256": cls._sha256(path)}
            )
        if plan_review is not None:
            plan_review_path = package_dir / "plan-review.json"
            cls._atomic_write_text(
                plan_review_path, cls._canonical_json(dict(plan_review))
            )
            files.append(
                {
                    "path": "delivery-package/plan-review.json",
                    "sha256": cls._sha256(plan_review_path),
                }
            )

        executable_files: list[dict[str, str]] = []
        if implementation is not None:
            implementation_root = Path(
                str(implementation["output_directory"])
            ).resolve(strict=True)
            source_root = (implementation_root / "source").resolve(strict=True)
            if implementation_root not in source_root.parents or not source_root.is_dir():
                raise FullProjectCycleValidationError(
                    "implementation source directory is unsafe or unavailable"
                )
            for source_file in sorted(source_root.rglob("*")):
                if not source_file.is_file() or source_file.is_symlink():
                    continue
                resolved = source_file.resolve(strict=True)
                if source_root not in resolved.parents:
                    raise FullProjectCycleValidationError(
                        "implementation source file escapes the source root"
                    )
                relative = resolved.relative_to(source_root)
                destination_file = package_dir / "source" / relative
                destination_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(resolved, destination_file)
                record = {
                    "path": f"delivery-package/source/{relative.as_posix()}",
                    "sha256": cls._sha256(destination_file),
                }
                files.append(record)
                executable_files.append(record)
            for name in (
                "project-prototype.zip",
                "manifest.json",
                "REPORT.md",
                "TEST_REPORT.json",
            ):
                source_file = implementation_root / name
                if source_file.is_file() and not source_file.is_symlink():
                    destination_file = package_dir / f"prototype-{name}"
                    shutil.copy2(source_file, destination_file)
                    record = {
                        "path": f"delivery-package/{destination_file.name}",
                        "sha256": cls._sha256(destination_file),
                    }
                    files.append(record)
                    executable_files.append(record)

        package_manifest = {
            "schema_version": 1,
            "project": project,
            "objective": objective,
            "status": release["status"],
            "approved": release["approved"],
            "files": files,
            "source_type": "validated-engineering-delivery-package",
            "contains_executable_product": implementation is not None,
            "executable_scope": (
                str(implementation.get("executable_scope") or "controlled-full-stack-web-prototype")
                if implementation is not None
                else None
            ),
            "executable_files": executable_files,
            "claim_boundary": (
                "This package contains tested executable source and governed evidence within the proven implementation scope. "
                "It is not represented as deployed production infrastructure or as an unproven external integration."
                if implementation is not None
                else "This package contains governed implementation specifications and evidence. "
                "It is not represented as deployed executable product source."
            ),
        }
        cls._atomic_write_text(
            package_dir / "manifest.json", cls._canonical_json(package_manifest)
        )
        manifest_hash = cls._sha256(package_dir / "manifest.json")
        return {
            "path": "delivery-package",
            "manifest": "delivery-package/manifest.json",
            "manifest_sha256": manifest_hash,
            "files_count": len(files) + 1,
            "contains_executable_product": implementation is not None,
            "executable_scope": package_manifest["executable_scope"],
        }

    @classmethod
    def _validate_research_evidence(
        cls, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        required = {
            "provider",
            "model",
            "research_question",
            "summary",
            "verified_facts",
            "risks",
            "unknowns",
            "recommended_constraints",
            "sources",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "calculated_cost",
            "tool_cost",
            "total_duration",
            "search_calls",
            "raw_prompt_stored",
            "raw_response_stored",
            "authorization_header_stored",
            "fallback_used",
            "production_modified",
        }
        payload = dict(evidence)
        if not required.issubset(payload):
            raise FullProjectCycleValidationError(
                "external research evidence is incomplete"
            )
        if (
            payload.get("provider") != "openai"
            or int(payload.get("search_calls") or 0) != 1
            or payload.get("fallback_used") is not False
            or payload.get("production_modified") is not False
            or payload.get("raw_prompt_stored") is not False
            or payload.get("raw_response_stored") is not False
            or payload.get("authorization_header_stored") is not False
        ):
            raise FullProjectCycleValidationError(
                "external research evidence violates the controlled research contract"
            )
        sources = payload.get("sources")
        facts = payload.get("verified_facts")
        if not isinstance(sources, list) or len(sources) < 2:
            raise FullProjectCycleValidationError(
                "external research requires at least two sources"
            )
        domains = {
            str(item.get("domain") or "").lower()
            for item in sources
            if isinstance(item, Mapping)
        }
        if len(domains - {""}) < 2:
            raise FullProjectCycleValidationError(
                "external research sources are not independent"
            )
        observed_urls = {
            str(item.get("url") or "")
            for item in sources
            if isinstance(item, Mapping)
        }
        if not isinstance(facts, list) or len(facts) < 2:
            raise FullProjectCycleValidationError(
                "external research requires at least two verified facts"
            )
        for fact in facts:
            if not isinstance(fact, Mapping):
                raise FullProjectCycleValidationError(
                    "external research fact is invalid"
                )
            urls = fact.get("source_urls")
            confidence = float(fact.get("confidence") or -1.0)
            if (
                not isinstance(urls, list)
                or not urls
                or any(str(url) not in observed_urls for url in urls)
                or not 0.0 <= confidence <= 1.0
            ):
                raise FullProjectCycleValidationError(
                    "external research fact is not attributable"
                )
        return payload

    @classmethod
    def _validate_implementation_source(
        cls,
        directory: Path,
        *,
        planning_manifest_sha256: str,
    ) -> dict[str, Any]:
        manifest_path = directory / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FullProjectCycleValidationError(
                "implementation manifest is invalid"
            ) from exc
        if (
            manifest.get("mode") != "controlled-full-stack-prototype"
            or manifest.get("provider") != "openai"
            or manifest.get("fallback_used") is not False
            or manifest.get("production_modified") is not False
            or (manifest.get("tests") or {}).get("passed") is not True
            or manifest.get("rollback_tested") is not True
            or (manifest.get("planning") or {}).get("manifest_sha256")
            != planning_manifest_sha256
        ):
            raise FullProjectCycleValidationError(
                "implementation evidence does not satisfy the controlled prototype contract"
            )
        source = (directory / "source").resolve(strict=True)
        if directory not in source.parents or not source.is_dir():
            raise FullProjectCycleValidationError(
                "implementation source directory is unsafe"
            )
        files = manifest.get("files")
        if not isinstance(files, Mapping) or not files:
            raise FullProjectCycleValidationError(
                "implementation file manifest is missing"
            )
        for relative, expected in files.items():
            path = cls._contained(source, source / str(relative))
            if (
                not path.is_file()
                or path.is_symlink()
                or cls._sha256(path) != str(expected)
            ):
                raise FullProjectCycleValidationError(
                    "implementation source hash mismatch"
                )
        archive = directory / "project-prototype.zip"
        if (
            not archive.is_file()
            or archive.is_symlink()
            or cls._sha256(archive) != str(manifest.get("archive_sha256") or "")
        ):
            raise FullProjectCycleValidationError(
                "implementation rollback archive is invalid"
            )
        application_type = str(manifest.get("application_type") or "web_application")
        test_checks = dict((manifest.get("tests") or {}).get("checks") or {})
        capabilities = {
            "authentication": bool(test_checks.get("member_authentication")),
            "member_directory": bool(test_checks.get("member_directory")),
            "realtime_communications": bool(test_checks.get("webrtc_runtime_present"))
            and bool(test_checks.get("signaling_round_trip")),
            "csrf": bool(test_checks.get("csrf_enforced")),
            "persistence": bool(
                test_checks.get("sqlite_persistence")
                or test_checks.get("api_create_read_delete")
            ),
            "native_mobile": False,
            "payments": False,
            "production_deployment": False,
            "external_integration": False,
            "public_realtime_relay": False,
        }
        return {
            "output_directory": str(directory),
            "source_directory": str(source),
            "manifest_path": str(manifest_path),
            "manifest_sha256": cls._sha256(manifest_path),
            "archive_path": str(archive),
            "archive_sha256": cls._sha256(archive),
            "mode": manifest["mode"],
            "application_type": application_type,
            "tests_passed": True,
            "rollback_tested": True,
            "requests_count": int(manifest.get("requests_count") or 1),
            "input_tokens": int(manifest.get("input_tokens") or 0),
            "output_tokens": int(manifest.get("output_tokens") or 0),
            "total_tokens": int(manifest.get("total_tokens") or 0),
            "calculated_cost": float(manifest.get("calculated_cost") or 0.0),
            "total_duration": float(manifest.get("total_duration") or 0.0),
            "executable_scope": (
                "realtime-communications-web-application"
                if application_type == "realtime_communications"
                else "controlled-full-stack-web-prototype"
            ),
            "capabilities": capabilities,
            "production_modified": False,
            "fallback_used": False,
        }

    @staticmethod
    def _implementation_scope_blockers(
        objective: str, implementation: Mapping[str, Any] | None
    ) -> list[str]:
        if implementation is None:
            return ["executable implementation evidence is missing"]
        lowered = objective.lower()
        capabilities = dict(implementation.get("capabilities") or {})
        requested = {
            "production-deployment": (
                "production deployment", "production backend", "hosted production",
                "public deployment", "نشر إنتاجي", "استضافة إنتاجية",
            ),
            "authentication": (
                "login", "authentication", "account", "password",
                "تسجيل دخول", "حساب", "كلمة مرور", "مسجلين", "الأعضاء المسجلين",
            ),
            "payments": ("payment", "billing", "checkout", "دفع", "فوترة"),
            "native-mobile": (
                "mobile app", "android", "ios", "تطبيق موبايل", "تطبيق هاتف",
                "أندرويد", "اندرويد", "آيفون", "ايفون",
            ),
            "external-integration": (
                "third-party integration", "webhook", "external integration",
                "تكامل خارجي", "طرف ثالث",
            ),
            "realtime-communications": (
                "webrtc", "video call", "voice call", "audio call", "calling",
                "مكالم", "اتصال", "اتصالات", "صوت", "فيديو",
            ),
        }
        capability_map = {
            "production-deployment": "production_deployment",
            "authentication": "authentication",
            "payments": "payments",
            "native-mobile": "native_mobile",
            "external-integration": "external_integration",
            "realtime-communications": "realtime_communications",
        }
        blockers: list[str] = []
        for capability, terms in requested.items():
            if any(
                FullProjectCycle._contains_requested_term(lowered, term)
                for term in terms
            ) and not bool(capabilities.get(capability_map[capability])):
                blockers.append(
                    f"implementation scope does not prove requested {capability} runtime capability"
                )
        if implementation.get("application_type") == "realtime_communications" and not bool(
            capabilities.get("public_realtime_relay")
        ):
            blockers.append(
                "realtime application requires audited HTTPS and STUN/TURN relay configuration before public-internet release"
            )
        return blockers

    @staticmethod
    def _negative_scope_spans(text: str) -> tuple[tuple[int, int], ...]:
        markers = (
            "must not require",
            "must not include",
            "does not require",
            "does not include",
            "do not require",
            "do not include",
            "doesn't require",
            "is not required to include",
            "without requiring",
            "without",
            "no need for",
            "exclude",
            "excludes",
            "excluded",
            "excluding",
            "لا يتطلب",
            "لا يحتاج",
            "لا يشمل",
            "لن يتطلب",
            "دون",
            "بدون",
            "باستثناء",
        )
        spans: list[tuple[int, int]] = []
        for marker in markers:
            start = 0
            while True:
                index = text.find(marker, start)
                if index < 0:
                    break
                boundary_candidates = [
                    text.find(symbol, index) for symbol in (".", "!", "?", ";", "\n")
                ]
                boundaries = [value for value in boundary_candidates if value >= 0]
                end = min(boundaries) if boundaries else min(len(text), index + 320)
                spans.append((index, min(len(text), max(end, index + len(marker)))))
                start = index + len(marker)
        return tuple(spans)

    @classmethod
    def _contains_requested_term(cls, text: str, term: str) -> bool:
        spans = cls._negative_scope_spans(text)
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                return False
            if not any(left <= index <= right for left, right in spans):
                return True
            start = index + len(term)

    @classmethod
    def _governance_objective(cls, objective: str) -> str:
        """Remove explicitly excluded capabilities from rule-based risk review."""
        spans = sorted(cls._negative_scope_spans(objective.lower()))
        if not spans:
            return objective
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        parts: list[str] = []
        cursor = 0
        for start, end in merged:
            parts.append(objective[cursor:start])
            parts.append(" bounded local prototype scope ")
            cursor = end
        parts.append(objective[cursor:])
        normalized = " ".join("".join(parts).split())
        return normalized or "Build a bounded local prototype."

    @classmethod
    def _risk_level(cls, objective: str) -> str:
        lowered = objective.lower()
        if any(
            cls._contains_requested_term(lowered, token)
            for token in (
                "production",
                "payment",
                "medical",
                "financial",
                "security",
                "delete",
                "الإنتاج",
                "دفع",
                "طبي",
                "مالي",
                "أمني",
                "حذف",
            )
        ):
            return "high"
        return "medium"

    @classmethod
    def _security_sensitive(cls, objective: str) -> bool:
        lowered = objective.lower()
        return any(
            cls._contains_requested_term(lowered, token)
            for token in (
                "authentication",
                "password",
                "payment",
                "security",
                "بيانات شخصية",
                "كلمة مرور",
                "دفع",
                "أمن",
            )
        )

    @staticmethod
    def _rework_plan(blockers: list[str]) -> list[str]:
        plans: list[str] = []
        for blocker in blockers:
            lowered = blocker.lower()
            if "test" in lowered:
                plans.append("Execute the required test plan and attach immutable receipts.")
            elif "security" in lowered:
                plans.append("Complete the authorized security review and verify remediation.")
            elif "owner approval" in lowered:
                plans.append("Request explicit Owner approval with the complete evidence package.")
            elif "research" in lowered:
                plans.append("Add independent evidence sources and repeat research verification.")
            elif "rollback" in lowered:
                plans.append("Create and verify a rollback procedure.")
            else:
                plans.append(f"Resolve and re-review: {blocker}")
        return list(dict.fromkeys(plans))

    @staticmethod
    def _prepare_root(output_root: str | Path) -> Path:
        raw = Path(output_root)
        if not raw.is_absolute():
            raise ValueError("output_root must be absolute")
        raw.mkdir(parents=True, exist_ok=True, mode=0o700)
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
            raise ValueError("path escapes allowed root")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"

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
    def _report(manifest: Mapping[str, Any]) -> str:
        summary = manifest["summary"]
        release = manifest["release_review"]
        return (
            "# Phase 28 Full Governed Project Cycle\n\n"
            f"- Project: `{manifest['project']}`\n"
            f"- Status: `{summary['status']}`\n"
            f"- Approved: `{str(summary['approved']).lower()}`\n"
            f"- Readiness: `{summary['readiness_score']}`\n"
            f"- Workers evaluated: `{summary['workers_evaluated']}`\n"
            f"- Workers retraining: `{summary['workers_retraining']}`\n"
            f"- Workers supervised: `{summary['workers_supervised']}`\n"
            f"- Duration: `{summary['duration_seconds']} seconds`\n"
            "- Fallback used: `false`\n"
            "- Production modified: `false`\n"
            "- Model claims used as execution proof: `false`\n\n"
            "## Blocking findings\n\n"
            + "\n".join(
                f"- {item}" for item in (release["blocking_findings"] or ["None"])
            )
            + "\n\n## Rework plan\n\n"
            + "\n".join(
                f"- {item}" for item in (release["rework_plan"] or ["None"])
            )
            + "\n"
        )
