import asyncio
from pathlib import Path

from aios.infrastructure.operations import Phase8FinalIntegration
from aios.infrastructure.operations.alerting import (
    AlertManager,
    AlertRulesEngine,
    AlertSeverity,
    ComparisonOperator,
    NotificationDispatcher,
)
from aios.infrastructure.operations.backup import BackupManager
from aios.infrastructure.operations.health import ClusterHealthManager, ServiceHealthMonitor


def run(coro):
    return asyncio.run(coro)


def test_phase8_part5_initialize_and_validate():
    integration = Phase8FinalIntegration()
    run(integration.initialize())
    result = run(integration.validate())
    assert result["phase"] == 8
    assert result["part"] == 5
    assert result["status"] == "PASSED"
    assert all(result["checks"].values())
    assert result["errors"] == []
    run(integration.shutdown())


def test_phase8_validation_fails_before_initialization():
    integration = Phase8FinalIntegration()
    result = run(integration.validate())
    assert result["status"] == "FAILED"
    assert result["checks"]["initialized"] is False


def test_backup_restore_and_tamper_detection(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.txt").write_text("AIONEX", encoding="utf-8")
    manager = BackupManager()
    record = run(manager.create_backup(str(source), str(tmp_path / "backups")))
    assert run(manager.verify_backup(record.backup_id))

    backup_file = Path(record.destination) / "sample.txt"
    backup_file.write_text("tampered", encoding="utf-8")
    assert not run(manager.verify_backup(record.backup_id))

    backup_file.write_text("AIONEX", encoding="utf-8")
    restored = tmp_path / "restored"
    run(manager.restore_backup(record.backup_id, str(restored)))
    assert (restored / "sample.txt").read_text(encoding="utf-8") == "AIONEX"


def test_alert_rules_cooldown_and_lifecycle():
    manager = AlertManager()
    engine = AlertRulesEngine(manager)
    rule = run(
        engine.create_rule(
            "High CPU",
            "cpu",
            ComparisonOperator.GTE,
            90,
            AlertSeverity.CRITICAL,
            "node-1",
            cooldown_seconds=60,
        )
    )
    first = run(engine.evaluate("cpu", 95))
    second = run(engine.evaluate("cpu", 99))
    assert len(first) == 1
    assert second == []
    alert_id = first[0]
    run(manager.acknowledge(alert_id))
    assert run(manager.summary())["acknowledged"] == 1
    run(manager.resolve(alert_id))
    summary = run(manager.summary())
    assert summary["resolved"] == 1
    assert summary["critical_open"] == 0
    assert rule.last_triggered_at is not None


def test_notification_dispatcher_retries_and_missing_handler():
    dispatcher = NotificationDispatcher(max_retries=3)
    attempts = {"count": 0}

    async def flaky_handler(recipient, subject, payload):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")

    run(dispatcher.register_handler("email", flaky_handler))
    result = run(dispatcher.dispatch("email", "owner@example.com", "subject", {}))
    assert result == {"status": "SENT", "attempt": 3}
    missing = run(dispatcher.dispatch("sms", "owner", "subject", {}))
    assert missing["status"] == "FAILED"


def test_cluster_expiration_and_service_failure_threshold():
    cluster = ClusterHealthManager()
    run(cluster.register_node("n1", "node-1"))
    cluster.nodes["n1"].last_seen = 0
    run(cluster.check_expired(timeout=1))
    assert run(cluster.summary())["offline_nodes"] == 1

    monitor = ServiceHealthMonitor(failure_threshold=2)

    async def failing_check():
        return False

    run(monitor.register_service("database", failing_check))
    first = run(monitor.check_service("database"))
    second = run(monitor.check_service("database"))
    assert first.status.value in {"DEGRADED", "UNHEALTHY"}
    assert second.status.value == "UNHEALTHY"
