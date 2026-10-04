import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SOURCE = Path(__file__).parents[1] / "app/services/academy_course_runtime.py"


def _load_snapshot_contract():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "LEARNER_READY_PACKAGE_STATUSES" in names:
                wanted.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "package_snapshot":
            wanted.append(node)
    module = ast.Module(body=wanted, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "AcademyCoursePackage": object,
        "iso": lambda value: value,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return (
        namespace["LEARNER_READY_PACKAGE_STATUSES"],
        namespace["package_snapshot"],
    )


def _package(status: str):
    return SimpleNamespace(
        id="pkg-1",
        course_id="course-1",
        status=status,
        version=1,
        lesson_count=2,
        request_payload={"locales": ["en"]},
        curriculum={"lessons": [{"key": "lesson-1"}]},
        citations=[{"url": "https://example.invalid/evidence"}],
        review={"status": "pending", "approved": False},
        archive_sha256="a" * 64,
        manifest_sha256="b" * 64,
        archive_bytes=128,
        archive_relpath="org/course/package.zip",
        site_relpath="org/course/site",
        error_code=None,
        completed_at=None,
        reviewed_at=None,
        created_at=None,
        updated_at=None,
    )


def test_review_pending_package_is_not_learner_ready():
    statuses, snapshot_fn = _load_snapshot_contract()
    snapshot = snapshot_fn(_package("review_pending"))

    assert statuses == frozenset({"approved"})
    assert snapshot["download_ready"] is False
    assert snapshot["site_ready"] is False
    assert "archive_relpath" not in snapshot
    assert "site_relpath" not in snapshot


def test_approved_package_is_learner_ready():
    _, snapshot_fn = _load_snapshot_contract()
    snapshot = snapshot_fn(_package("approved"))

    assert snapshot["download_ready"] is True
    assert snapshot["site_ready"] is True


def test_rejected_package_is_not_learner_ready():
    _, snapshot_fn = _load_snapshot_contract()
    snapshot = snapshot_fn(_package("rejected"))

    assert snapshot["download_ready"] is False
    assert snapshot["site_ready"] is False
