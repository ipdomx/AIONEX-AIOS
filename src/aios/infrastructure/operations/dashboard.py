from __future__ import annotations
import time


class OperationsDashboardService:
    def __init__(self, cluster, services, resources, metrics, alerts, backups, recovery):
        self.cluster, self.services, self.resources = cluster, services, resources
        self.metrics, self.alerts, self.backups, self.recovery = metrics, alerts, backups, recovery
        self.started_at = time.time()

    async def dashboard(self) -> dict:
        return {"generated_at": time.time(), "uptime_seconds": time.time()-self.started_at,
                "cluster": await self.cluster.summary(), "cluster_nodes": await self.cluster.get_nodes(),
                "services": await self.services.get_status(), "resources": await self.resources.get_snapshot(),
                "metrics": await self.metrics.summary(), "alerts": await self.alerts.summary(),
                "backups": {"total": len(await self.backups.list_backups())},
                "recovery": await self.recovery.summary()}

    async def health(self) -> dict:
        cluster, alerts = await self.cluster.summary(), await self.alerts.summary()
        resources_ok = await self.resources.is_healthy()
        status = "CRITICAL" if alerts["critical_open"] else ("DEGRADED" if not resources_ok or cluster["offline_nodes"] else "HEALTHY")
        return {"status": status, "resources_ok": resources_ok, "cluster": cluster, "alerts": alerts}
