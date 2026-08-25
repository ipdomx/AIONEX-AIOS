from __future__ import annotations
import json
import zipfile
from pathlib import Path
import pytest
from aios.course_factory import (
    CourseCitation,
    CourseFactoryError,
    CourseFactoryRequest,
    CompleteCourseFactory,
)


class FakeVideo:
    def preflight(self):
        return {"engine": "fake-test", "version": "1", "network_used": False}

    def render(self, destination: Path, *, lesson_index: int):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"0" * 2048)


def request():
    return CourseFactoryRequest(
        course_id="safe-digital-systems",
        title="Safe Digital Systems",
        domain="digital systems",
        audience="new operators",
        module_count=2,
        lessons_per_module=2,
        citations=(
            CourseCitation(
                "source-1", "Internal operating guide", "internal://aionex/guide"
            ),
        ),
    )


def test_factory_builds_complete_six_locale_offline_package(tmp_path: Path):
    result = CompleteCourseFactory(FakeVideo()).build(request(), tmp_path / "package")
    assert result.lesson_count == 4 and result.locales == (
        "ar",
        "en",
        "fr",
        "de",
        "es",
        "tr",
    )
    assert result.archive_path.is_file() and len(result.archive_sha256) == 64
    root = tmp_path / "package"
    for name in (
        "curriculum.json",
        "adaptive-paths.json",
        "_private/teacher/answer-key.json",
        "_private/teacher/review.json",
        "analytics/schema.json",
        "manifest.json",
        "mobile/manifest.webmanifest",
    ):
        assert (root / name).is_file()
    for locale in result.locales:
        assert (root / locale / "index.html").is_file()
        assert (root / "lessons" / locale / "m01l01" / "index.html").is_file()
    assert (root / "assets/m01l01/concept.svg").is_file()
    assert (root / "assets/m01l01/narration.wav").stat().st_size > 1000
    assert (root / "assets/m01l01/preview.mp4").stat().st_size >= 2048
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["provider_requests"] == 0 and manifest["network_used"] is False
    with zipfile.ZipFile(result.archive_path) as archive:
        assert "en/index.html" in archive.namelist()
        assert "_private/teacher/answer-key.json" not in archive.namelist()
        assert all(not name.startswith("_private/") for name in archive.namelist())


def test_factory_is_deterministic_except_archive_location(tmp_path: Path):
    first = CompleteCourseFactory(FakeVideo()).build(request(), tmp_path / "a")
    second = CompleteCourseFactory(FakeVideo()).build(request(), tmp_path / "b")
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.archive_sha256 == second.archive_sha256


def test_validation_rejects_unsafe_scope_and_citations(tmp_path: Path):
    with pytest.raises(CourseFactoryError):
        CompleteCourseFactory(FakeVideo()).build(
            CourseFactoryRequest("../bad", "Bad", "x", "x"), tmp_path / "bad"
        )
    with pytest.raises(CourseFactoryError):
        CourseCitation("source-1", "x", "http://example.com").validate()


def test_factory_refuses_nonempty_destination(tmp_path: Path):
    root = tmp_path / "x"
    root.mkdir()
    (root / "old").write_text("x")
    with pytest.raises(CourseFactoryError, match="empty"):
        CompleteCourseFactory(FakeVideo()).build(request(), root)


def test_arabic_lesson_localizes_content_and_quiz_not_only_labels(tmp_path: Path):
    CompleteCourseFactory(FakeVideo()).build(request(), tmp_path / "package")
    page = (tmp_path / "package/lessons/ar/m01l01/index.html").read_text(
        encoding="utf-8"
    )
    assert 'dir="rtl"' in page
    assert "أي اختيار يطبق المنهج المحكوم" in page
    assert "تجاهل الأدلة" in page
    assert "Apply evidence-driven" not in page
