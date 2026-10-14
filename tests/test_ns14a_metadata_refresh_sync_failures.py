"""NS14A: unrelated metadata refresh must not hide a failed durable chat poll.

Fail-closed source contract complements the real original six browser tests.
"""
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "vip-frontend/src/components/pages/conversations-client.tsx"
)


def component() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_unrelated_projects_policy_agents_refresh_cannot_clear_chat_transport_failures():
    code = component()
    start = code.index("  const load = useCallback(async () => {")
    end = code.index("  }, [reportError]);", start)
    metadata_only = code[start:end]
    assert "listProjects()" in metadata_only
    assert "conversationApi.list()" in metadata_only
    assert "conversationApi.policy()" in metadata_only
    assert "conversationApi.agents()" in metadata_only
    assert "conversationApi.history(" not in metadata_only
    assert "setSyncFailures(0)" not in metadata_only


def test_real_history_success_and_selection_change_remain_only_reset_sources():
    code = component()
    assert "const selectionChanged = selection.current !== selected;" in code
    assert "if (selectionChanged || !isAuthenticated) {" in code
    assert "setSyncFailures(0);" in code
    start = code.index("    const refresh = async () => {")
    end = code.index("    void refresh();", start)
    poller = code[start:end]
    assert "conversationApi.history(selected)" in poller
    assert "setHistory(next); setPolicy(usage);" in poller
    assert "setSyncFailures(0); setError(\"\");" in poller
    assert "setSyncFailures((value) => value + 1);" in poller
    assert "conversationApi.send(" not in poller


def test_browser_end_to_end_acceptance_remains_original_and_unmodified():
    # A source-level assertion cannot certify the deployed customer experience.
    assert (SOURCE.parents[4] / "tests/browser-e2e/specs/vip.spec.ts").is_file()
