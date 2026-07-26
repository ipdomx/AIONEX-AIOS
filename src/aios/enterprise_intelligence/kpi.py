from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KPIStatus(str, Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"


@dataclass(frozen=True)
class KPI:
    name: str
    current: float
    target: float
    warning_ratio: float = 0.8
    higher_is_better: bool = True

    @property
    def progress(self) -> float:
        if self.target == 0:
            return 1.0 if self.current == 0 else 0.0
        return self.current / self.target


class KPIEngine:
    def evaluate(self, kpi: KPI) -> KPIStatus:
        ratio = kpi.progress
        if kpi.higher_is_better:
            if ratio >= 1.0:
                return KPIStatus.ON_TRACK
            if ratio >= kpi.warning_ratio:
                return KPIStatus.AT_RISK
            return KPIStatus.OFF_TRACK
        if ratio <= 1.0:
            return KPIStatus.ON_TRACK
        if ratio <= (2.0 - kpi.warning_ratio):
            return KPIStatus.AT_RISK
        return KPIStatus.OFF_TRACK

    def scorecard(self, kpis: list[KPI]) -> dict[str, str]:
        return {kpi.name: self.evaluate(kpi).value for kpi in kpis}
