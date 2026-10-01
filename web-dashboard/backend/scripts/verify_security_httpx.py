"""Run httpx and the real application adapter against owned loopback fixtures.

Run only in a disposable image with --network none. No production source,
credentials, database, external domain, active scan or provider is used.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BINARY = "/usr/local/bin/pd-httpx"


def main() -> None:
    from app.services.security_tools import _network_command, _run_network_tool

    provenance = json.loads(Path("/usr/local/share/aionex/httpx-build-provenance.json").read_text())
    assert provenance["local_rebuild_not_upstream_binary"] is True
    assert hashlib.sha256(Path(BINARY).read_bytes()).hexdigest() == provenance["binary_sha256"]
    version = subprocess.run([BINARY, "-version"], capture_output=True, text=True, timeout=15, check=False)
    assert version.returncode == 0 and "v1.12.0+aios.1" in version.stdout + version.stderr
    requests: list[str] = []
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "AIONEX-Synthetic/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            with guard:
                requests.append(self.path)
            body = b"<html><title>AIONEX Local Fixture</title><body>synthetic</body></html>"
            status = 200
            redirect = None
            if self.path.startswith("/redirect/"):
                count = int(self.path.rsplit("/", 1)[1])
                status = 302
                redirect = "/ok" if count == 1 else "/redirect/" + str(count - 1)
            elif self.path == "/missing":
                status = 404
            elif self.path == "/error":
                status = 500
            compressed = self.path == "/gzip"
            if compressed:
                body = gzip.compress(body)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            if redirect:
                self.send_header("Location", redirect)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    cases = []
    try:
        for path, expected in (("/ok", 200), ("/redirect/2", 200), ("/missing", 404), ("/error", 500), ("/gzip", 200)):
            command = _network_command("projectdiscovery-httpx", root + path, "127.0.0.1")
            assert command[0] == "pd-httpx" and command[-2:] == ["-maxr", "3"]
            result = subprocess.run(command + ["-duc", "-nfs", "-title", "-sc", "-t", "1", "-rl", "4", "-timeout", "3", "-retries", "0"],
                                    capture_output=True, text=True, timeout=25, check=False)
            assert result.returncode == 0, "Loopback tool execution failed"
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            assert len(rows) == 1, "Missing or extra loopback observations"
            row = rows[0]
            assert row["status_code"] == expected
            assert row.get("title") == "AIONEX Local Fixture"
            cases.append({"path": path, "status": row["status_code"], "title_verified": True})
        with guard:
            assert "/redirect/2" in requests and "/redirect/1" in requests and "/ok" in requests
        # No replacement command runner/normalizer: execute the application's path.
        application_result = asyncio.run(_run_network_tool("projectdiscovery-httpx", origin=root + "/ok", hostname="127.0.0.1", execution_mode="passive", timeout=30))
        assert application_result["status"] == "completed" and application_result["exit_code"] == 0
        assert len(application_result["stdout_sha256"]) == 64
        # This tool fingerprints services; it must not fabricate vulnerability findings.
        assert application_result["findings"] == [] and application_result["finding_count"] == 0
        invalid = subprocess.run([BINARY, "-aionex-invalid-fixture-flag"], capture_output=True, text=True, timeout=15, check=False)
        assert invalid.returncode != 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
    print(json.dumps({"status": "PASS", "version": "1.12.0+aios.1", "http_cases": cases,
                      "actual_application_argument_builder": True, "actual_application_execution_adapter": True,
                      "no_fabricated_vulnerability_findings": True, "invalid_option_rejected": True,
                      "loopback_server_stopped": True, "external_network": False, "production_changed": False,
                      "full_image_security_passed": False}))


if __name__ == "__main__":
    main()
