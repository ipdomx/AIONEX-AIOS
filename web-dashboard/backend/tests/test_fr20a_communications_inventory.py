"""FR-20A source-only acceptance for truthful communication/social readiness.

This test intentionally uses only the Python standard library. It performs no provider
calls, database calls, credential reads, customer-data access, spend, publication, or
historical-delivery mutation.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
COMMUNICATIONS = BACKEND / "app" / "services" / "communications.py"
SOCIAL_ACCOUNTS = BACKEND / "app" / "services" / "growth_social_accounts.py"
SOCIAL_CONNECTORS = BACKEND / "app" / "services" / "growth_provider_connectors.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function_segment(path: Path, name: str) -> str:
    text = _source(path)
    for node in _tree(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if segment is None:
                raise AssertionError(f"Unable to recover source for {name}")
            return segment
    raise AssertionError(f"Missing function {name} in {path}")


def _returned_dict_keys(path: Path, function_name: str) -> set[str]:
    tree = _tree(path)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        keys: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Dict):
                for key in child.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
        return keys
    raise AssertionError(f"Missing function {function_name} in {path}")


class FR20ACommunicationsInventoryAcceptance(unittest.TestCase):
    def test_in_app_delivery_stays_durable_when_external_channels_are_unavailable(self):
        segment = _function_segment(COMMUNICATIONS, "_ensure_notification_deliveries")

        self.assertIn('if channel == "in_app":', segment)
        self.assertIn('delivery_status = "delivered"', segment)
        self.assertIn('delivered_at = now()', segment)
        self.assertIn('elif not state["ready"]:', segment)
        self.assertIn('delivery_status = "unconfigured"', segment)
        self.assertIn('error_code = "provider_unconfigured"', segment)
        self.assertIn(
            'next_attempt_at=now() if delivery_status == "queued" else None',
            segment,
        )

        in_app_index = segment.index('if channel == "in_app":')
        unavailable_index = segment.index('elif not state["ready"]:')
        self.assertLess(in_app_index, unavailable_index)

    def test_email_telegram_firebase_readiness_is_fail_closed_and_secret_free(self):
        segment = _function_segment(COMMUNICATIONS, "channel_readiness")
        returned_keys = _returned_dict_keys(COMMUNICATIONS, "channel_readiness")

        self.assertIn("SMTP_HOST", segment)
        self.assertIn("SMTP_PASSWORD", segment)
        self.assertIn("FIREBASE_PROJECT_ID", segment)
        self.assertIn("FIREBASE_ADMIN_CREDENTIALS_JSON", segment)
        self.assertIn('_telegram_scope_ready("owner")', segment)
        self.assertIn('_telegram_scope_ready("user")', segment)
        self.assertIn('"status": "ready" if ready else "unconfigured"', segment)

        self.assertTrue(
            {"id", "name", "configured", "ready", "status", "reason",
             "owner_only", "capabilities"} <= returned_keys
        )
        sensitive_output_keys = {
            "password",
            "token",
            "authorization",
            "bearer",
            "private_key",
            "credential",
            "secret",
        }
        self.assertTrue(returned_keys.isdisjoint(sensitive_output_keys))

    def test_firebase_ready_is_local_configuration_readiness_only(self):
        segment = _function_segment(COMMUNICATIONS, "channel_readiness")

        self.assertIn("firebase_path = Path(", segment)
        self.assertIn('firebase_path.read_text(encoding="utf-8")', segment)
        self.assertIn('firebase_document.get("type") == "service_account"', segment)
        self.assertIn(
            'firebase_document.get("project_id") == settings.FIREBASE_PROJECT_ID',
            segment,
        )
        self.assertIn('for key in ("client_email", "private_key")', segment)

        forbidden_live_calls = (
            "httpx.",
            "requests.",
            "aiohttp.",
            "urllib.",
            "firebase_admin.",
            "messaging.send",
            "credentials.Certificate",
        )
        for marker in forbidden_live_calls:
            self.assertNotIn(marker, segment)

    def test_social_planner_contract_never_claims_live_connection(self):
        module_source = _source(SOCIAL_CONNECTORS)
        segment = _function_segment(SOCIAL_CONNECTORS, "validation_preview")

        self.assertIn('mode in LIVE_MUTATION_MODES', segment)
        self.assertIn('"verification_state": "unverified"', segment)
        self.assertIn('"provider_call_allowed": False', segment)
        self.assertIn('"mutation_allowed": False', segment)
        self.assertIn('"spend_allowed": False', segment)
        self.assertIn("live_mutation_allowed=False", module_source)
        self.assertIn("credential_reference_required=True", module_source)

        forbidden_network_imports = (
            "import httpx",
            "import requests",
            "import aiohttp",
            "from httpx",
            "from requests",
            "from aiohttp",
        )
        for marker in forbidden_network_imports:
            self.assertNotIn(marker, module_source)

    def test_social_simulator_is_explicitly_non_live(self):
        health = _function_segment(SOCIAL_ACCOUNTS, "simulate_health_payload")
        capability = _function_segment(SOCIAL_ACCOUNTS, "simulate_capability")

        self.assertIn('"metadata-health-simulation-passed"', health)
        self.assertIn('"verification_state": "simulated"', capability)
        self.assertIn('"source": "gs03-deterministic-connector-simulator"', capability)
        self.assertIn('"live_verified": False', capability)
        self.assertIn('"live_provider_call": False', capability)
        self.assertIn("matrix.verified_at = None", capability)

    def test_acceptance_scope_contains_no_execution_hooks(self):
        tree = _tree(HERE)
        imported_roots = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

        self.assertEqual(
            imported_roots,
            {"__future__", "ast", "unittest", "pathlib"},
        )

        forbidden_names = {
            "SessionLocal",
            "retry_delivery",
            "claim_due_deliveries",
            "process_delivery",
        }
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        self.assertTrue(referenced_names.isdisjoint(forbidden_names))


if __name__ == "__main__":
    unittest.main()
