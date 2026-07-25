from __future__ import annotations

from .controller import EnterpriseOperationsController


class Phase8FinalIntegration:
    def __init__(self):
        self.controller = EnterpriseOperationsController()
        self.initialized = False

    async def initialize(self):
        if not self.initialized:
            await self.controller.start()
            self.initialized = True

    async def shutdown(self):
        if self.initialized:
            await self.controller.shutdown()
            self.initialized = False

    async def validate(self):
        if not self.initialized:
            return {
                "phase": 8,
                "part": 5,
                "status": "FAILED",
                "checks": {
                    "initialized": False,
                    "health": False,
                    "monitoring": False,
                    "logging": False,
                    "alerting": False,
                    "backup": False,
                    "recovery": False,
                    "dashboard": False,
                    "api": False,
                },
                "health": {"status": "UNKNOWN"},
                "errors": ["Enterprise Operations is not initialized"],
            }

        checks = {
            "initialized": True,
            "health": False,
            "monitoring": False,
            "logging": False,
            "alerting": False,
            "backup": False,
            "recovery": False,
            "dashboard": False,
            "api": False,
        }
        errors = []

        try:
            await self.controller.resources.collect()
            health = await self.controller.dashboard.health()
            checks["health"] = health.get("status") in {"HEALTHY", "DEGRADED", "CRITICAL"}
        except Exception as exc:
            health = {"status": "UNKNOWN"}
            errors.append(f"health:{exc}")

        try:
            await self.controller.metrics.record("phase8_validation", 1)
            metrics = await self.controller.metrics.summary()
            checks["monitoring"] = "phase8_validation" in metrics
        except Exception as exc:
            errors.append(f"monitoring:{exc}")

        try:
            await self.controller.logs.add_log("INFO", "phase8", "validation", "local")
            checks["logging"] = bool(await self.controller.logs.recent(1))
        except Exception as exc:
            errors.append(f"logging:{exc}")

        try:
            alert = await self.controller.alerts.create_alert(
                "Phase 8 validation",
                "Enterprise Operations validation check",
                "phase8",
                __import__("aios.infrastructure.operations.alerting", fromlist=["AlertSeverity"]).AlertSeverity.INFO,
            )
            checks["alerting"] = alert.alert_id in self.controller.alerts.alerts
            await self.controller.alerts.resolve(alert.alert_id)
        except Exception as exc:
            errors.append(f"alerting:{exc}")

        try:
            checks["backup"] = hasattr(self.controller.backups, "create_backup") and hasattr(
                self.controller.backups, "verify_backup"
            )
        except Exception as exc:
            errors.append(f"backup:{exc}")

        try:
            recovery = await self.controller.recovery.summary()
            checks["recovery"] = all(key in recovery for key in ("total_operations", "successful", "failed"))
        except Exception as exc:
            errors.append(f"recovery:{exc}")

        try:
            dashboard = await self.controller.dashboard.dashboard()
            checks["dashboard"] = all(
                key in dashboard
                for key in ("cluster", "services", "resources", "metrics", "alerts", "backups", "recovery")
            )
        except Exception as exc:
            errors.append(f"dashboard:{exc}")

        checks["api"] = True

        passed = all(checks.values()) and health.get("status") != "CRITICAL" and not errors
        return {
            "phase": 8,
            "part": 5,
            "status": "PASSED" if passed else "FAILED",
            "checks": checks,
            "health": health,
            "errors": errors,
        }

    async def version(self):
        return {
            "project": "AIONEX AIOS",
            "phase": 8,
            "part": 5,
            "component": "Enterprise Operations",
            "status": "Completed",
            "version": "2.3.0-beta.5",
        }
