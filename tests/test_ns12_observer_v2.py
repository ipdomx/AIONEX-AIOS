import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "ns12_observer_v2.py"
SPEC = importlib.util.spec_from_file_location("ns12_observer_v2", MODULE_PATH)
observer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(observer)


class CrossTargetDNSStallCorrelationTests(unittest.TestCase):
    def test_correlates_timeout_with_two_slow_successful_siblings(self):
        http = {
            "vip_es": {
                "status": "UNAVAILABLE",
                "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT",
                "dns_seconds": 0.0,
            },
            "vip_ar": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": 2.956479,
            },
            "vip_fr": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": 2.196362,
            },
        }
        result = observer.cross_target_dns_stall_correlation(http)
        self.assertEqual(result["status"], "CORRELATED")
        self.assertEqual(result["timed_out_endpoints"], ["vip_es"])
        self.assertEqual(
            [item["endpoint"] for item in result["slow_successful_endpoints"]],
            ["vip_ar", "vip_fr"],
        )
        self.assertTrue(result["inference_only"])
        self.assertFalse(result["cause_established"])
        self.assertFalse(result["changes_primary_result"])

    def test_fails_closed_for_timeout_with_one_slow_sibling(self):
        http = {
            "vip_es": {
                "status": "UNAVAILABLE",
                "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT",
            },
            "vip_ar": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": 2.5,
            },
        }
        result = observer.cross_target_dns_stall_correlation(http)
        self.assertEqual(result["status"], "NOT_CORRELATED")
        self.assertEqual(result["minimum_slow_successful_siblings"], 2)

    def test_fails_closed_without_timeout(self):
        http = {
            "vip_ar": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": 2.5,
            },
            "vip_fr": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": 2.25,
            },
        }
        result = observer.cross_target_dns_stall_correlation(http)
        self.assertEqual(result["status"], "NOT_CORRELATED")
        self.assertEqual(result["timed_out_endpoints"], [])

    def test_ignores_malformed_or_non_successful_dns_timings(self):
        http = {
            "vip_es": {
                "status": "UNAVAILABLE",
                "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT",
            },
            "vip_ar": {
                "status": "EXPECTED",
                "curl_phase": "COMPLETE",
                "dns_seconds": "2.5",
            },
            "vip_fr": {
                "status": "UNAVAILABLE",
                "curl_phase": "DNS_FAILURE",
                "dns_seconds": 3.0,
            },
        }
        result = observer.cross_target_dns_stall_correlation(http)
        self.assertEqual(result["status"], "NOT_CORRELATED")
        self.assertEqual(result["slow_successful_endpoints"], [])


class DNSPreconnectDiagnosticTests(unittest.TestCase):
    def test_not_triggered_preserves_primary_semantics(self):
        http = {"vip_en": {"status": "EXPECTED", "curl_phase": "COMPLETE"}}
        with patch.object(observer, "invoke") as invoke:
            result = observer.dns_preconnect_diagnostic(http)
        self.assertEqual(result["status"], "NOT_TRIGGERED")
        self.assertFalse(result["changes_primary_result"])
        invoke.assert_not_called()

    def test_triggered_resolves_once_per_host_and_bypasses_dns(self):
        http = {
            "vip_de": {"status": "UNAVAILABLE", "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT"},
            "vip_en": {"status": "UNAVAILABLE", "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT"},
        }
        def fake_invoke(argv, timeout, input_text=None):
            if argv[0] == "getent":
                return {
                    "exit_code": 0,
                    "stdout": "104.18.1.2 STREAM ai.vip-e.net\n104.18.1.2 DGRAM ai.vip-e.net\n",
                    "seconds": 0.02,
                    "error_type": None,
                }
            self.assertEqual(argv[0], "curl")
            self.assertIn("--resolve", argv)
            return {
                "exit_code": 0,
                "stdout": "200|0.000001|0.010000|0.030000|0.040000|0.050000",
                "seconds": 0.05,
                "error_type": None,
            }
        with patch.object(observer, "invoke", side_effect=fake_invoke) as invoke:
            result = observer.dns_preconnect_diagnostic(http)
        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(result["triggered_by"], ["vip_de", "vip_en"])
        self.assertEqual(list(result["hosts"]), ["ai.vip-e.net"])
        host = result["hosts"]["ai.vip-e.net"]
        self.assertEqual(host["resolver"]["status"], "RESOLVED")
        self.assertEqual(host["dns_bypass_https"]["status"], "EXPECTED")
        self.assertEqual(host["dns_bypass_https"]["selected_ipv4"], "104.18.1.2")
        self.assertEqual(invoke.call_count, 2)
        self.assertFalse(result["changes_primary_result"])

    def test_resolution_failure_is_retained_without_bypass(self):
        http = {
            "api_health": {"status": "UNAVAILABLE", "curl_phase": "DNS_OR_PRE_CONNECT_TIMEOUT"},
        }
        with patch.object(observer, "invoke", return_value={
            "exit_code": 2, "stdout": "", "seconds": 3.0, "error_type": "PROCESS_EXIT"
        }) as invoke:
            result = observer.dns_preconnect_diagnostic(http)
        host = result["hosts"]["api.vip-e.net"]
        self.assertEqual(host["resolver"]["status"], "UNAVAILABLE")
        self.assertEqual(host["dns_bypass_https"]["status"], "NOT_RUN")
        self.assertEqual(invoke.call_count, 1)

    def test_receipt_schema_is_v2(self):
        host = {
            "status": "MEASURED",
            "checks": {
                "containers": {"status": "MEASURED", "running": 36, "unhealthy": 0,
                               "restarting": 0, "restart_count_total": 0,
                               "containers": [], "without_healthcheck": 0},
                "owner_next_version": {"status": "MEASURED", "value": "15.5.27"},
                "owner_rollback_image": {"status": "MEASURED", "value": "sha256:test"},
                "resources": {"status": "MEASURED", "value": {
                    "filesystems": [{"total_bytes": 100, "available_bytes": 50,
                                     "total_inodes": 100, "free_inodes": 50}],
                    "memory": {"MemTotal_bytes": 100, "MemAvailable_bytes": 50},
                }},
                "raid": {"status": "MEASURED", "value": [
                    {"level": "raid0", "array_state": "clean"}
                ]},
            },
        }
        http = {name: {"status": "EXPECTED"} for name in observer.URLS}
        receipt = observer.make_receipt(http, host, "2026-10-14T00:00:00+00:00")
        self.assertEqual(receipt["schema"], "aionex.ns12.bounded_observer.v2")
        self.assertEqual(receipt["cross_target_dns_stall_correlation"]["status"], "NOT_CORRELATED")


if __name__ == "__main__":
    unittest.main()
