"""Phase 0 item 0.1: the portals must not loop on POST /auth/refresh.

Source contracts complementing the `node --test` suites in
`vip-frontend/scripts/test-auth-refresh-gate.mjs` and
`web-dashboard/frontend/scripts/test-auth-refresh-gate.mjs`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL_API = ROOT / "vip-frontend/src/lib/api.ts"
OWNER_CLIENT = ROOT / "web-dashboard/frontend/src/lib/api-client.ts"
GATES = (
    ROOT / "vip-frontend/src/lib/auth-refresh-gate.ts",
    ROOT / "web-dashboard/frontend/src/lib/auth-refresh-gate.ts",
)
BACKEND_MAIN = ROOT / "web-dashboard/backend/main.py"
# Headers a browser may send cross-origin without being listed in
# Access-Control-Allow-Headers (Fetch "CORS-safelisted request headers").
SAFELISTED = {"accept", "accept-language", "content-language", "content-type"}


def _backend_allowed_headers() -> set[str]:
    tree = ast.parse(BACKEND_MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "allow_headers":
            value = ast.literal_eval(node.value)
            return {str(item).lower() for item in value}
    raise AssertionError("CORSMiddleware allow_headers not found")


def _sent_header_names(source: str) -> set[str]:
    names = set(re.findall(r'headers\.(?:set|append)\(\s*"([A-Za-z-]+)"', source))
    names |= set(re.findall(r'"(X-[A-Za-z-]+)"\s*[:\]]', source))
    names |= set(re.findall(r'\b(Accept|Authorization)\s*:', source))
    names |= set(re.findall(r'"(Content-Type)"\s*:', source))
    return {name.lower() for name in names}


def test_gate_modules_are_identical_in_both_frontends():
    portal, owner = (path.read_text(encoding="utf-8") for path in GATES)
    assert portal == owner
    for text in (
        "if (!safeHint()) return Promise.resolve(null);",
        "if (inFlight) return inFlight;",
        "if (now() < blockedUntil) return Promise.resolve(null);",
        "new Set([400, 401, 403, 429])",
    ):
        assert text in portal


def test_portal_refresh_is_gated_and_never_recursive():
    source = PORTAL_API.read_text(encoding="utf-8")
    assert "hasSessionHint: hasStoredSession" in source
    assert "refreshGate.run(performRefresh)" in source
    # The old pattern refreshed unconditionally and then replayed the request.
    assert "await refreshSession();" not in source
    assert "refreshInFlight" not in source
    refresh = source[source.index("async function performRefresh"):source.index("const refreshGate")]
    assert "refreshSession(" not in refresh and "request<" not in refresh
    assert "throw new RefreshFailure(null)" in refresh


def test_owner_refresh_is_gated_and_never_recursive():
    source = OWNER_CLIENT.read_text(encoding="utf-8")
    assert "createRefreshGate<true>" in source
    assert "this.refreshGate.run(" in source
    assert "private refreshPromise" not in source
    refresh = source[source.index("private async refreshAccessToken"):source.index("resetRefreshBackoff(): void")]
    assert "this.client.request" not in refresh  # raw axios, outside the 401 interceptor


def test_frontends_only_send_headers_the_backend_preflight_allows():
    allowed = _backend_allowed_headers() | SAFELISTED
    assert "x-requested-with" not in _backend_allowed_headers()
    for source_root in (ROOT / "vip-frontend/src", ROOT / "web-dashboard/frontend/src/lib"):
        for path in source_root.rglob("*.ts*"):
            text = path.read_text(encoding="utf-8")
            assert "x-requested-with" not in text.lower(), path
    for path in (PORTAL_API, OWNER_CLIENT):
        sent = _sent_header_names(path.read_text(encoding="utf-8"))
        assert sent, path
        assert sent <= allowed, (path, sorted(sent - allowed))
