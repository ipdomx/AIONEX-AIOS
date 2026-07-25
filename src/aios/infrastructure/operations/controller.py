from __future__ import annotations
from .health import ClusterHealthManager, ServiceHealthMonitor, SystemResourceMonitor
from .monitoring import MetricsCollector, ObservabilityManager
from .logging import StructuredLogger, LogAggregator
from .alerting import AlertManager, AlertRulesEngine, NotificationDispatcher
from .backup import BackupManager, BackupScheduler
from .recovery import DisasterRecoveryManager, RecoveryValidator
from .dashboard import OperationsDashboardService


class EnterpriseOperationsController:
    def __init__(self):
        self.cluster = ClusterHealthManager()
        self.services = ServiceHealthMonitor()
        self.resources = SystemResourceMonitor()
        self.metrics = MetricsCollector()
        self.observability = ObservabilityManager(self.metrics)
        self.logger = StructuredLogger("enterprise_operations")
        self.logs = LogAggregator()
        self.alerts = AlertManager()
        self.rules = AlertRulesEngine(self.alerts)
        self.notifications = NotificationDispatcher()
        self.backups = BackupManager()
        self.scheduler = BackupScheduler(self.backups)
        self.recovery = DisasterRecoveryManager(self.backups)
        self.validator = RecoveryValidator()
        self.dashboard = OperationsDashboardService(self.cluster, self.services, self.resources,
                                                    self.metrics, self.alerts, self.backups, self.recovery)

    async def start(self):
        await self.logger.info("Enterprise Operations starting")
        await self.resources.collect()
        await self.metrics.record("operations_startup", 1)
        await self.scheduler.start()

    async def shutdown(self):
        await self.scheduler.stop()
        await self.logger.info("Enterprise Operations stopped")

    async def summary(self):
        return await self.dashboard.dashboard()
