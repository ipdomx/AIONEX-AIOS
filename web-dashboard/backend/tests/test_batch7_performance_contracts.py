from time import perf_counter

from app.core.production_runtime import ProductionRuntime


def test_health_aggregation_is_fast():
    runtime = ProductionRuntime()
    started = perf_counter()
    for _ in range(500):
        health = runtime.health()
        assert health["status"] in {"healthy", "degraded"}
    elapsed = perf_counter() - started
    assert elapsed < 1.0


def test_alert_lifecycle_handles_volume():
    runtime = ProductionRuntime()
    started = perf_counter()
    alerts = [
        runtime.create_alert(f"Alert {index}", "load test", "warning", "quality")
        for index in range(250)
    ]
    for alert in alerts:
        runtime.set_alert_status(alert["id"], "resolved")
    elapsed = perf_counter() - started
    assert elapsed < 2.0
    assert runtime.health()["status"] == "healthy"
