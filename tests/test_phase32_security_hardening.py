import pytest

from aios.models.openai_compatible import OpenAICompatibleProvider


def test_openai_compatible_rejects_unsafe_remote_http_and_embedded_credentials():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("http://example.com", "key", "model")
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("https://user:pass@example.com", "key", "model")
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("file:///tmp/model", "key", "model")


def test_openai_compatible_allows_https_and_local_http():
    assert OpenAICompatibleProvider("https://models.example.com", "key", "model").base_url.startswith("https://")
    assert OpenAICompatibleProvider("http://127.0.0.1:11434", "key", "model").base_url.startswith("http://127.0.0.1")
