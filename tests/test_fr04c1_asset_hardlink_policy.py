from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"


def test_fr04c1_asset_snapshots_reject_hard_links_explicitly() -> None:
    source = SNAPSHOT.read_text(encoding="utf-8")
    assert "metadata.st_nlink != 1" in source
    assert "unsafe hard-linked file" in source
