"""FR09: Cloudflare tunnel client identity must be trusted only from one peer."""

from __future__ import annotations

import importlib.util
import ipaddress
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr09_cloudflared_realip_admission.py"
OVERLAY = ROOT / "web-dashboard/docker-compose.fr09-trusted-realip.yml"
ENTRYPOINT = ROOT / "web-dashboard/docker/nginx-fr09-realip-entrypoint.sh"
SOURCE_NGINX = ROOT / "web-dashboard/docker/nginx.conf"

spec = importlib.util.spec_from_file_location("fr09_cloudflared_realip", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(name: str, service: str, address: str, *, network: str = "web-dashboard_aionex-network") -> dict:
    return {
        "Name": "/" + name,
        "Config": {
            "Labels": {
                "com.docker.compose.project": "web-dashboard",
                "com.docker.compose.service": service,
            }
        },
        "State": {"Running": True},
        "NetworkSettings": {
            "Networks": {network: {"IPAddress": address, "IPPrefixLen": 16}}
        },
    }


def pair() -> tuple[dict, dict]:
    return (
        record("web-dashboard-nginx-1", "nginx", "172.18.0.17"),
        record("web-dashboard-cloudflared-1", "cloudflared", "172.18.0.31"),
    )


class TrustedCloudflaredRealIP(unittest.TestCase):
    def test_only_exact_cloudflared_ipv4_32_is_trusted(self):
        peer = module.admitted_tunnel_peer(*pair())
        self.assertEqual(str(peer), "172.18.0.31")
        config = module.render_trusted_peer(peer).decode("ascii")
        self.assertIn("set_real_ip_from 172.18.0.31/32;", config)
        self.assertIn("real_ip_header CF-Connecting-IP;", config)
        self.assertNotIn("172.18.0.0/16", config)
        self.assertNotIn("0.0.0.0/0", config)
        self.assertNotIn("X-Forwarded-For", config)

    def test_tunnel_spoofed_compose_service_rejected(self):
        nginx, tunnel = pair()
        tunnel["Config"]["Labels"]["com.docker.compose.service"] = "project-worker"
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_unrelated_private_network_rejected(self):
        nginx, tunnel = pair()
        tunnel["NetworkSettings"]["Networks"] = {
            "different_docker_network": {"IPAddress": "172.18.0.31", "IPPrefixLen": 16}
        }
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_tunnel_with_different_ipv4_subnet_rejected(self):
        nginx, tunnel = pair()
        tunnel["NetworkSettings"]["Networks"]["web-dashboard_aionex-network"]["IPAddress"] = "172.19.0.31"
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_public_peer_ip_rejected(self):
        nginx, tunnel = pair()
        tunnel["NetworkSettings"]["Networks"]["web-dashboard_aionex-network"]["IPAddress"] = "8.8.8.8"
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_stopped_peer_rejected(self):
        nginx, tunnel = pair()
        tunnel["State"]["Running"] = False
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_header_injection_never_accepted_as_ip(self):
        nginx, tunnel = pair()
        tunnel["NetworkSettings"]["Networks"]["web-dashboard_aionex-network"]["IPAddress"] = "172.18.0.31; allow all"
        with self.assertRaises(module.RealIPAdmissionError):
            module.admitted_tunnel_peer(nginx, tunnel)

    def test_fail_closed_for_loopback_and_unspecified(self):
        for ip in ("127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255"):
            with self.subTest(ip=ip):
                with self.assertRaises(module.RealIPAdmissionError):
                    module.render_trusted_peer(ipaddress.IPv4Address(ip))

    def test_separate_opt_in_overlay_not_default(self):
        main = SOURCE_NGINX.read_text(encoding="utf-8")
        overlay = OVERLAY.read_text(encoding="utf-8")
        shell = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertNotIn("set_real_ip_from", main)
        self.assertIn("AIOS_NGINX_TRUSTED_REALIP_DIR:?", overlay)
        self.assertIn("/etc/nginx/aionex-realip:ro", overlay)
        self.assertIn("include /etc/nginx/aionex-realip/*.conf;", shell)
        self.assertIn("nginx -t -c", shell)
        self.assertIn("nginx.conf", shell)
        self.assertNotIn("curl ", shell)
        self.assertNotIn("allow all", shell)

    def test_writer_never_signals_or_restarts_services(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("docker restart", source)
        self.assertNotIn("docker exec", source)
        self.assertNotIn("systemctl", source)
        self.assertNotIn("nginx -s reload", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("STAGED_NOT_RELOADED", source)


if __name__ == "__main__":
    unittest.main()
