from __future__ import annotations
from .models import MinistryAssignment, MinistryDefinition, MinistryState

class MinistryRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, MinistryDefinition] = {}
        self._states: dict[str, MinistryState] = {}
        self._assignments: list[MinistryAssignment] = []

    def register(self, definition: MinistryDefinition) -> None:
        if definition.ministry_id in self._definitions:
            raise ValueError(f'ministry already registered: {definition.ministry_id}')
        self._definitions[definition.ministry_id] = definition
        self._states[definition.ministry_id] = MinistryState.ACTIVE

    def set_state(self, ministry_id: str, state: MinistryState) -> None:
        self.require(ministry_id)
        self._states[ministry_id] = state

    def state(self, ministry_id: str) -> MinistryState:
        self.require(ministry_id)
        return self._states[ministry_id]

    def require(self, ministry_id: str) -> MinistryDefinition:
        try:
            return self._definitions[ministry_id]
        except KeyError as exc:
            raise KeyError(f'unknown ministry: {ministry_id}') from exc

    def assign(self, assignment: MinistryAssignment) -> None:
        self.require(assignment.ministry_id)
        if self.state(assignment.ministry_id) != MinistryState.ACTIVE:
            raise PermissionError('inactive ministry cannot receive work')
        self._assignments.append(assignment)

    def list(self) -> tuple[MinistryDefinition, ...]:
        return tuple(self._definitions.values())

    def assignments(self, project_id: str | None = None) -> tuple[MinistryAssignment, ...]:
        items = self._assignments
        if project_id is not None:
            items = [item for item in items if item.project_id == project_id]
        return tuple(items)
