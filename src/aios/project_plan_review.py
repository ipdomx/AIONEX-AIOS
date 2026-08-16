from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .government import GovernanceCase, GovernmentRuntime
from .intelligence import Strategy, WisdomEngine
from .ministries import MinistryAssignment, build_default_ministry_registry
from .organization import EngineeringOrganization


class GovernedPlanReviewError(ValueError):
    """The retained six-department planning evidence is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class GovernedPlanReviewResult:
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    manifest_path: Path
    report_path: Path
    payload: dict[str, Any]


class GovernedProjectPlanReviewer:
    """Review provider planning evidence before implementation is allowed to begin."""

    DEPARTMENTS = ("Architecture", "Backend", "Frontend", "Security", "Quality", "DevOps")
    MINISTRY_MAP = {
        "Architecture": "engineering",
        "Backend": "engineering",
        "Frontend": "engineering",
        "Security": "security",
        "Quality": "quality",
        "DevOps": "engineering",
    }

    def review(
        self,
        *,
        project: str,
        objective: str,
        planning_directory: str | Path,
        output_root: str | Path,
        requested_by_id: str,
    ) -> GovernedPlanReviewResult:
        planning = Path(planning_directory).resolve(strict=True)
        manifest_path = planning / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GovernedPlanReviewError("planning manifest is invalid") from exc
        records = manifest.get("artifacts")
        if (
            manifest.get("provider") != "openai"
            or manifest.get("fallback_used") is not False
            or not isinstance(records, list)
            or len(records) != len(self.DEPARTMENTS)
        ):
            raise GovernedPlanReviewError("plan review requires six retained OpenAI department artifacts")

        record_by_department = {
            str(item.get("department")): item
            for item in records
            if isinstance(item, Mapping)
        }
        if set(record_by_department) != set(self.DEPARTMENTS):
            raise GovernedPlanReviewError("planning departments do not match the governed organization")

        organization = EngineeringOrganization()
        blueprint = organization.plan(project, objective)
        department_payloads: list[dict[str, Any]] = []
        risk_labels: list[str] = []
        for deliverable in blueprint.deliverables:
            record = record_by_department[deliverable.department]
            relative = Path(str(record.get("path") or ""))
            artifact_path = self._contained(planning, planning / relative)
            if not artifact_path.is_file() or artifact_path.is_symlink():
                raise GovernedPlanReviewError(f"missing planning artifact: {deliverable.department}")
            if self._sha256(artifact_path) != str(record.get("sha256") or ""):
                raise GovernedPlanReviewError(f"planning artifact hash mismatch: {deliverable.department}")
            try:
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise GovernedPlanReviewError(f"planning artifact JSON is invalid: {deliverable.department}") from exc
            output = artifact.get("model_output") or {}
            implementation_plan = output.get("implementation_plan") or []
            risks = output.get("risks") or []
            schema_valid = record.get("schema_valid") is True and artifact.get("schema_valid") is True
            coverage = float(record.get("acceptance_coverage") or 0.0)
            risks_valid = bool(risks) and all(
                isinstance(item, Mapping)
                and str(item.get("risk") or "").strip()
                and str(item.get("mitigation") or "").strip()
                for item in risks
            )
            deliverable.evidence.update(
                {
                    "passed_criteria": list(deliverable.acceptance_criteria) if coverage >= 1.0 else [],
                    "plan_schema_valid": schema_valid,
                    "implementation_plan_complete": isinstance(implementation_plan, list) and len(implementation_plan) >= 2,
                    "risks_documented": risks_valid,
                    "planning_artifact_sha256": self._sha256(artifact_path),
                }
            )
            for item in risks[:3] if isinstance(risks, list) else []:
                if isinstance(item, Mapping) and str(item.get("risk") or "").strip():
                    risk_labels.append(str(item["risk"])[:240])
            department_payloads.append(
                {
                    "department": deliverable.department,
                    "artifact_sha256": self._sha256(artifact_path),
                    "schema_valid": schema_valid,
                    "acceptance_coverage": coverage,
                    "implementation_steps": len(implementation_plan) if isinstance(implementation_plan, list) else 0,
                    "risks_documented": len(risks) if isinstance(risks, list) else 0,
                }
            )

        chief = organization.chief_plan_review(blueprint)
        ministries = build_default_ministry_registry()
        manager_by_department = {
            decision.department: decision.manager_id
            for decision in chief.department_decisions
        }
        ministry_payload: list[dict[str, Any]] = []
        for item in department_payloads:
            department = str(item["department"])
            ministry_id = self.MINISTRY_MAP[department]
            ministry = ministries.require(ministry_id)
            ministries.assign(
                MinistryAssignment(
                    ministry_id=ministry_id,
                    project_id=project,
                    worker_ids=(manager_by_department[department],),
                    objective=(
                        f"Review and govern the {department} implementation plan "
                        f"before build execution: {objective[:400]}"
                    ),
                )
            )
            ministry_payload.append(
                {
                    "department": department,
                    "ministry_id": ministry_id,
                    "ministry": ministry.name,
                    "mission": ministry.mission,
                    "manager_role": ministry.manager_role,
                    "state": ministries.state(ministry_id).value,
                    "assignment_accepted": True,
                    "assigned_manager_id": manager_by_department[department],
                }
            )
        if chief.approved:
            strategies = (
                Strategy("implement-reviewed-plan", 0.94, 0.96, 0.96, 0.94, 0.94, 0.35, 0.45, 0.95),
                Strategy("rework-plan", 0.40, 0.90, 1.0, 0.92, 0.96, 0.20, 0.30, 0.80),
            )
        else:
            strategies = (
                Strategy("rework-plan", 0.94, 0.96, 1.0, 0.96, 0.98, 0.15, 0.25, 0.95),
                Strategy("implement-reviewed-plan", 0.30, 0.40, 0.80, 0.55, 0.50, 0.40, 0.70, 0.45),
            )
        wisdom = WisdomEngine().decide(strategies)
        plan_digest = self._sha256(manifest_path)
        government = GovernmentRuntime("platform-owner").review(
            GovernanceCase(
                case_id=f"plan-{plan_digest[:24]}",
                title=f"Implementation plan review for {project}",
                action="approve_governed_project_implementation_plan",
                proposer=requested_by_id,
                evidence=(
                    f"planning-manifest:{plan_digest}",
                    f"chief-plan-review:{str(chief.approved).lower()}",
                    f"wisdom:{wisdom.selected.name if wisdom.selected else 'abstained'}",
                    "six-department-plan-reviewed",
                    "ministry-routing-complete",
                ),
                risks=tuple(dict.fromkeys(risk_labels))[:2],
                requires_owner_approval=False,
                metadata={
                    "authorization": True,
                    "rollback_plan": "return the planning package for rework before implementation",
                    "irreversible": False,
                },
            )
        )
        blockers = list(chief.blocking_findings)
        if wisdom.selected is None or wisdom.selected.name != "implement-reviewed-plan":
            blockers.append("wisdom council requires plan rework before implementation")
        if government["verdict"] != "approved":
            blockers.append("government councils did not approve implementation progression")
        blockers = list(dict.fromkeys(blockers))
        rework = list(chief.rework_plan)
        if blockers and not rework:
            rework.append("revise the implementation plan and submit it through the governed plan review again")
        approved = not blockers

        root = Path(output_root)
        if not root.is_absolute():
            raise GovernedPlanReviewError("plan review output root must be absolute")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = (root / "plan-review").resolve(strict=False)
        if destination != root.resolve(strict=True) and root.resolve(strict=True) not in destination.parents:
            raise GovernedPlanReviewError("plan review output path escapes the execution root")
        destination.mkdir(mode=0o700, exist_ok=True)
        payload = {
            "schema_version": 1,
            "mode": "governed-pre-implementation-plan-review",
            "project": project,
            "objective_sha256": hashlib.sha256(objective.encode("utf-8")).hexdigest(),
            "planning_manifest_sha256": plan_digest,
            "approved": approved,
            "readiness_score": chief.readiness_score,
            "blocking_findings": blockers,
            "rework_plan": rework,
            "departments": department_payloads,
            "chief_engineer": {
                "approved": chief.approved,
                "readiness_score": chief.readiness_score,
                "blocking_findings": list(chief.blocking_findings),
                "rework_plan": list(chief.rework_plan),
                "rationale": chief.rationale,
                "department_decisions": [
                    {
                        "department": decision.department,
                        "approved": decision.approved,
                        "score": decision.score,
                        "findings": list(decision.findings),
                        "required_actions": list(decision.required_actions),
                        "manager_id": decision.manager_id,
                    }
                    for decision in chief.department_decisions
                ],
            },
            "wisdom": {
                "selected": wisdom.selected.name if wisdom.selected else None,
                "ranking": [list(item) for item in wisdom.ranking],
                "confidence": wisdom.confidence,
                "rationale": wisdom.rationale,
                "abstained": wisdom.abstained,
            },
            "government": government,
            "ministry_routing": ministry_payload,
            "implementation_started": False,
            "production_modified": False,
        }
        review_manifest = destination / "manifest.json"
        self._atomic_json(review_manifest, payload)
        report = destination / "REPORT.md"
        report.write_text(self._report(payload), encoding="utf-8")
        os.chmod(report, 0o600)
        return GovernedPlanReviewResult(
            approved=approved,
            readiness_score=chief.readiness_score,
            blocking_findings=tuple(blockers),
            rework_plan=tuple(rework),
            manifest_path=review_manifest,
            report_path=report,
            payload=payload,
        )

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=False)
        if resolved_root not in resolved.parents:
            raise GovernedPlanReviewError("planning artifact path escapes the planning root")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)

    @staticmethod
    def _report(payload: Mapping[str, Any]) -> str:
        blockers = payload.get("blocking_findings") or ["None"]
        rework = payload.get("rework_plan") or ["None"]
        return (
            "# Governed Pre-Implementation Plan Review\n\n"
            f"- Approved for implementation: `{str(payload['approved']).lower()}`\n"
            f"- Chief-engineer readiness: `{payload['readiness_score']}`\n"
            f"- Wisdom strategy: `{payload['wisdom']['selected']}`\n"
            f"- Government verdict: `{payload['government']['verdict']}`\n"
            "- Implementation started during this review: `false`\n\n"
            "## Blocking findings\n"
            + "\n".join(f"- {item}" for item in blockers)
            + "\n\n## Rework plan\n"
            + "\n".join(f"- {item}" for item in rework)
            + "\n"
        )
