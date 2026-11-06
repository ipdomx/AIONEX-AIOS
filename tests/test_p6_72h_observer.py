"""P6 gate 6.2: 72 h observer sample classification and certificate."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p6_72h_observer", ROOT / "scripts/ops/p6_72h_observer.py")
observer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = observer
spec.loader.exec_module(observer)

RUN = "p6-72h-20261120t0900z"
INTERVAL = 120


def sample(epoch: float, *, ok: bool = True, restarts: int = 0, started: str = "2026-11-20T00:00:00Z",
           local_age: float = 3.0, offsite_age: float = 3.5, total: int = 1000, five_xx: int = 1) -> dict:
    status = "EXPECTED" if ok else "UNAVAILABLE"
    return {
        "schema": observer.SCHEMA_SAMPLE,
        "run_id": RUN,
        "epoch": epoch,
        "started_at_utc": f"t{epoch}",
        "http": {"api_health": {"status": status}, "public": {"status": "EXPECTED"}},
        "containers": {"status": "MEASURED", "unhealthy": 0, "restarting": 0,
                       "containers": [{"name": "web-dashboard-backend-1", "restart_count": restarts,
                                       "started_at_utc": started, "oom_killed": False}]},
        "origin_errors": {"status": "MEASURED", "total": total, "5xx": five_xx},
        "backup": {"status": "MEASURED", "local_age_hours": local_age, "offsite_age_hours": offsite_age},
    }


def series(hours: float = 72.5, **overrides) -> list[dict]:
    count = int(hours * 3600 / INTERVAL) + 1
    return [sample(1_800_000_000 + i * INTERVAL, **overrides) for i in range(count)]


def test_nginx_log_parsing_counts_status_classes_only():
    log = "\n".join([
        '172.18.0.31 - abc [20/Nov/2026:09:00:00 +0000] "GET /health HTTP/1.1" 200 12',
        '172.18.0.31 - abd [20/Nov/2026:09:00:01 +0000] "POST /api/v1/auth/login HTTP/1.1" 503 197',
        '172.18.0.31 - abe [20/Nov/2026:09:00:02 +0000] "GET /api/v1/x HTTP/1.1" 404 9',
        "nginx: [warn] something unrelated",
    ])
    assert observer.parse_nginx_statuses(log) == {"total": 3, "5xx": 1, "4xx": 1, "503": 1}


def test_clean_72h_series_passes():
    certificate = observer.certify(series(), run_id=RUN, interval=INTERVAL)
    assert certificate["status"] == "PASS", certificate["failed_criteria"]
    assert certificate["span_hours"] >= 72


def test_short_or_gappy_series_fails():
    assert "continuous_72h_span" in observer.certify(series(hours=60), run_id=RUN, interval=INTERVAL)["failed_criteria"]
    rows = series()
    del rows[100:110]
    assert "no_sampling_gap_over_2_intervals" in observer.certify(rows, run_id=RUN, interval=INTERVAL)["failed_criteria"]


def test_restart_recreate_backup_and_availability_failures():
    rows = series()
    rows[-1] = sample(rows[-1]["epoch"], restarts=1)
    assert "container_restarts_zero" in observer.certify(rows, run_id=RUN, interval=INTERVAL)["failed_criteria"]
    rows = series()
    rows[-1] = sample(rows[-1]["epoch"], started="2026-11-21T00:00:00Z")
    assert "no_container_recreated_or_missing" in observer.certify(rows, run_id=RUN, interval=INTERVAL)["failed_criteria"]
    rows = series()
    rows[50] = sample(rows[50]["epoch"], offsite_age=30)
    assert "r2_backup_fresh_le_26h" in observer.certify(rows, run_id=RUN, interval=INTERVAL)["failed_criteria"]
    rows = series()
    for index in range(0, 30):
        rows[index] = sample(rows[index]["epoch"], ok=False)
    assert "availability:api_health" in observer.certify(rows, run_id=RUN, interval=INTERVAL)["failed_criteria"]
    assert "origin_5xx_rate_le_1pct" in observer.certify(series(five_xx=50), run_id=RUN, interval=INTERVAL)["failed_criteria"]


def test_other_runs_are_ignored():
    rows = series()
    rows.append({**sample(rows[-1]["epoch"] + 60, restarts=9), "run_id": "p6-72h-20261101t0000z"})
    assert observer.certify(rows, run_id=RUN, interval=INTERVAL)["status"] == "PASS"


def test_sample_anomalies():
    clean = sample(1.0)
    assert observer.sample_anomalies(clean) == []
    noisy = sample(1.0, ok=False, local_age=40, total=100, five_xx=20)
    assert set(observer.sample_anomalies(noisy)) == {"http:api_health", "backup_stale:local_age_hours", "origin_5xx_spike"}


def test_cli_refuses_bad_run_id(tmp_path, capsys):
    assert observer.main(["certify", "--run-id", "anything", "--dir", str(tmp_path)]) == 2


def test_take_sample_reuses_ns12_probes_and_confirms_failures(monkeypatch):
    calls = []

    class FakeNS12:
        URLS = {"api_health": ("https://api.vip-e.net/health", [200]), "public": ("https://vip-e.net/", [200])}

        @staticmethod
        def http_probe(url, expected):
            calls.append(url)
            ok = "api" in url or calls.count(url) > 1  # public fails once, then recovers
            return {"status": "EXPECTED" if ok else "UNAVAILABLE", "http_code": 200 if ok else None}

        @staticmethod
        def host_probe():
            return {"status": "MEASURED", "checks": {"containers": {"status": "MEASURED", "total": 1, "running": 1,
                    "unhealthy": 0, "restarting": 0, "restart_count_total": 0, "containers": [
                        {"name": "web-dashboard-backend-1", "state": "running", "health": "healthy",
                         "restart_count": 0, "oom_killed": False, "started_at_utc": "x", "image": "secret-ish"}]}}}

    monkeypatch.setattr(observer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(observer, "origin_error_rate", lambda s: {"status": "MEASURED", "total": 10, "5xx": 0})
    monkeypatch.setattr(observer, "backup_freshness", lambda now: {"status": "MEASURED", "local_age_hours": 1.0,
                                                                     "offsite_age_hours": 1.5})
    result = observer.take_sample(RUN, INTERVAL, ns12=FakeNS12)
    assert result["http"]["public"]["status"] == "EXPECTED"
    assert result["http"]["public"]["first_attempt"]["status"] == "UNAVAILABLE"
    assert result["anomalies"] == []
    assert "image" not in result["containers"]["containers"][0]
