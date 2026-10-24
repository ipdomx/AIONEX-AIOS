"""FR09: opt-in API scale cannot exceed existing PG connection budget."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "web-dashboard/docker-compose.fr09-backend-workers8-pool56.yml"
BASE = ROOT / "web-dashboard/docker-compose.production.yml"


class Worker8Pool56Tests(unittest.TestCase):
    def test_opt_in_backend_only(self):
        self.assertEqual(
            OVERLAY.read_text(encoding="utf-8"),
            (
                'services:\n'
                '  backend:\n'
                '    environment:\n'
                '      WORKERS: "8"\n'
                '      DATABASE_POOL_SIZE: "6"\n'
                '      DATABASE_MAX_OVERFLOW: "1"\n'
                '      DATABASE_POOL_CONNECTION_BUDGET: "60"\n'
            ),
        )
        self.assertEqual(8 * (6 + 1), 56)
        self.assertLessEqual(56, 60)

    def test_original_source_immutable(self):
        source = BASE.read_text(encoding="utf-8")
        default = (ROOT / 'web-dashboard/backend/app/core/config.py').read_text()
        self.assertIn('WORKERS: int = Field(default=4', default)
        self.assertNotIn('WORKERS:', source)
        self.assertIn('DATABASE_POOL_SIZE: "12"', source)
        self.assertIn('DATABASE_MAX_OVERFLOW: "2"', source)
        self.assertIn('DATABASE_POOL_CONNECTION_BUDGET: "60"', source)

    def test_does_not_touch_other_services(self):
        source = OVERLAY.read_text(encoding="utf-8")
        for omitted in ("project-worker:", "cloudflared:", "nginx:", "postgres:", "redis:"):
            self.assertNotIn(omitted, source)


if __name__ == "__main__":
    unittest.main()
