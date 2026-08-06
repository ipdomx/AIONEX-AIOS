from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_configured_about_page_keeps_visible_h1() -> None:
    source = (ROOT / "vip-frontend/src/components/pages/about-client.tsx").read_text()
    configured_branch = source.split("if (configured.length)", 1)[1].split("const principles", 1)[0]
    assert "<h1" in configured_branch
    assert 't("title")' in configured_branch


def test_facebook_button_meets_normal_text_contrast_contract() -> None:
    source = (ROOT / "vip-frontend/src/components/auth/oauth-buttons.tsx").read_text()
    assert 'facebook: "bg-[#166FE5] text-white"' in source
    assert "bg-[#1877F2] text-white" not in source
