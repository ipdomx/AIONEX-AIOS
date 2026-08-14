from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs/release-candidate/GROWTH_SOCIAL_COMMAND_CENTER_ROADMAP_2026-08-14.md"


def test_growth_social_roadmap_exists_and_requires_owner_controlled_access():
    text = ROADMAP.read_text(encoding="utf-8")
    assert "APPROVED_FOR_INCREMENTAL_BUILD" in text
    assert "owner service-control override" in text
    assert "No user can self-enable an owner-blocked service." in text
    assert "real_spend_allowed=false" in text
    assert "GS-12" in text
