"""FR09 opt-in Next CPU overlay: protect the immutable FR06 base proof."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
OVERLAY = ROOT / "web-dashboard" / "docker-compose.fr09-frontend-cpu.yml"


def service(name: str) -> str:
    source = COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9_-]+:\n|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"Missing production Compose service: {name}")
    return match.group(1)


class FrontendCpuBudgetContract(unittest.TestCase):
    def test_opt_in_overlay_is_only_one_resource_budget(self):
        self.assertEqual(
            OVERLAY.read_text(encoding="utf-8"),
            'services:\n  frontend:\n    cpus: "3.0"\n',
        )

    def test_default_retains_historically_attested_cpu_budget(self):
        frontend = service("frontend")
        self.assertIn('    cpus: "1.5"\n', frontend)
        self.assertIn("    mem_limit: 1g\n", frontend)
        self.assertIn("    read_only: true\n", frontend)
        self.assertIn('    cap_drop: ["ALL"]\n', frontend)
        self.assertIn("    pids_limit: 256\n", frontend)
        self.assertNotIn("\n    ports:", frontend)

    def test_portal_and_backend_budgets_untouched(self):
        self.assertIn('    cpus: "1.5"\n', service("portal"))
        backend = service("backend")
        self.assertIn('    cpus: "4.0"\n', backend)
        self.assertIn("    mem_limit: 4g\n", backend)
        self.assertIn('      DATABASE_POOL_SIZE: "12"\n', backend)
        self.assertIn('      DATABASE_MAX_OVERFLOW: "2"\n', backend)
        self.assertIn('      DATABASE_POOL_CONNECTION_BUDGET: "60"\n', backend)


if __name__ == "__main__":
    unittest.main()
