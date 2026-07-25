from __future__ import annotations

from collections import defaultdict

from .models import WorkerHealthReport, WorkerObservation


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


class OperationalHealthInstitute:
    """Evaluates digital-worker performance and behavior; it makes no medical diagnosis."""

    def __init__(self) -> None:
        self._history: dict[str, list[WorkerObservation]] = defaultdict(list)
        self._advisors: dict[str, str] = {}

    def assign_advisor(self, worker_id: str, advisor_id: str) -> None:
        self._advisors[worker_id] = advisor_id

    def advisor_for(self, worker_id: str) -> str | None:
        return self._advisors.get(worker_id)

    def observe(self, observation: WorkerObservation) -> WorkerHealthReport:
        self._history[observation.worker_id].append(observation)
        records = self._history[observation.worker_id][-20:]

        avg = lambda attr: sum(getattr(item, attr) for item in records) / len(records)
        incident_penalty = min(30.0, sum(len(item.incidents) for item in records) * 2.5)
        health = _bounded((avg("reliability") + avg("policy_compliance")) / 2 - incident_penalty)
        performance = _bounded((avg("quality") + avg("reliability")) / 2)
        collaboration = _bounded(avg("collaboration"))
        learning = _bounded(avg("learning"))
        trust = _bounded((health + performance + collaboration) / 3)

        restrictions: list[str] = []
        if avg("policy_compliance") < 70:
            restrictions.append("mandatory_policy_review")
        if avg("reliability") < 65:
            restrictions.append("supervised_execution_only")
        if incident_penalty >= 15:
            restrictions.append("temporary_privilege_reduction")

        if trust >= 90 and not restrictions:
            recommendation = "eligible_for_promotion_review"
        elif trust >= 75 and not restrictions:
            recommendation = "continue_with_standard_monitoring"
        elif trust >= 60:
            recommendation = "academy_retraining_and_increased_review"
        else:
            recommendation = "temporary_suspension_and_recertification"

        return WorkerHealthReport(
            worker_id=observation.worker_id,
            operational_health=health,
            performance=performance,
            collaboration=collaboration,
            trust=trust,
            learning=learning,
            recommendation=recommendation,
            restrictions=tuple(restrictions),
        )

    def history(self, worker_id: str) -> tuple[WorkerObservation, ...]:
        return tuple(self._history.get(worker_id, ()))
