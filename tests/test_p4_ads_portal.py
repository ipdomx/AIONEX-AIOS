"""Static portal contract for P4 Meta Ads: campaigns tabs, charts, locales, nginx."""

from __future__ import annotations

import json
import re
from pathlib import Path

from aios.completion_program import ENDPOINT_BATCH

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
PAGES = VIP / "src/components/pages"
CLIENTS = {
    name: (PAGES / f"{name}.tsx").read_text(encoding="utf-8")
    for name in ("ads-shared", "ads-dashboard", "ads-accounts-panel", "ads-campaign-builder", "campaigns-client")
}
API = (VIP / "src/lib/api.ts").read_text(encoding="utf-8")
NGINX = (ROOT / "web-dashboard/docker/nginx.conf").read_text(encoding="utf-8")
LOCALES = ("ar", "en", "fr", "de", "es", "tr")


def _flatten(value: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _flatten(item, path) if isinstance(item, dict) else {path}
    return keys


def test_every_locale_has_the_ads_strings_and_arabic_is_complete() -> None:
    reference = json.loads((VIP / "src/messages/en.json").read_text(encoding="utf-8"))["ads"]
    expected = _flatten(reference)
    arabic = json.loads((VIP / "src/messages/ar.json").read_text(encoding="utf-8"))["ads"]
    for locale in LOCALES:
        messages = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))["ads"]
        assert _flatten(messages) == expected, locale
    flat_ar = {}

    def walk(prefix: str, value: dict) -> None:
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                walk(path, item)
            else:
                flat_ar[path] = item

    walk("", arabic)
    # Every Arabic string carries Arabic script, except bare metric acronyms.
    for key, text in flat_ar.items():
        assert re.search(r"[؀-ۿ]", text) or text in {"ROAS"}, key
    # Every key the clients call exists.
    used = set()
    for source in CLIENTS.values():
        used |= set(re.findall(r'\b(?:t|tAds)\("([a-zA-Z_.]+)"', source))
    assert used and used <= expected | set(_flatten(json.loads((VIP / "src/messages/en.json").read_text())["campaigns"])), used - expected


def test_clients_use_api_helpers_and_never_inject_html_or_tokens() -> None:
    for route in ("/ads/access", "/ads/connect/meta/start", "/ads/accounts", "/ads/analytics", "/ads/recommendations", "/ads/campaigns"):
        assert route in API, route
    for name, source in CLIENTS.items():
        assert "fetch(" not in source, name
        assert "dangerouslySetInnerHTML" not in source and "innerHTML" not in source, name
        assert "access_token" not in source, name
    builder = CLIENTS["ads-campaign-builder"]
    assert "access.activation_phrase" in builder and "confirmed_budget_minor" in builder
    assert 'hostname !== META_DIALOG_HOST' in CLIENTS["ads-accounts-panel"]
    # Charts are plain SVG: no new chart dependency.
    package = json.loads((VIP / "package.json").read_text(encoding="utf-8"))
    assert not {"recharts", "chart.js", "d3", "echarts"} & set(package["dependencies"])
    assert "<svg" in CLIENTS["ads-shared"]
    client = CLIENTS["campaigns-client"]
    for marker in ("AdsDashboardPanel", "AdsAccountsPanel", "AdsCampaignBuilder", 'role="tablist"', "getAdsAccess"):
        assert marker in client, marker


def test_ads_routes_are_public_and_registered() -> None:
    assert ENDPOINT_BATCH["ads"] == "GS-08"
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert (
        "|ads/(?:access|connect/meta/start|connections|accounts(?:/(?:available|[0-9a-f-]{36}(?:/sync)?))?"
        "|analytics|usage|recommendations|campaigns(?:/[0-9a-f-]{36}/(?:provision|activate|pause))?)|"
    ) in public_server
    assert "owner/ads" not in public_server
