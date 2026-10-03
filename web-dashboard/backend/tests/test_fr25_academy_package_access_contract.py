from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ACADEMY_ENDPOINT = ROOT / "web-dashboard/backend/app/api/v1/endpoints/academy.py"


def _function_source(name: str) -> str:
    source = ACADEMY_ENDPOINT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"missing function: {name}")


def test_reader_download_and_site_require_approved_package() -> None:
    for name in ("download_course_package", "course_package_site"):
        source = _function_source(name)
        assert 'item.status != "approved"' in source
        assert '"review_pending"' not in source


def test_reviewer_path_remains_distinct_from_reader_path() -> None:
    review = _function_source("review_course_package")
    answer_key = _function_source("teacher_answer_key")
    assert 'require_permissions("academy:assess")' in review
    assert 'require_permissions("academy:assess")' in answer_key
    assert '"review_pending"' in answer_key
