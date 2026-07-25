from __future__ import annotations

from pathlib import Path

from .cells import CognitiveCell, default_cells
from .deliberation import DeliberationEngine
from .ledger import DecisionLedger
from .models import DecisionOutcome, Proposal
from .registry import CellRegistry


class CognitiveCore:
    """Facade for institutional, auditable multi-cell decisions."""

    def __init__(self, ledger_path: str | Path, cells: tuple[CognitiveCell, ...] | None = None) -> None:
        self.registry = CellRegistry(cells or default_cells())
        self.deliberation = DeliberationEngine(self.registry)
        self.ledger = DecisionLedger(ledger_path)

    def decide(
        self,
        title: str,
        description: str,
        *,
        project: str | None = None,
        risk_level: str = "medium",
        metadata: dict | None = None,
    ) -> DecisionOutcome:
        proposal = Proposal(title, description, project, risk_level, metadata or {})
        outcome = self.deliberation.deliberate(proposal)
        self.ledger.append(proposal, outcome)
        return outcome

    def register_cell(self, cell: CognitiveCell) -> None:
        self.registry.register(cell)
