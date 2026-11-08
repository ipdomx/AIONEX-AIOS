"""P6 gate 6.1: time-boxed rate-limit exemption + capacity tuning overlays."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "web-dashboard/docker/nginx-p6-loadtest-entrypoint.sh"
NGINX = ROOT / "web-dashboard/docker/nginx.conf"
TUNING = ROOT / "web-dashboard/docker-compose.p6-capacity-tuning.yml"
WINDOW = ROOT / "web-dashboard/docker-compose.p6-loadtest-window.yml"
spec = importlib.util.spec_from_file_location("p6_loadtest_exemption", ROOT / "scripts/capacity/p6_loadtest_exemption.py")
exemption = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = exemption
spec.loader.exec_module(exemption)

RUN = "p6-20261120t0900z"


def test_renderer_accepts_only_public_unicast_with_bounded_expiry():
    now = time.time()
    text = exemption.render(["192.0.32.10"], expires_epoch=int(now + 3600), run_id=RUN, now=now)
    assert "192.0.32.10/32 1;" in text and f"# expires_epoch={int(now + 3600)}" in text
    for bad in ("10.0.0.5", "127.0.0.1", "172.18.0.31", "169.254.1.1", "0.0.0.0", "not-an-ip"):
        with pytest.raises(exemption.ExemptionError):
            exemption.render([bad], expires_epoch=int(now + 3600), run_id=RUN, now=now)
    with pytest.raises(exemption.ExemptionError):
        exemption.render(["192.0.32.10"], expires_epoch=int(now + 9 * 3600), run_id=RUN, now=now)
    with pytest.raises(exemption.ExemptionError):
        exemption.render(["192.0.32.10"], expires_epoch=int(now - 1), run_id=RUN, now=now)
    with pytest.raises(exemption.ExemptionError):
        exemption.render([f"192.0.32.{i}" for i in range(10, 15)], expires_epoch=int(now + 60), run_id=RUN, now=now)


def _run_entrypoint(tmp_path: Path, exempt_text: str | None, *, realip: bool = True):
    realip_dir = tmp_path / "realip"
    exempt_dir = tmp_path / "exempt"
    realip_dir.mkdir()
    exempt_dir.mkdir()
    if realip:
        (realip_dir / "trusted-cloudflared.conf").write_text(
            "set_real_ip_from 172.18.0.31/32;\nreal_ip_header CF-Connecting-IP;\nreal_ip_recursive off;\n")
    if exempt_text is not None:
        (exempt_dir / "exempt.conf").write_text(exempt_text)
    dest = tmp_path / "out.conf"
    env = {**os.environ, "P6_NGINX_SOURCE": str(NGINX), "P6_NGINX_DEST": str(dest),
           "P6_NGINX_REALIP_DIR": str(realip_dir), "P6_NGINX_EXEMPT_DIR": str(exempt_dir)}
    result = subprocess.run(["sh", str(ENTRYPOINT), "--render"], env=env, capture_output=True, text=True, timeout=30)
    return result, dest


def test_entrypoint_rekeys_only_the_three_per_ip_zones(tmp_path):
    text = exemption.render(["192.0.32.10"], expires_epoch=int(time.time() + 3600), run_id=RUN)
    result, dest = _run_entrypoint(tmp_path, text)
    assert result.returncode == 0, result.stderr
    rendered = dest.read_text()
    assert rendered.count("$aionex_p6_limit_key zone=") == 3
    assert "limit_req_zone $binary_remote_addr zone=support_per_ip" in rendered
    assert "limit_req_zone $binary_remote_addr zone=billing_webhook_per_ip" in rendered
    assert 'map $aionex_p6_loadtest_source $aionex_p6_limit_key' in rendered
    assert NGINX.read_text().count("$aionex_p6_limit_key") == 0


@pytest.mark.parametrize("case", ["expired", "no_realip", "bad_line", "missing", "too_many"])
def test_entrypoint_fails_closed(tmp_path, case):
    good = exemption.render(["192.0.32.10"], expires_epoch=int(time.time() + 3600), run_id=RUN)
    text = {
        "expired": "# expires_epoch=1000000000\n192.0.32.10/32 1;\n",
        "no_realip": good,
        "bad_line": good + "0.0.0.0/0 1;\n",
        "missing": None,
        "too_many": good + "".join(f"192.0.32.{i}/32 1;\n" for i in range(20, 25)),
    }[case]
    result, _ = _run_entrypoint(tmp_path, text, realip=case != "no_realip")
    assert result.returncode == 2
    assert "refused" in result.stderr


def test_capacity_tuning_keeps_postgres_budget_and_redis_headroom():
    text = TUNING.read_text()
    assert 'WORKERS: "32"' in text and 'DATABASE_POOL_SIZE: "5"' in text and 'DATABASE_MAX_OVERFLOW: "2"' in text
    assert 32 * (5 + 2) <= 230 and 'DATABASE_POOL_CONNECTION_BUDGET: "230"' in text
    assert "max_connections=300" in text and 230 + 60 <= 300
    # 6.1 run 2026-11-07: per-process file limit and ephemeral-port headroom.
    assert "nofile: {soft: 65536, hard: 65536}" in text
    assert 'net.ipv4.tcp_tw_reuse: "1"' in text
    # PROJECT_EXECUTION_ADMISSION_CONCURRENCY 14 must leave room for auth/realtime.
    assert 'REDIS_POOL_SIZE: "64"' in text and 64 - 14 >= 30
    assert 'PASSWORD_HASH_THREADS: "2"' in text
    assert "ports:" not in text
    # The tunnel only gets CPU/memory; its command, token and environment stay untouched.
    tunnel = text.split("\n  cloudflared:\n", 1)[1]
    keys = [line.split(":", 1)[0].strip() for line in tunnel.splitlines()
            if line.startswith("    ") and not line.strip().startswith("#")]
    assert keys == ["cpus", "mem_limit"]
    assert 'cpus: "4.0"' in tunnel and "mem_limit: 2g" in tunnel


def test_loadtest_window_overlay_requires_realip_and_exemption():
    text = WINDOW.read_text()
    assert "AIOS_NGINX_TRUSTED_REALIP_DIR:?" in text
    assert "AIOS_P6_LOADTEST_EXEMPT_DIR:?" in text
    assert "nginx-p6-loadtest-entrypoint.sh" in text
    assert "backend:" not in text
