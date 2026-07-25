from __future__ import annotations
import asyncio, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional


class AlertSeverity(str, Enum):
    INFO="INFO"; WARNING="WARNING"; ERROR="ERROR"; CRITICAL="CRITICAL"


class AlertStatus(str, Enum):
    OPEN="OPEN"; ACKNOWLEDGED="ACKNOWLEDGED"; RESOLVED="RESOLVED"


@dataclass
class Alert:
    alert_id: str
    title: str
    message: str
    source: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AlertManager:
    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.lock = asyncio.Lock()

    async def create_alert(self, title: str, message: str, source: str, severity: AlertSeverity,
                           metadata: Optional[Dict[str, Any]] = None) -> Alert:
        alert = Alert(uuid.uuid4().hex, title, message, source, severity, metadata=metadata or {})
        async with self.lock:
            self.alerts[alert.alert_id] = alert
        return alert

    async def acknowledge(self, alert_id: str) -> Alert:
        async with self.lock:
            self.alerts[alert_id].status = AlertStatus.ACKNOWLEDGED
            return self.alerts[alert_id]

    async def resolve(self, alert_id: str) -> Alert:
        async with self.lock:
            self.alerts[alert_id].status = AlertStatus.RESOLVED
            return self.alerts[alert_id]

    async def list_alerts(self, limit: int = 100) -> list[dict]:
        async with self.lock:
            items = sorted(self.alerts.values(), key=lambda x: x.created_at, reverse=True)[:limit]
            return [{**vars(a), "severity": a.severity.value, "status": a.status.value} for a in items]

    async def summary(self) -> dict:
        async with self.lock:
            values = list(self.alerts.values())
            return {"total": len(values), "open": sum(a.status == AlertStatus.OPEN for a in values),
                    "acknowledged": sum(a.status == AlertStatus.ACKNOWLEDGED for a in values),
                    "resolved": sum(a.status == AlertStatus.RESOLVED for a in values),
                    "critical_open": sum(a.severity == AlertSeverity.CRITICAL and a.status != AlertStatus.RESOLVED for a in values)}


class ComparisonOperator(str, Enum):
    GT="GT"; GTE="GTE"; LT="LT"; LTE="LTE"; EQ="EQ"; NE="NE"


@dataclass
class AlertRule:
    rule_id: str
    name: str
    metric_name: str
    operator: ComparisonOperator
    threshold: float
    severity: AlertSeverity
    source: str
    cooldown_seconds: float = 300.0
    last_triggered_at: Optional[float] = None


class AlertRulesEngine:
    def __init__(self, manager: AlertManager):
        self.manager, self.rules = manager, {}

    async def create_rule(self, name, metric_name, operator, threshold, severity, source, cooldown_seconds=300.0):
        rule = AlertRule(uuid.uuid4().hex, name, metric_name, operator, float(threshold), severity, source, cooldown_seconds)
        self.rules[rule.rule_id] = rule
        return rule

    async def evaluate(self, metric_name: str, value: float) -> list[str]:
        ids = []
        ops = {ComparisonOperator.GT: lambda a,b:a>b, ComparisonOperator.GTE:lambda a,b:a>=b,
               ComparisonOperator.LT:lambda a,b:a<b, ComparisonOperator.LTE:lambda a,b:a<=b,
               ComparisonOperator.EQ:lambda a,b:a==b, ComparisonOperator.NE:lambda a,b:a!=b}
        for rule in self.rules.values():
            if rule.metric_name != metric_name or not ops[rule.operator](value, rule.threshold):
                continue
            if rule.last_triggered_at and time.time()-rule.last_triggered_at < rule.cooldown_seconds:
                continue
            alert = await self.manager.create_alert(rule.name, f"{metric_name}={value}", rule.source, rule.severity)
            rule.last_triggered_at = time.time()
            ids.append(alert.alert_id)
        return ids


NotificationHandler = Callable[[str, str, Dict[str, Any]], Awaitable[None]]


class NotificationDispatcher:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.handlers: Dict[str, NotificationHandler] = {}

    async def register_handler(self, channel: str, handler: NotificationHandler) -> None:
        self.handlers[channel] = handler

    async def dispatch(self, channel: str, recipient: str, subject: str, payload: Dict[str, Any]) -> dict:
        handler = self.handlers.get(channel)
        if handler is None:
            return {"status": "FAILED", "error": f"No handler for {channel}"}
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                await handler(recipient, subject, payload)
                return {"status": "SENT", "attempt": attempt}
            except Exception as exc:
                last_error = str(exc)
                await asyncio.sleep(0)
        return {"status": "FAILED", "error": last_error}
