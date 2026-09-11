from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_isort_is_not_a_backend_dependency() -> None:
    requirements = (ROOT / "web-dashboard/backend/requirements.txt").read_text(encoding="utf-8")
    assert "isort==" not in requirements


def test_ci_and_automation_do_not_depend_on_isort() -> None:
    paths = list((ROOT / ".github/workflows").glob("*.yml"))
    paths += list((ROOT / ".github/workflows").glob("*.yaml"))
    text_suffixes = {".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini"}
    paths += [
        path
        for path in (ROOT / "scripts").rglob("*")
        if path.is_file() and path.suffix in text_suffixes
    ]
    paths += [
        path
        for path in (ROOT / "web-dashboard/backend/scripts").rglob("*")
        if path.is_file() and path.suffix in text_suffixes
    ]
    root_hook = ROOT / ".pre-commit-config.yaml"
    backend_hook = ROOT / "web-dashboard/backend/.pre-commit-config.yaml"
    paths += [path for path in (root_hook, backend_hook) if path.is_file()]
    corpus = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in paths).lower()
    assert "isort" not in corpus
