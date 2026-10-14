"""FR07: preserve Academy artifact filenames across the production cross-origin API.

The production VIP image embeds https://api.vip-e.net/api/v1. Browsers expose
Content-Disposition to JavaScript only when the credentialed API explicitly
allows that response header. The Academy must also use a context-specific
filename if the header is unavailable, never a project-delivery filename.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "web-dashboard/backend/main.py"
ACADEMY = ROOT / "vip-frontend/src/components/pages/academy-client.tsx"
API = ROOT / "vip-frontend/src/lib/api.ts"
BROWSER = ROOT / "tests/browser-e2e/specs/vip.spec.ts"


def _cors_keywords() -> dict[str, ast.expr]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "app" and n.func.attr == "add_middleware"
        and n.args and isinstance(n.args[0], ast.Name)
        and n.args[0].id == "CORSMiddleware"
    ]
    assert len(calls) == 1, "expected one canonical production CORS middleware"
    return {k.arg: k.value for k in calls[0].keywords if k.arg is not None}


def test_production_cors_exposes_only_explicit_attachment_header() -> None:
    fields = _cors_keywords()
    assert ast.unparse(fields["allow_origins"]) == "settings.CORS_ORIGINS"
    assert ast.literal_eval(fields["allow_credentials"]) is True
    exposed = ast.literal_eval(fields["expose_headers"])
    assert exposed == ["Content-Disposition"]
    assert "*" not in exposed


def test_academy_fallback_never_uses_generic_project_delivery_filename() -> None:
    source = ACADEMY.read_text(encoding="utf-8")
    start = source.index("  async function download(item: AcademyCoursePackage)")
    end = source.index("  if (isLoading", start)
    method = source[start:end]
    assert 'filename !== "aionex-project-delivery.zip"' in method
    assert 'item.course_id.startsWith("course-")' in method
    assert 'course-${item.course_id}' in method
    assert '${coursePrefix}-v${item.version}.zip' in method
    assert 'anchor.download = filename && filename !== "aionex-project-delivery.zip"' in method
    assert "await downloadAcademyCoursePackage(item.id)" in method


def test_other_download_consumers_keep_existing_contract() -> None:
    api = API.read_text(encoding="utf-8")
    assert 'filename: match?.[1] || "aionex-project-delivery.zip"' in api
    assert 'response.headers.get("Content-Disposition")' in api


def test_original_browser_acceptance_spec_was_not_changed() -> None:
    assert hashlib.sha256(BROWSER.read_bytes()).hexdigest() == (
        "b73278cf75932b8d9d8310bb64633a84c1f931d3095937088af4756a043fc924"
    )
