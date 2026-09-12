from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
BACKUP_WORKER = ROOT / "web-dashboard" / "backend" / "app" / "services" / "backup_worker.py"
OFFSITE = ROOT / "web-dashboard" / "backend" / "app" / "services" / "offsite_backup.py"


ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def _backup_worker_block() -> str:
    return _service_block("backup-worker", "communication-worker")


def test_fr04b2_backup_worker_mounts_only_project_and_course_additions() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _backup_worker_block()
    assert "entrypoint: [\"/bin/sh\", \"-ceu\"]" in init
    assert "three_d_asset_data:/var/lib/aionex/three-d-assets:rw" in init
    assert "project_execution_data:/var/lib/aionex/project-executions:rw" in init
    assert "course_package_data:/var/lib/aionex/course-packages:rw" in init
    assert "install -d -m 0700 -o 1000 -g 1000" in init
    assert "$$path" in init
    assert "cap_drop: [\"ALL\"]" in init
    assert 'BACKUP_PROJECT_EXECUTION_ASSETS_ENABLED: "true"' in backup
    assert 'BACKUP_COURSE_PACKAGES_ENABLED: "true"' in backup
    assert "PROJECT_EXECUTION_OUTPUT_ROOT: /var/lib/aionex/project-executions" in backup
    assert "ACADEMY_COURSE_PACKAGE_ROOT: /var/lib/aionex/course-packages" in backup
    assert "project_execution_data:/var/lib/aionex/project-executions:ro" in backup
    assert "course_package_data:/var/lib/aionex/course-packages:ro" in backup
    assert "backup-asset-root-init: {condition: service_completed_successfully}" in backup
    assert "project_npm_cache_data" not in backup
    assert "portal_asset_data" not in backup


def test_fr04b2_settings_and_snapshot_roots_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    assert "BACKUP_PROJECT_EXECUTION_ASSETS_ENABLED" in settings
    assert "BACKUP_COURSE_PACKAGES_ENABLED" in settings
    assert "ACADEMY_COURSE_PACKAGE_ROOT" in settings
    assert '"project_execution_data"' in snapshot
    assert '"course_package_data"' in snapshot
    assert '"aionex-platform-asset-roots"' in snapshot
    assert "stat.S_ISLNK" in snapshot
    assert "stat.S_ISREG" in snapshot
    assert "payload_bytes" in snapshot and "file_count" in snapshot


def test_fr04b2_entrypoint_accepts_prepared_read_only_asset_roots() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "Private project execution root is not owned or permissioned correctly" in entrypoint
    assert "Private academy course package root is not owned or permissioned correctly" in entrypoint
    assert "project_output_meta" in entrypoint
    assert "course_package_meta" in entrypoint


def test_fr04b2_restore_and_offsite_evidence_keep_root_totals() -> None:
    backup_worker = BACKUP_WORKER.read_text(encoding="utf-8")
    offsite = OFFSITE.read_text(encoding="utf-8")
    assert 'snapshot_evidence["roots"] = snapshot.roots' in backup_worker
    assert 'validation_details["asset_snapshot_roots"] = snapshot_validation.roots' in backup_worker
    assert 'snapshot_evidence["roots"] = snapshot.roots' in offsite
