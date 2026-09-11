from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backend_ruff_version_and_contract_are_explicit() -> None:
    requirements = (ROOT / "web-dashboard/backend/requirements.txt").read_text(encoding="utf-8")
    config = (ROOT / "web-dashboard/backend/ruff.toml").read_text(encoding="utf-8")
    assert "ruff==0.16.6" in requirements
    assert 'target-version = "py38"' in config
    assert 'select = ["E4", "E7", "E9", "F"]' in config


def test_static_quality_workflow_still_invokes_ruff_and_mypy() -> None:
    workflow = (ROOT / ".github/workflows/final-validation.yml").read_text(encoding="utf-8")
    assert "ruff check --no-cache app tests" in workflow
    assert "mypy --no-incremental app" in workflow
