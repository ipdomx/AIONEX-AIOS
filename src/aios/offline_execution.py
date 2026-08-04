from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .organization import EngineeringOrganization


_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class OfflineExecutionResult:
    execution_id: str
    output_directory: Path
    manifest_path: Path
    report_path: Path
    artifact_paths: tuple[Path, ...]
    approved: bool
    readiness_score: float
    blocking_findings: tuple[str, ...]
    rework_plan: tuple[str, ...]
    network_used: bool = False
    provider_keys_used: bool = False
    production_modified: bool = False


class OfflineMockExecutor:
    """Create deterministic local engineering artifacts without providers or network access."""

    def __init__(self, organization: EngineeringOrganization | None = None) -> None:
        self.organization = organization or EngineeringOrganization()

    def execute(
        self,
        *,
        execution_id: str,
        project: str,
        objective: str,
        output_root: str | Path,
    ) -> OfflineExecutionResult:
        root = self._prepare_root(output_root)
        safe_id = self._validate_execution_id(execution_id)
        destination = self._contained(root, root / safe_id)
        staging = self._contained(root, root / f".staging-{safe_id}")

        if destination.exists():
            raise FileExistsError(f"offline execution already exists: {safe_id}")
        if staging.exists():
            raise FileExistsError(f"offline execution staging already exists: {safe_id}")

        staging.mkdir(mode=0o700)
        try:
            artifacts_dir = staging / "artifacts"
            artifacts_dir.mkdir(mode=0o700)

            blueprint = self.organization.plan(project, objective)
            artifact_records: list[dict[str, Any]] = []
            artifact_paths: list[Path] = []

            for deliverable in blueprint.deliverables:
                filename = f"{deliverable.department.lower()}.json"
                artifact_path = artifacts_dir / filename
                payload = self._artifact_payload(
                    execution_id=safe_id,
                    project=project,
                    objective=objective,
                    department=deliverable.department,
                    acceptance_criteria=deliverable.acceptance_criteria,
                )
                content = self._canonical_json(payload)
                self._atomic_write_text(artifact_path, content)
                digest = self._sha256(artifact_path)
                artifact_records.append(
                    {
                        "department": deliverable.department,
                        "path": f"artifacts/{filename}",
                        "sha256": digest,
                    }
                )
                artifact_paths.append(artifact_path)
                deliverable.evidence.update(
                    {
                        "passed_criteria": list(deliverable.acceptance_criteria),
                        "tests_passed": True,
                        "security_reviewed": True,
                        "artifact": f"artifacts/{filename}",
                        "sha256": digest,
                    }
                )

            review = self.organization.chief_review(blueprint)
            manifest = {
                "schema_version": 1,
                "execution_id": safe_id,
                "project": project,
                "objective": objective,
                "mode": "offline-mock",
                "departments": list(blueprint.departments),
                "artifacts": artifact_records,
                "review": {
                    "approved": review.approved,
                    "readiness_score": review.readiness_score,
                    "blocking_findings": list(review.blocking_findings),
                    "rework_plan": list(review.rework_plan),
                },
                "proof": {
                    "network_used": False,
                    "provider_keys_used": False,
                    "production_modified": False,
                },
            }
            manifest_path = staging / "manifest.json"
            self._atomic_write_text(manifest_path, self._canonical_json(manifest))

            report_path = staging / "REPORT.md"
            self._atomic_write_text(report_path, self._report(manifest))

            os.replace(staging, destination)
            return OfflineExecutionResult(
                execution_id=safe_id,
                output_directory=destination,
                manifest_path=destination / "manifest.json",
                report_path=destination / "REPORT.md",
                artifact_paths=tuple(destination / record["path"] for record in artifact_records),
                approved=review.approved,
                readiness_score=review.readiness_score,
                blocking_findings=review.blocking_findings,
                rework_plan=review.rework_plan,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

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
    def _artifact_payload(
        *,
        execution_id: str,
        project: str,
        objective: str,
        department: str,
        acceptance_criteria: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "execution_id": execution_id,
            "project": project,
            "objective": objective,
            "department": department,
            "status": "complete",
            "acceptance_criteria": list(acceptance_criteria),
            "evidence": {
                "passed_criteria": list(acceptance_criteria),
                "tests_passed": True,
                "security_reviewed": True,
            },
            "execution": {
                "mode": "offline-mock",
                "network_used": False,
                "provider_keys_used": False,
                "production_modified": False,
            },
        }

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
        proof = manifest["proof"]
        artifact_lines = "\n".join(
            f"- {item['department']}: `{item['path']}` — SHA-256 `{item['sha256']}`"
            for item in manifest["artifacts"]
        )
        blockers = review["blocking_findings"] or ["None"]
        rework = review["rework_plan"] or ["None"]
        return (
            f"# Offline Mock Execution Report\n\n"
            f"- Execution ID: `{manifest['execution_id']}`\n"
            f"- Project: `{manifest['project']}`\n"
            f"- Mode: `offline-mock`\n"
            f"- Approved: `{str(review['approved']).lower()}`\n"
            f"- Readiness score: `{review['readiness_score']}`\n"
            f"- Network used: `{str(proof['network_used']).lower()}`\n"
            f"- Provider keys used: `{str(proof['provider_keys_used']).lower()}`\n"
            f"- Production modified: `{str(proof['production_modified']).lower()}`\n\n"
            f"## Artifacts\n\n{artifact_lines}\n\n"
            f"## Blocking findings\n\n" + "\n".join(f"- {item}" for item in blockers) + "\n\n"
            f"## Rework plan\n\n" + "\n".join(f"- {item}" for item in rework) + "\n"
        )
