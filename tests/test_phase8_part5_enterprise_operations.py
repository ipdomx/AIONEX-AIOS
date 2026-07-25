import asyncio
from pathlib import Path
from aios.infrastructure.operations import Phase8FinalIntegration
from aios.infrastructure.operations.backup import BackupManager


def run(coro):
    return asyncio.run(coro)


def test_phase8_part5_initialize_and_validate():
    integration = Phase8FinalIntegration()
    run(integration.initialize())
    result = run(integration.validate())
    assert result["phase"] == 8
    assert result["part"] == 5
    assert result["status"] in {"PASSED", "FAILED"}
    run(integration.shutdown())


def test_backup_restore(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.txt").write_text("AIONEX", encoding="utf-8")
    manager = BackupManager()
    record = run(manager.create_backup(str(source), str(tmp_path / "backups")))
    assert run(manager.verify_backup(record.backup_id))
    restored = tmp_path / "restored"
    run(manager.restore_backup(record.backup_id, str(restored)))
    assert (restored / "sample.txt").read_text(encoding="utf-8") == "AIONEX"
