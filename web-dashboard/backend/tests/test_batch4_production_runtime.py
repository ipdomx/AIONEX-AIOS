from app.core.production_runtime import ProductionRuntime


def test_monitoring_alert_backup_and_dr_lifecycle():
    runtime = ProductionRuntime()
    alert = runtime.create_alert("CPU saturation", "CPU above threshold", "critical", "monitoring")
    assert runtime.health()["status"] == "degraded"
    runtime.set_alert_status(alert["id"], "resolved")
    assert runtime.health()["status"] == "healthy"

    backup = runtime.create_backup("nightly", "platform")
    assert backup["status"] == "completed"
    assert backup["checksum"]

    runtime.security_event("failed_login_burst", 85, "detected", "user-1", "10.0.0.1")
    assert runtime.security_events[-1]["risk_level"] == "critical"
    assert runtime.audit_events
