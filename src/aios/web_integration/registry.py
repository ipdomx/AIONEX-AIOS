from __future__ import annotations

from .contracts import DashboardManifest


class DashboardRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, DashboardManifest] = {}

    def register(self, manifest: DashboardManifest) -> DashboardManifest:
        self._manifests[manifest.dashboard_id] = manifest
        return manifest

    def get(self, dashboard_id: str) -> DashboardManifest:
        try:
            return self._manifests[dashboard_id]
        except KeyError as exc:
            raise LookupError(f"dashboard not registered: {dashboard_id}") from exc

    def list(self) -> list[DashboardManifest]:
        return sorted(self._manifests.values(), key=lambda item: item.dashboard_id)

    def remove(self, dashboard_id: str) -> bool:
        return self._manifests.pop(dashboard_id, None) is not None

    def validate(self, dashboard_id: str) -> dict[str, bool]:
        manifest = self.get(dashboard_id)
        checks = {
            "identity": bool(manifest.dashboard_id and manifest.name and manifest.version),
            "api_base_path": manifest.api_base_path.startswith("/"),
            "routes": bool(manifest.routes),
            "route_integrity": all(route.enabled and route.path.startswith("/") for route in manifest.routes),
        }
        checks["ready"] = all(checks.values())
        return checks
