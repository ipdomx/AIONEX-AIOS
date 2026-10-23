"""FR09 protected frontend CPU candidate: avoid widening unrelated budgets."""

from pathlib import Path
import re
import unittest


COMPOSE = (
    Path(__file__).resolve().parents[1]
    / "web-dashboard"
    / "docker-compose.production.yml"
)


def service(name: str) -> str:
    source = COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9_-]+:\n|\\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"Missing production Compose service: {name}")
    return match.group(1)


class FrontendCpuBudgetContract(unittest.TestCase):
    def test_frontend_cpu_candidate_is_bounded(self):
        frontend = service("frontend")
        self.assertIn('    cpus: "3.0"\n', frontend)
        self.assertIn("    mem_limit: 1g\n", frontend)
        self.assertIn("    read_only: true\n", frontend)
        self.assertIn('    cap_drop: ["ALL"]\n', frontend)
        self.assertIn("    pids_limit: 256\n", frontend)
        self.assertNotIn("\n    ports:", frontend)

    def test_portal_and_backend_budgets_unchanged(self):
        self.assertIn('    cpus: "1.5"\n', service("portal"))
        backend = service("backend")
        self.assertIn('    cpus: "4.0"\n', backend)
        self.assertIn("    mem_limit: 4g\n", backend)
        self.assertIn('      DATABASE_POOL_SIZE: "12"\n', backend)
        self.assertIn('      DATABASE_MAX_OVERFLOW: "2"\n', backend)
        self.assertIn('      DATABASE_POOL_CONNECTION_BUDGET: "60"\n', backend)


if __name__ == "__main__":
    unittest.main()
