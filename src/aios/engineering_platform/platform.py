from __future__ import annotations

from .auditor import ProjectAuditor
from .catalog import build_default_language_registry
from .delivery import DefinitionOfDoneEngine
from .planner import ProjectPlanner


class EngineeringPlatform:
    def __init__(self) -> None:
        self.languages = build_default_language_registry()
        self.planner = ProjectPlanner()
        self.auditor = ProjectAuditor()
        self.delivery = DefinitionOfDoneEngine()

    def status(self) -> dict:
        return {
            "language_capabilities": len(self.languages.list()),
            "project_planning": "dependency-validated",
            "project_audit": "quality-security-maintainability",
            "delivery_gates": "evidence-required",
        }
