"""Guard the public-facing AIOS Portal artifact identity without mutating production."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts/release/ns14a_verify_portal_public_artifact.py"
SPEC = importlib.util.spec_from_file_location("aios_ns14a_public_identity", MOD)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_encoded_and_literal_locale_chunks_resolve_only_to_original_host():
    for marker in ("%5Blocale%5D", "[locale]"):
        html = f'<script src="/_next/static/chunks/app/{marker}/conversations/page-1234abcd.js"></script>'
        result = guard.extract_conversation_asset(html, "https://ai.vip-e.net/en/conversations/")
        assert result.startswith("https://ai.vip-e.net/_next/static/chunks/")
        assert result.endswith("/conversations/page-1234abcd.js")


@pytest.mark.parametrize("url", [
    "http://ai.vip-e.net/en/conversations/",
    "https://evil.example/en/conversations/",
    "https://127.0.0.1/en/conversations/",
    "https://ai.vip-e.net:444/en/conversations/",
    "https://user:password@ai.vip-e.net/en/conversations/",
    "https://ai.vip-e.net/en/conversations/#fragment",
    "https://ai.vip-e.net\\@evil.example/en/conversations/",
])
def test_untrusted_public_origins_are_never_fetched(url):
    with pytest.raises(ValueError):
        guard.require_origin(url)


def test_external_conversation_asset_rejected_before_network_request():
    page = '<script src="https://attacker.example/_next/static/chunks/app/%5Blocale%5D/conversations/page-123abc.js"></script>'
    with pytest.raises(ValueError):
        guard.extract_conversation_asset(page, "https://ai.vip-e.net/en/conversations/")


def test_redirect_cross_host_refused_without_network_request():
    handler = guard.SameHostRedirects()
    from urllib.request import Request
    req = Request("https://ai.vip-e.net/en/conversations")
    with pytest.raises(ValueError):
        handler.redirect_request(req, None, 302, "Moved", {}, "https://unexpected.example/portal")
    with pytest.raises(ValueError):
        handler.redirect_request(req, None, 302, "Moved", {}, "http://ai.vip-e.net/en/conversations")


def test_no_conversation_chunk_or_ambiguous_document_fails_closed():
    with pytest.raises(ValueError):
        guard.extract_conversation_asset("<html/>", "https://ai.vip-e.net/en/conversations")
    duplicate = (
        '<script src="/_next/static/chunks/app/%5Blocale%5D/conversations/page-1234.js"></script>'
        '<script src="/_next/static/chunks/app/%5Blocale%5D/conversations/page-5678.js"></script>'
    )
    with pytest.raises(ValueError):
        guard.extract_conversation_asset(duplicate, "https://ai.vip-e.net/en/conversations")


def test_portal_identity_probe_bounded_resource_limit():
    assert 0 < guard.MAX_REMOTE_BYTES <= 8 * 1024 * 1024
    assert guard.PUBLIC_HOST == "ai.vip-e.net"
    assert guard.LOCALES == {"ar","en","fr","de","es","tr"}
