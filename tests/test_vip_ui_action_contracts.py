from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend" / "src"


def test_vip_has_no_known_dead_or_fake_action_markers() -> None:
    forbidden = (
        'href="#"',
        "onClick={() => {}}",
        "coming soon",
        "not implemented",
        "fake success",
        "demo success",
    )
    findings: list[str] = []
    for path in VIP.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden:
            if marker.lower() in lowered:
                findings.append(f"{path.relative_to(ROOT)}:{marker}")
    assert findings == []


def test_vip_explicit_button_controls_are_not_inert() -> None:
    findings: list[str] = []
    explicit_button = re.compile(
        r"<button\b(?=[^>]{0,500}type\s*=\s*[\"\']button[\"\'])",
        re.I,
    )
    for path in VIP.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        for match in explicit_button.finditer(text):
            closing = text.find("</button>", match.start())
            fragment = text[
                match.start() : closing if closing >= 0 else match.start() + 1500
            ]
            if "onClick=" not in fragment:
                findings.append(
                    f"{path.relative_to(ROOT)}:"
                    f"{text.count(chr(10), 0, match.start()) + 1}"
                )
    assert findings == []
