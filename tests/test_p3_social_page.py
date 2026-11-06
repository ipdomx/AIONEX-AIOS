"""Static portal contract for the P3 social accounts page (/[locale]/social/)."""

from __future__ import annotations

import json
from pathlib import Path

from aios.completion_program import ENDPOINT_BATCH, VIP_PAGE_BATCH

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
CLIENT = (VIP / "src/components/pages/social-client.tsx").read_text(encoding="utf-8")
PAGE = (VIP / "src/app/[locale]/social/page.tsx").read_text(encoding="utf-8")
API = (VIP / "src/lib/api.ts").read_text(encoding="utf-8")
TYPES = (VIP / "src/types/index.ts").read_text(encoding="utf-8")
NAVBAR = (VIP / "src/components/layout/navbar.tsx").read_text(encoding="utf-8")
FRAME = (VIP / "src/components/layout/site-frame.tsx").read_text(encoding="utf-8")
LOCALES = ("ar", "en", "fr", "de", "es", "tr")


def _flatten(value: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _flatten(item, path) if isinstance(item, dict) else {path}
    return keys


def test_page_is_registered_linked_and_smoke_tested() -> None:
    assert VIP_PAGE_BATCH["[locale]/social/page.tsx"] == "GS-03"
    assert ENDPOINT_BATCH["social"] == "GS-03"
    assert "<SocialClient />" in PAGE and 'path: "social"' in PAGE and "noIndex: true" in PAGE
    assert NAVBAR.count("href={`/${locale}/social`}") == 2  # desktop and mobile
    assert 't("social")' in NAVBAR
    assert "|social|" in FRAME or "(?:social|" in FRAME
    assert '"src/app/[locale]/social/page.tsx"' in (VIP / "scripts/check-integrity.mjs").read_text()
    assert '"/social"' in (VIP / "scripts/smoke-test.mjs").read_text()
    assert '"social"' in (VIP / "scripts/static-smoke-test.mjs").read_text()


def test_every_locale_has_the_social_strings_and_arabic_title() -> None:
    reference = json.loads((VIP / "src/messages/en.json").read_text(encoding="utf-8"))
    expected = _flatten(reference["social"])
    for locale in LOCALES:
        messages = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
        assert _flatten(messages["social"]) == expected, locale
        assert messages["nav"]["social"] and messages["meta"]["socialTitle"]
    arabic = json.loads((VIP / "src/messages/ar.json").read_text(encoding="utf-8"))
    assert arabic["nav"]["social"] == "حساباتي"
    assert arabic["social"]["eyebrow"] == "حساباتي"


def test_client_uses_the_api_helpers_and_never_handles_tokens() -> None:
    for route in (
        "/social/providers",
        "/social/connect/",
        "/social/connections",
        "/social/accounts",
    ):
        assert route in API, route
    for helper in (
        "listSocialProviders",
        "startSocialConnect",
        "listSocialConnectionAssets",
        "connectSocialAssets",
        "listSocialAccounts",
        "checkSocialAccountHealth",
        "disconnectSocialAccount",
    ):
        assert helper in CLIENT, helper
    social_types = TYPES[TYPES.index("export type SocialProviderStatus"):]
    assert "access_token" not in social_types and "ciphertext" not in social_types
    assert "access_token" not in CLIENT
    assert "fetch(" not in CLIENT  # all traffic goes through api.ts and its refresh gate


def test_client_is_honest_and_free_of_polling_and_html_injection() -> None:
    assert "setInterval" not in CLIENT and "setTimeout" not in CLIENT
    assert "dangerouslySetInnerHTML" not in CLIENT and "innerHTML" not in CLIENT
    assert "<img" not in CLIENT
    # Only a configured provider can start a connection; the rest are disabled.
    assert 'provider.status === "configured"' in CLIENT
    assert "disabled={!live || busy !== null}" in CLIENT
    assert 'providers.status.${comingSoon ? "comingSoon"' in CLIENT
    # The authorize redirect is validated before the browser leaves the page.
    assert 'META_DIALOG_HOST = "www.facebook.com"' in CLIENT
    assert 'target.protocol !== "https:"' in CLIENT
    english = json.loads((VIP / "src/messages/en.json").read_text(encoding="utf-8"))["social"]
    assert "not live yet" in english["honesty"]
