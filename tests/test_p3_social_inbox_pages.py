"""Static contract for P3 roadmap 3.6 and 3.8: unified inbox page, Meta
callbacks at the gateway, the public data-deletion page, the privacy notice
and the Meta App Review pack."""

from __future__ import annotations

import json
from pathlib import Path

from aios.completion_program import ENDPOINT_BATCH, VIP_PAGE_BATCH

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
PAGES = VIP / "src/components/pages"
INBOX = (PAGES / "social-inbox-client.tsx").read_text(encoding="utf-8")
DELETION = (PAGES / "data-deletion-client.tsx").read_text(encoding="utf-8")
LEGAL = (PAGES / "legal-client.tsx").read_text(encoding="utf-8")
API = (VIP / "src/lib/api.ts").read_text(encoding="utf-8")
NAVBAR = (VIP / "src/components/layout/navbar.tsx").read_text(encoding="utf-8")
NGINX = (ROOT / "web-dashboard/docker/nginx.conf").read_text(encoding="utf-8")
PACK = ROOT / "docs/project/META-APP-REVIEW-PACK.md"
ROADMAP = (ROOT / "docs/project/COMPLETION-ROADMAP.md").read_text(encoding="utf-8")
LOCALES = ("ar", "en", "fr", "de", "es", "tr")


def _flatten(value: dict, prefix: str = "") -> dict[str, str]:
    items: dict[str, str] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            items.update(_flatten(item, path))
        else:
            items[path] = item
    return items


def test_pages_are_registered_linked_and_smoke_tested() -> None:
    assert VIP_PAGE_BATCH["[locale]/social/inbox/page.tsx"] == "GS-07"
    assert VIP_PAGE_BATCH["[locale]/legal/data-deletion/page.tsx"] == "29B"
    assert ENDPOINT_BATCH["social_inbox"] == "GS-07"
    assert ENDPOINT_BATCH["social_meta_callbacks"] == "GS-03"
    inbox_page = (VIP / "src/app/[locale]/social/inbox/page.tsx").read_text(encoding="utf-8")
    assert "<SocialInboxClient />" in inbox_page and 'path: "social/inbox"' in inbox_page
    assert "noIndex: true" in inbox_page
    deletion_page = (VIP / "src/app/[locale]/legal/data-deletion/page.tsx").read_text(encoding="utf-8")
    assert "<DataDeletionClient />" in deletion_page and "noIndex" not in deletion_page
    assert NAVBAR.count("href={`/${locale}/social/inbox`}") == 2
    assert 't("socialInbox")' in NAVBAR
    scripts = {
        name: (VIP / f"scripts/{name}").read_text(encoding="utf-8")
        for name in ("check-integrity.mjs", "smoke-test.mjs", "static-smoke-test.mjs")
    }
    assert '"src/app/[locale]/social/inbox/page.tsx"' in scripts["check-integrity.mjs"]
    assert '"src/app/[locale]/legal/data-deletion/page.tsx"' in scripts["check-integrity.mjs"]
    assert '"/social/inbox"' in scripts["smoke-test.mjs"] and '"/legal/data-deletion"' in scripts["smoke-test.mjs"]
    assert '"social/inbox"' in scripts["static-smoke-test.mjs"]
    assert '"legal/data-deletion"' in scripts["static-smoke-test.mjs"]
    assert '"/legal/data-deletion"' in (VIP / "src/app/sitemap.ts").read_text(encoding="utf-8")


def test_every_locale_has_complete_non_english_inbox_strings() -> None:
    reference = json.loads((VIP / "src/messages/en.json").read_text(encoding="utf-8"))
    for namespace in ("socialInbox", "dataDeletion"):
        expected = _flatten(reference[namespace])
        for locale in LOCALES:
            messages = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
            values = _flatten(messages[namespace])
            assert set(values) == set(expected), (locale, namespace)
            assert all(text.strip() for text in values.values()), (locale, namespace)
            if locale != "en":
                # No English fallback for user-visible sentences (brand and
                # platform names are the same in every language).
                same = {key for key, text in values.items() if text == expected[key] and len(text.split()) > 2}
                assert not same, (locale, namespace, sorted(same))
            assert messages["nav"]["socialInbox"] and messages["meta"]["socialInboxTitle"]
            for key in ("privacy5Title", "privacy5Copy", "privacy6Title", "privacy6Copy", "dataDeletionLink"):
                assert messages["legal"][key], (locale, key)
    arabic = json.loads((VIP / "src/messages/ar.json").read_text(encoding="utf-8"))
    assert "Meta" in arabic["socialInbox"]["readiness"]["awaitingTitle"]
    assert "24" in arabic["socialInbox"]["thread"]["windowClosedTitle"]
    assert "AIONEX AI" in arabic["socialInbox"]["reply"]["suggest"]


