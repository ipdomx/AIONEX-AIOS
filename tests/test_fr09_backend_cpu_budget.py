"""FR09 optional Backend CPU-only quota: protect immutable FR06 base contracts."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
OVERLAY = ROOT / "web-dashboard" / "docker-compose.fr09-backend-cpu.yml"
FRONT_OVERLAY = ROOT / "web-dashboard" / "docker-compose.fr09-frontend-cpu.yml"


def service(name: str) -> str:
    source = COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9_-]+:\n|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"Missing production Compose service: {name}")
    return match.group(1)


class BackendCpuBudgetContract(unittest.TestCase):
    def test_opt_in_overlay_only_changes_backend_cpus(self):
        self.assertEqual(
            OVERLAY.read_text(encoding="utf-8"),
            'services:\n  backend:\n    cpus: "8.0"\n',
        )

    def test_base_backend_protected_budget_not_modified(self):
        backend = service("backend")
        self.assertIn('    cpus: "4.0"\n', backend)
        self.assertIn("    mem_limit: 4g\n", backend)
        self.assertIn("    pids_limit: 768\n", backend)
        self.assertIn('      DATABASE_POOL_SIZE: "12"\n', backend)
        self.assertIn('      DATABASE_MAX_OVERFLOW: "2"\n', backend)
        self.assertIn('      DATABASE_POOL_CONNECTION_BUDGET: "60"\n', backend)
        self.assertIn('      PROJECT_EXECUTION_ADMISSION_CONCURRENCY: "14"\n', backend)
        self.assertIn('      PROJECT_EXECUTION_ADMISSION_GLOBAL_LIMIT: "48"\n', backend)

    def test_opt_in_frontend_budget_and_public_portal_unchanged(self):
        self.assertEqual(
            FRONT_OVERLAY.read_text(encoding="utf-8"),
            'services:\n  frontend:\n    cpus: "3.0"\n',
        )
        self.assertIn('    cpus: "1.5"\n', service("frontend"))
        self.assertIn('    cpus: "1.5"\n', service("portal"))
        self.assertNotIn('    image: aionex-aios-backend:fr09-', service("backend"))

    def test_worker_services_are_never_opted_into_cpu_overlay(self):
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertNotIn("project-worker:", text)
        self.assertNotIn("identity-media-worker:", text)
        self.assertNotIn("media-worker:", text)
        self.assertNotIn("cloudflared:", text)
        self.assertNotIn("nginx:", text)


if __name__ == "__main__":
    unittest.main()
