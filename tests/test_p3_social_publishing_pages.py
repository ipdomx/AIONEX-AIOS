"""Static portal contract for P3 publishing: composer and content calendar."""

from __future__ import annotations

import json
import re
from pathlib import Path

from aios.completion_program import ENDPOINT_BATCH, VIP_PAGE_BATCH

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
PAGES = VIP / "src/components/pages"
COMPOSER = (PAGES / "social-composer-client.tsx").read_text(encoding="utf-8")
CALENDAR = (PAGES / "social-calendar-client.tsx").read_text(encoding="utf-8")
SHARED = (PAGES / "social-publishing-shared.tsx").read_text(encoding="utf-8")
API = (VIP / "src/lib/api.ts").read_text(encoding="utf-8")
NAVBAR = (VIP / "src/components/layout/navbar.tsx").read_text(encoding="utf-8")
NGINX = (ROOT / "web-dashboard/docker/nginx.conf").read_text(encoding="utf-8")
RULES = (ROOT / "web-dashboard/backend/app/services/social_publishing_rules.py").read_text(
    encoding="utf-8"
)
LOCALES = ("ar", "en", "fr", "de", "es", "tr")


def _flatten(value: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _flatten(item, path) if isinstance(item, dict) else {path}
    return keys


def test_pages_are_registered_linked_and_smoke_tested() -> None:
    assert VIP_PAGE_BATCH["[locale]/social/compose/page.tsx"] == "GS-04"
    assert VIP_PAGE_BATCH["[locale]/social/calendar/page.tsx"] == "GS-04"
    assert ENDPOINT_BATCH["social_publishing"] == "GS-04"
    for route, client in (("compose", "SocialComposerClient"), ("calendar", "SocialCalendarClient")):
        page = (VIP / f"src/app/[locale]/social/{route}/page.tsx").read_text(encoding="utf-8")
        assert f"<{client} />" in page and f'path: "social/{route}"' in page
        assert "noIndex: true" in page
        assert NAVBAR.count(f"href={{`/${{locale}}/social/{route}`}}") == 2  # desktop and mobile
        assert f'"src/app/[locale]/social/{route}/page.tsx"' in (
            VIP / "scripts/check-integrity.mjs"
        ).read_text()
        assert f'"/social/{route}"' in (VIP / "scripts/smoke-test.mjs").read_text()
        assert f'"social/{route}"' in (VIP / "scripts/static-smoke-test.mjs").read_text()
    assert 't("socialCompose")' in NAVBAR and 't("socialCalendar")' in NAVBAR


def test_every_locale_has_the_publishing_strings_and_arabic() -> None:
    reference = json.loads((VIP / "src/messages/en.json").read_text(encoding="utf-8"))
    expected = _flatten(reference["socialPublishing"])
    for locale in LOCALES:
        messages = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
        assert _flatten(messages["socialPublishing"]) == expected, locale
        assert messages["nav"]["socialCompose"] and messages["nav"]["socialCalendar"]
        assert messages["meta"]["socialComposeTitle"] and messages["meta"]["socialCalendarTitle"]
    arabic = json.loads((VIP / "src/messages/ar.json").read_text(encoding="utf-8"))
    assert arabic["socialPublishing"]["calendar"]["title"] == "تقويم المحتوى"
    assert "AIONEX AI" in arabic["socialPublishing"]["ai"]["title"]
    # Every issue code the shared helper translates exists in the messages.
    codes = set(re.findall(r'^  "([a-z0-9-]+)",$', SHARED, re.MULTILINE))
    assert codes and codes <= set(reference["socialPublishing"]["issues"])


def test_clients_use_api_helpers_and_never_inject_html_or_tokens() -> None:
    for route in (
        "/social/posts",
        "/social/posts/validate",
        "/social/media",
        "/social/ai/assist",
    ):
        assert route in API, route
    for client in (COMPOSER, CALENDAR, SHARED):
        assert "fetch(" not in client
        assert "dangerouslySetInnerHTML" not in client and "innerHTML" not in client
        assert "createObjectURL" not in client and "<img" not in client
        assert "access_token" not in client
    for helper in ("createSocialPost", "publishSocialPostNow", "scheduleSocialPost", "socialAiAssist", "uploadSocialMedia", "validateSocialPost"):
        assert helper in COMPOSER, helper
    for helper in ("listSocialPosts", "cancelSocialPost", "getSocialPost"):
        assert helper in CALENDAR, helper
    # Live-post links: only https on a Meta host, opened without an opener.
    assert "safePermalink(target.permalink)" in CALENDAR
    assert 'url.protocol !== "https:"' in SHARED
    assert 'rel="noopener noreferrer"' in CALENDAR
    assert '"month"' in CALENDAR and '"week"' in CALENDAR


def test_new_social_routes_are_in_the_public_nginx_allowlist() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert (
        "social/(?:providers|connect/[a-z][a-z0-9_-]{1,39}/start|oauth/[a-z][a-z0-9_-]{1,39}/callback"
        in public_server
    )
    for fragment in (
        "|posts(?:/(?:validate|[0-9a-f-]{36}(?:/(?:schedule|publish|cancel))?))?",
        "|media(?:/[0-9a-f-]{36})?|ai/assist)",
        "location = /api/v1/social/media {",
        "^/api/v1/social/media/public/[A-Za-z0-9_-]{20,600}\\.[0-9a-f]{64}/[A-Za-z0-9._-]{1,160}$",
    ):
        assert fragment in public_server, fragment
    bridge = public_server.split("location ~ \"^/api/v1/social/media/public/", 1)[1]
    bridge = bridge.split("# P3 composer uploads", 1)[0]
    assert "access_log off;" in bridge and "limit_except GET" in bridge and "deny all;" in bridge
    assert 'proxy_set_header Cookie "";' in bridge


def test_instagram_caption_limit_matches_composer() -> None:
    assert "IG_CAPTION_MAX = 2200" in RULES
    assert "const IG_CAPTION_MAX = 2200;" in COMPOSER
