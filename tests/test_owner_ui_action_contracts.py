from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend" / "src"


def test_no_known_inert_or_fake_success_markers_on_production_surfaces() -> None:
    forbidden = (
        'href="#"',
        "onClick={() => {}}",
        "This page is under development",
        "coming soon",
        "not implemented",
        "fake success",
    )
    findings: list[str] = []
    for path in FRONTEND.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden:
            if marker.lower() in lowered:
                findings.append(f"{path.relative_to(ROOT)}:{marker}")
    assert findings == []


def test_owner_operations_uses_live_foreign_key_selectors_and_backend_submit() -> None:
    text = (FRONTEND / "app/owner/operations/page.tsx").read_text(encoding="utf-8")
    for token in (
        'useOwnerResource<OwnerOrganizationOption>("organizations")',
        'useOwnerResource<OwnerRoleOption>("access")',
        "organizationId",
        "roleId",
        "executeOwnerOperation",
        "Select a live organization",
        "Select a live role",
    ):
        assert token in text


def test_ai_agents_has_no_historical_fixture_and_every_mutation_is_live_bound() -> None:
    text = (FRONTEND / "app/ai/agents/page.tsx").read_text(encoding="utf-8")
    for historical in (
        'name: "Code Reviewer AI"',
        'name: "Customer Support Bot"',
        'const agents = [',
        'const providers = [',
    ):
        assert historical not in text
    for token in (
        "runtimeServices.listAgents",
        "runtimeServices.listProviders",
        "runtimeServices.createAgent",
        "runtimeServices.executeAgent",
        "runtimeServices.updateAgent",
        "runtimeServices.deleteAgent",
    ):
        assert token in text


def test_explicit_button_controls_are_not_inert() -> None:
    findings: list[str] = []
    explicit_button = re.compile(r"<button\b(?=[^>]{0,500}type\s*=\s*[\"\']button[\"\'])", re.I)
    for path in FRONTEND.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        for match in explicit_button.finditer(text):
            closing = text.find("</button>", match.start())
            fragment = text[match.start() : closing if closing >= 0 else match.start() + 1500]
            if "onClick=" not in fragment:
                findings.append(f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, match.start()) + 1}")
    assert findings == []
