"""CI cache contracts: caching must not replace builds or weaken verification."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/final-validation.yml"
BUILD = "Build Security Lab image without competing network-heavy builds"
SETUP = "Set up isolated Security Lab builder"
VERIFY = "Verify Security Lab toolchain image"
SCOPE = "aios-security-tools-linux-amd64-v1"


def step(text: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    if text.count(marker) != 1:
        raise AssertionError(f"Expected one workflow step: {name}")
    body = text.split(marker, 1)[1]
    return body.split("\n      - ", 1)[0]


class SecurityBuildCacheContracts(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_actions_use_immutable_commits(self):
        for name, action in ((SETUP, "setup-buildx-action"), (BUILD, "build-push-action")):
            self.assertRegex(step(self.workflow, name), rf"uses: docker/{action}@[0-9a-f]{{40}}\b")

    def test_builder_does_not_replace_default_compose_builder(self):
        setup = step(self.workflow, SETUP)
        for expected in ("driver: docker-container", "use: false", "install: false", "max-parallelism = 2"):
            self.assertIn(expected, setup)
        self.assertIn("builder: ${{ steps.security-builder.outputs.name }}", step(self.workflow, BUILD))

    def test_exact_production_build_context_is_preserved(self):
        build = step(self.workflow, BUILD)
        for expected in ("context: ./web-dashboard/backend", "file: ./web-dashboard/backend/Dockerfile.security-tools"):
            self.assertIn(expected, build)
        compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text(encoding="utf-8")
        service = compose.split("  security-scan-worker:\n", 1)[1].split("\n  security-remediation-worker:", 1)[0]
        self.assertIn("context: ./backend", service)
        self.assertIn("dockerfile: Dockerfile.security-tools", service)

    def test_image_is_loaded_for_existing_smoke_not_pushed(self):
        build = step(self.workflow, BUILD)
        for expected in ("tags: aionex-aios-security-tools:local", "load: true", "push: false"):
            self.assertIn(expected, build)

    def test_cache_import_has_dedicated_v2_scope(self):
        self.assertIn(f"cache-from: type=gha,version=2,scope={SCOPE}", step(self.workflow, BUILD))

    def test_only_main_push_can_export_shared_cache(self):
        build = step(self.workflow, BUILD)
        export = next(line.strip() for line in build.splitlines() if line.strip().startswith("cache-to:"))
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main' &&", export)
        self.assertIn("|| '' }}", export)
        self.assertIn(f"type=gha,version=2,scope={SCOPE},mode=max", export)

    def test_cache_export_failure_does_not_skip_build_failure(self):
        build = step(self.workflow, BUILD)
        self.assertIn("ignore-error=true,timeout=5m", build)
        self.assertNotIn("continue-on-error", build)
        self.assertNotIn("if:", build)
        self.assertNotIn("cache-hit", build)

    def test_original_toolchain_smoke_still_runs_unconditionally(self):
        verify = step(self.workflow, VERIFY)
        self.assertIn('test "$(docker run --rm aionex-aios-security-tools:local id -u)" = "1000"', verify)
        self.assertIn("semgrep bandit pip-audit schemathesis nuclei katana pd-httpx trivy osv-scanner syft grype gitleaks trufflehog cosign testssl.sh nmap", verify)
        self.assertIn("test -f /app/security-rules/semgrep/aionex.yml", verify)
        self.assertIn('test "$(find /opt/nuclei-templates -type f | wc -l)" -gt 1000', verify)
        self.assertNotIn("if:", verify)
        self.assertNotIn("continue-on-error", verify)

    def test_order_stays_serial_after_other_network_heavy_builds(self):
        names = ["Build and verify Sharp 0.35.5 image derivative worker", SETUP, BUILD, VERIFY,
                 "Verify legacy DATABASE_URL upgrade preserves PostgreSQL data",
                 "Smoke production backup worker and restore round-trip"]
        positions = [self.workflow.index(f"      - name: {name}\n") for name in names]
        self.assertEqual(positions, sorted(positions))

    def test_workflow_permissions_are_not_expanded(self):
        permissions = self.workflow.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(permissions.strip(), "contents: read")
        self.assertEqual(len(re.findall(r"^permissions:|^  +permissions:", self.workflow, flags=re.M)), 1)

    def test_builder_receives_no_production_credentials_or_ssh(self):
        build = step(self.workflow, BUILD)
        for field in ("secrets:", "secret-files:", "secret-envs:", "ssh:", "github-token:", "build-args:"):
            self.assertNotIn(field, build)
        self.assertNotIn("pull_request_target", self.workflow)

    def test_pinned_security_dockerfile_and_native_regressions_remain(self):
        dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text(encoding="utf-8")
        self.assertIn("USER 1000:1000", dockerfile)
        self.assertIn("RUN python /app/scripts/verify_security_pcre2.py", dockerfile)
        self.assertIn("RUN python /app/scripts/verify_security_lzma.py", dockerfile)
        self.assertIn("grype-build-provenance.json", dockerfile)
        self.assertIn("trivy-build-provenance.json", dockerfile)


if __name__ == "__main__":
    unittest.main()
