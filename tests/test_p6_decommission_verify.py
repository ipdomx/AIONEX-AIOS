"""P6 gate 6.5: read-only old-server decommission verification."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p6_decommission", ROOT / "scripts/ops/p6_old_server_decommission_verify.py")
verify = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = verify
spec.loader.exec_module(verify)

OLD = "198.51.100.7"


def test_old_ip_matching_is_exact_token():
    lines = [OLD, f"v=spf1 ip4:{OLD} -all", "198.51.100.70", "198.51.100.7.5", "x 198.51.100.77"]
    assert verify.answers_reference_old(lines, OLD, []) == [OLD, f"v=spf1 ip4:{OLD} -all"]
    assert verify.answers_reference_old(["ssh old-aios.example.net"], "203.0.113.9", ["old-aios.example.net"])


def fake_opener(answers: dict):
    @contextmanager
    def opener(request, timeout=10):
        url = request.full_url if hasattr(request, "full_url") else request
        name = url.split("name=")[1].split("&")[0]
        rtype = url.split("type=")[1]
        yield io.BytesIO(json.dumps({"Answer": [{"data": d} for d in answers.get((name, rtype), [])]}).encode())
    return opener


def test_dns_check_flags_any_record_on_the_old_ip(monkeypatch):
    monkeypatch.setattr(verify.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("203.0.113.10", 443))])
    clean = verify.check_dns(["api.vip-e.net"], OLD, [], opener=fake_opener({("api.vip-e.net", "A"): ["104.21.1.1"]}))
    assert clean["status"] == "PASS"
    dirty = verify.check_dns(["vip-e.net"], OLD, [], opener=fake_opener({("vip-e.net", "TXT"): [f"v=spf1 ip4:{OLD} ~all"]}))
    assert dirty["status"] == "FAIL" and "vip-e.net:TXT:references_old" in dirty["failures"]


def test_webhooks_without_tokens_are_manual():
    assert verify.check_webhooks("", "", OLD, [])["status"] == "MANUAL"


def test_telegram_webhook_must_be_polling_or_new_api(tmp_path):
    token = tmp_path / "t"
    token.write_text("123:abc")

    def opener_for(url_value):
        @contextmanager
        def opener(request, timeout=10):
            yield io.BytesIO(json.dumps({"result": {"url": url_value, "pending_update_count": 0}}).encode())
        return opener

    assert verify.check_webhooks(str(token), "", OLD, [], opener=opener_for(""))["status"] == "PASS"
    assert verify.check_webhooks(str(token), "", OLD, [], opener=opener_for("https://api.vip-e.net/tg"))["status"] == "PASS"
    assert verify.check_webhooks(str(token), "", OLD, [], opener=opener_for(f"https://{OLD}/tg"))["status"] == "FAIL"


def test_file_scan_reports_paths_not_contents(tmp_path):
    secret = tmp_path / "env"
    secret.write_text(f"PASSWORD=hunter2\nOLD_HOST={OLD}\n")
    result = verify.scan_files((str(tmp_path / "*"),), OLD, [])
    assert result["hits"] == [{"path": str(secret), "matching_lines": 1}]
    assert "hunter2" not in json.dumps(result)


def test_cli_refuses_non_ip(capsys):
    assert verify.main(["--old-ip", "old.example.com"]) == 2
