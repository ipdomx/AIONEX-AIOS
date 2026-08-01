from types import SimpleNamespace

from app.api.v1.endpoints.locale import _accept_languages, _country_from_headers
from app.services.programming_languages import (
    identify_language,
    programming_language_manifest,
)


def _request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers)


def test_locale_country_uses_trusted_coarse_header_only():
    assert _country_from_headers(_request({"cf-ipcountry": "ae"})) == "AE"
    assert _country_from_headers(_request({"x-country-code": "EG"})) == "EG"
    assert _country_from_headers(_request({"x-forwarded-for": "203.0.113.2"})) is None
    assert _country_from_headers(_request({"cf-ipcountry": "XX"})) is None


def test_accept_language_is_ordered_deduplicated_and_bounded():
    request = _request({"accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,ar-EG;q=0.7"})
    assert _accept_languages(request) == ["ar-EG", "ar", "en-US"]


def test_programming_registry_is_multi_language_and_identifies_files():
    manifest = programming_language_manifest()
    assert len(manifest) >= 20
    assert {item["id"] for item in manifest} >= {
        "python",
        "javascript",
        "typescript",
        "java",
        "csharp",
        "go",
        "rust",
        "cpp",
        "php",
        "swift",
        "kotlin",
        "dart",
        "sql",
    }
    assert identify_language("service.py").id == "python"
    assert identify_language("dashboard.tsx").id == "typescript"
    assert identify_language("README.md") is None
