"""NS14A: service-worker claiming must never force a conversation reload.

The public static Portal is served from ai.vip-e.net on shared hosting.
ServiceWorker clients.claim() fires controllerchange even on first install.
A forced window.location.reload() interrupts authenticated durable chat recovery.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "vip-frontend/src/components/pwa/pwa-register.tsx"
WORKER = ROOT / "vip-frontend/public/sw.js"
BROWSER = ROOT / "tests/browser-e2e/specs/vip.spec.ts"


def test_sw_controller_change_cannot_reload_an_active_conversation():
    source = REGISTER.read_text(encoding="utf-8")
    assert "window.location.reload()" not in source
    assert '"controllerchange"' in source
    assert 'window.dispatchEvent(new Event("aionex:pwa-update-available"))' in source


def test_sw_registration_and_existing_update_boundaries_remain():
    source = REGISTER.read_text(encoding="utf-8")
    assert 'navigator.serviceWorker.register("/sw.js"' in source
    assert '"updateViaCache"' not in source or 'updateViaCache: "none"' in source
    assert '"SKIP_WAITING"' in source
    assert 'registration?.update()' in source
    assert 'navigator.serviceWorker.removeEventListener(' in source


def test_sw_preserves_api_cache_exclusion_and_activation_contract():
    code = WORKER.read_text(encoding="utf-8")
    assert "self.clients.claim()" in code
    assert 'url.pathname.startsWith("/api/")' in code
    assert '"skipWaiting"' not in code or "self.skipWaiting()" in code
    assert 'request.mode === "navigate"' in code


def test_original_browser_scenarios_are_immutable():
    sha = hashlib.sha256(BROWSER.read_bytes()).hexdigest()
    assert sha == "b73278cf75932b8d9d8310bb64633a84c1f931d3095937088af4756a043fc924"