def test_inbox_client_is_honest_and_never_injects_html() -> None:
    for route in (
        "/social/inbox/status",
        "/social/inbox/conversations",
        "/social/inbox/messages/",
        "/social/inbox/accounts/",
        "/social/meta/data-deletion/status",
    ):
        assert route in API, route
    for client in (INBOX, DELETION, LEGAL):
        assert "fetch(" not in client
        assert "dangerouslySetInnerHTML" not in client and "innerHTML" not in client
        assert "access_token" not in client and "<img" not in client
    for helper in (
        "getSocialInboxStatus",
        "listSocialInboxConversations",
        "getSocialInboxConversation",
        "updateSocialInboxConversation",
        "replySocialInboxConversation",
        "suggestSocialInboxReply",
        "setSocialInboxMessageVisibility",
        "subscribeSocialInboxAccount",
    ):
        assert helper in INBOX, helper
    # Honest states: awaiting Meta permission, the 24-hour window, live not verified.
    for key in ('t("readiness.awaitingTitle")', 't("thread.windowClosedTitle")', '"readiness.liveNotVerified"'):
        assert key in INBOX, key
    assert "windowClosed" in INBOX and "disabled={!canReply" in INBOX
    # A suggestion only fills the reply box; sending is a separate action.
    suggest = INBOX.split("async function suggest()", 1)[1].split("async function toggleHidden", 1)[0]
    assert "setDraft(" in suggest and "replySocialInboxConversation" not in suggest
    assert "getMetaDataDeletionStatus" in DELETION and "{ auth: false }" in API
    assert "/legal/data-deletion" in LEGAL and "MetaDataSections" in LEGAL


def test_meta_callbacks_and_inbox_routes_are_in_the_public_gateway() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    location = "location ~ ^/api/v1/social/meta/(webhooks|deauthorize|data-deletion)$ {"
    assert public_server.count(location) == 1
    block = public_server.split(location, 1)[1].split("\n        }", 1)[0]
    assert "limit_except GET POST" in block and "deny all;" in block
    assert "limit_req zone=meta_callback_per_ip" in block and "client_max_body_size 1m;" in block
    assert "X-AIOS-Auth-Channel public" in block
    assert 'proxy_set_header Cookie "";' in block and 'proxy_set_header Authorization "";' in block
    assert "zone=meta_callback_per_ip:10m" in NGINX
    fragment = (
        "|inbox/(?:status|conversations(?:/[0-9a-f-]{36}(?:/(?:reply|suggest))?)?"
        "|messages/[0-9a-f-]{36}/visibility|accounts/[0-9a-f-]{36}/subscribe)"
        "|meta/data-deletion/status|"
    )
    assert fragment in public_server


def test_app_review_pack_and_roadmap() -> None:
    pack = PACK.read_text(encoding="utf-8")
    for required in (
        "1056852290270430",
        "AIONEX-AIOS",
        "https://api.vip-e.net/api/v1/social/oauth/meta/callback",
        "https://api.vip-e.net/api/v1/social/meta/webhooks",
        "https://api.vip-e.net/api/v1/social/meta/deauthorize",
        "https://api.vip-e.net/api/v1/social/meta/data-deletion",
        "/legal/data-deletion/",
        "/legal/privacy/",
        "Business Verification",
        "pages_messaging",
        "pages_manage_engagement",
        "pages_read_user_content",
        "pages_manage_metadata",
        "instagram_manage_messages",
        "instagram_manage_comments",
        "instagram_content_publish",
        "business_management",
    ):
        assert required in pack, required
    for item in ("3.6", "3.8"):
        line = next(text for text in ROADMAP.splitlines() if text.startswith(f"- [x] {item} "))
        assert line.endswith("(code merged; live verification deferred to pre-launch)"), line
