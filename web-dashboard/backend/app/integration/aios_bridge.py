"""Bridge between the web dashboard FastAPI app and the AIOS core modules."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AIOSIntegrationStatus:
    available: bool
    version: str
    root: str
    modules: dict[str, bool]
    error: str | None = None


class AIOSCoreBridge:
    """Loads AIOS core packages from the monorepo without coupling dashboard code."""

    def __init__(self) -> None:
        self.repo_root = Path(
            os.getenv("AIOS_REPO_ROOT", Path(__file__).resolve().parents[4])
        ).resolve()
        self.src_root = self.repo_root / "src"
        self._error: str | None = None
        self._modules: dict[str, bool] = {}

    def initialize(self) -> AIOSIntegrationStatus:
        if str(self.src_root) not in sys.path:
            sys.path.insert(0, str(self.src_root))

        for module_name in (
            "aios.api_experience",
            "aios.web_dashboard_integration",
            "aios.mobile_ecosystem",
            "aios.global_communications",
            "aios.enterprise_intelligence",
            "aios.production_hardening",
        ):
            try:
                importlib.import_module(module_name)
                self._modules[module_name] = True
            except Exception as exc:  # pragma: no cover - diagnostic path
                self._modules[module_name] = False
                self._error = f"{module_name}: {exc}"

        return self.status()

    def status(self) -> AIOSIntegrationStatus:
        version_file = self.repo_root / "VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"
        available = bool(self._modules) and all(self._modules.values())
        return AIOSIntegrationStatus(
            available=available,
            version=version,
            root=str(self.repo_root),
            modules=dict(self._modules),
            error=self._error,
        )

    def build_platforms(self) -> dict[str, Any]:
        """Create default platform objects for dashboard-backed integration endpoints."""
        self.initialize()
        platforms: dict[str, Any] = {}

        factories = {
            "api_experience": ("aios.api_experience", "APIExperiencePlatform"),
            "web_dashboard": ("aios.web_dashboard_integration", "WebDashboardIntegrationPlatform"),
            "mobile": ("aios.mobile_ecosystem", "MobileEcosystemPlatform"),
            "communications": ("aios.global_communications", "GlobalCommunicationsPlatform"),
            "intelligence": ("aios.enterprise_intelligence", "EnterpriseIntelligencePlatform"),
            "production": ("aios.production_hardening", "ProductionHardeningPlatform"),
        }
        for key, (module_name, class_name) in factories.items():
            try:
                module = importlib.import_module(module_name)
                platform_class = getattr(module, class_name)
                platforms[key] = platform_class.build_default()
            except Exception:
                platforms[key] = None
        return platforms


aios_bridge = AIOSCoreBridge()
