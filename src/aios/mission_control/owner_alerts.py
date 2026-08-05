from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(slots=True)
class OwnerAlert:
    alert_id: str
    owner_id: str
    source: str
    title: str
    message: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class OwnerAlertService:
    def __init__(self) -> None:
        self._alerts: dict[str, OwnerAlert] = {}

    def publish(self, alert: OwnerAlert) -> OwnerAlert:
        if alert.alert_id in self._alerts:
            raise ValueError(f"duplicate alert: {alert.alert_id}")
        self._alerts[alert.alert_id] = alert
        return alert

    def acknowledge(self, alert_id: str, owner_id: str) -> OwnerAlert:
        alert = self._require_owner(alert_id, owner_id)
        if alert.status is AlertStatus.RESOLVED:
            return alert
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = datetime.now(timezone.utc)
        return alert

    def resolve(self, alert_id: str, owner_id: str) -> OwnerAlert:
        alert = self._require_owner(alert_id, owner_id)
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = datetime.now(timezone.utc)
        return alert

    def list_for_owner(
        self,
        owner_id: str,
        *,
        statuses: Iterable[AlertStatus] | None = None,
        minimum_severity: AlertSeverity | None = None,
    ) -> list[OwnerAlert]:
        severity_rank = {
            AlertSeverity.INFO: 1,
            AlertSeverity.WARNING: 2,
            AlertSeverity.CRITICAL: 3,
        }
        allowed = set(statuses) if statuses is not None else None
        result = [alert for alert in self._alerts.values() if alert.owner_id == owner_id]
        if allowed is not None:
            result = [alert for alert in result if alert.status in allowed]
        if minimum_severity is not None:
            result = [
                alert
                for alert in result
                if severity_rank[alert.severity] >= severity_rank[minimum_severity]
            ]
        return sorted(result, key=lambda alert: alert.created_at, reverse=True)

    def _require_owner(self, alert_id: str, owner_id: str) -> OwnerAlert:
        try:
            alert = self._alerts[alert_id]
        except KeyError as exc:
            raise KeyError(f"unknown alert: {alert_id}") from exc
        if alert.owner_id != owner_id:
            raise PermissionError("alert is not owned by this owner")
        return alert
