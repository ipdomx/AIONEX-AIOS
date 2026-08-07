from pathlib import Path

import pytest

from aios.backend_zero_dead import audit_backend
from aios.models.router import ModelRouter


ROOT = Path(__file__).resolve().parents[1]


def test_backend_zero_dead_audit_passes_current_repository() -> None:
    report = audit_backend(ROOT)
    assert report.scanned_files > 100
    assert report.api_routes >= 300
    assert report.blocking_findings == ()
    assert report.passed is True


def test_legacy_local_model_never_returns_fake_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('AIOS_MODEL_PROVIDER', 'local')
    monkeypatch.delenv('AIOS_OPENAI_COMPAT_BASE_URL', raising=False)
    monkeypatch.delenv('AIOS_OPENAI_COMPAT_API_KEY', raising=False)
    model = ModelRouter().build_default()
    with pytest.raises(RuntimeError, match='No local model runtime is configured'):
        model.generate('build something real')


def test_unknown_legacy_model_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('AIOS_MODEL_PROVIDER', 'nonexistent')
    with pytest.raises(RuntimeError, match='Unsupported legacy model provider'):
        ModelRouter().build_default()
