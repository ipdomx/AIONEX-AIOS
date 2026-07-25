from __future__ import annotations
from collections import defaultdict
from .models import ServiceDefinition, ServiceEvaluation, ServiceState

class UniversalServiceRegistry:
    LEVELS=('system','organization','project','team','worker')
    def __init__(self) -> None:
        self._services: dict[str, ServiceDefinition] = {}
        self._states: dict[str, ServiceState] = {}
        self._policies: dict[tuple[str,str,str], bool] = {}
        self._evaluations: dict[str, ServiceEvaluation] = {}

    def register(self, definition: ServiceDefinition) -> None:
        if definition.service_id in self._services:
            raise ValueError('service already registered')
        self._services[definition.service_id]=definition
        self._states[definition.service_id]=definition.default_state

    def evaluate(self, evaluation: ServiceEvaluation) -> None:
        if evaluation.service_id not in self._services:
            raise KeyError(evaluation.service_id)
        self._evaluations[evaluation.service_id]=evaluation

    def enable(self, service_id: str, *, actor_is_owner: bool) -> None:
        if not actor_is_owner:
            raise PermissionError('only owner may enable services')
        evaluation=self._evaluations.get(service_id)
        if evaluation and not evaluation.eligible:
            raise PermissionError('service evaluation does not permit activation')
        self._states[service_id]=ServiceState.ENABLED

    def disable(self, service_id: str, *, actor_is_owner: bool) -> None:
        if not actor_is_owner:
            raise PermissionError('only owner may disable services')
        self._states[service_id]=ServiceState.DISABLED

    def set_policy(self, service_id: str, level: str, subject_id: str, allowed: bool, *, actor_is_owner: bool) -> None:
        if not actor_is_owner:
            raise PermissionError('only owner may change service policies')
        if level not in self.LEVELS:
            raise ValueError('invalid policy level')
        self._policies[(service_id,level,subject_id)]=allowed

    def allowed(self, service_id: str, context: dict[str,str]) -> bool:
        if self._states.get(service_id) != ServiceState.ENABLED:
            return False
        decision=True
        for level in self.LEVELS:
            subject=context.get(level)
            if subject is not None and (service_id,level,subject) in self._policies:
                decision=self._policies[(service_id,level,subject)]
        return decision

    def state(self, service_id: str) -> ServiceState:
        return self._states[service_id]

    def list(self) -> tuple[ServiceDefinition,...]:
        return tuple(self._services.values())
