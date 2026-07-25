from __future__ import annotations

from collections.abc import Iterable

from .cells import CognitiveCell


class CellRegistry:
    def __init__(self, cells: Iterable[CognitiveCell] = ()) -> None:
        self._cells: dict[str, CognitiveCell] = {}
        for cell in cells:
            self.register(cell)

    def register(self, cell: CognitiveCell) -> None:
        if not cell.id.strip():
            raise ValueError("Cell id cannot be empty")
        if cell.id in self._cells:
            raise ValueError(f"Cell already registered: {cell.id}")
        if cell.weight <= 0:
            raise ValueError("Cell weight must be positive")
        self._cells[cell.id] = cell

    def get(self, cell_id: str) -> CognitiveCell:
        return self._cells[cell_id]

    def all(self) -> tuple[CognitiveCell, ...]:
        return tuple(self._cells[key] for key in sorted(self._cells))

    def __len__(self) -> int:
        return len(self._cells)
