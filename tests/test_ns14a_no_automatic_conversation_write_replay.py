"""NS-14A: avoid implicit write replay after authentication expiry.

This offline source contract does not replace the six original browser tests.
The read helpers remain eligible for 401 refresh, while every conversation
mutation must wait for explicit user action after an uncertain result.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "vip-frontend/src/lib/project-conversations.ts"
PAGE = ROOT / "vip-frontend/src/components/pages/conversations-client.tsx"
BROWSER = ROOT / "tests/browser-e2e/specs/vip.spec.ts"


def _members() -> dict[str, str]:
    source = CLIENT.read_text(encoding="utf-8")
    body = source.split("export const conversationApi = {", 1)[1]
    matches = list(re.finditer(r"(?m)^  (policy|agents|list|history|create|send|close):", body))
    return {
        match.group(1): body[match.end(): matches[index + 1].start() if index + 1 < len(matches) else body.index("\n};")]
        for index, match in enumerate(matches)
    }


def test_conversation_mutations_never_replay_automatically_on_401():
    members = _members()
    for name in ("create", "send", "close"):
        section = members[name]
        assert "WRITE_TIMEOUT_MS" in section, name
        assert "jsonRequest<" in section, name
        assert "{ signal, retry: false }" in section, f"{name} could silently replay a POST"


def test_read_poll_and_synthetic_original_browser_guards_are_preserved():
    members = _members()
    for name in ("policy", "agents", "list", "history"):
        section = members[name]
        assert "READ_TIMEOUT_MS" in section, name
        assert "retry: false" not in section, name
    page = PAGE.read_text(encoding="utf-8")
    assert "if (sendIntent.current?.key !== key)" in page
    assert "sendIntent.current = null;" in page
    assert "conversationApi.history(selected)" in page
    spec = BROWSER.read_text(encoding="utf-8")
    for title in (
        "NS-14A auth expiry refreshes once",
        "NS-14A lost write response retries the identical request id",
        "NS-14A repeated transport failures recover",
    ):
        assert title in spec
