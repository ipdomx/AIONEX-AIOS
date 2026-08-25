from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "web-dashboard/backend/alembic/versions/20260825_0042_academy_course_packages.py"
)
ACADEMY = ROOT / "web-dashboard/backend/app/api/v1/endpoints/academy.py"
WORKER = ROOT / "web-dashboard/backend/app/services/academy_course_worker.py"
COMPOSE = ROOT / "web-dashboard/docker-compose.production.yml"
FACTORY = ROOT / "src/aios/course_factory.py"


def test_0042_is_linear_reversible_and_adds_only_course_package_authority() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20260825_0042"' in source
    assert 'down_revision: str | None = "20260824_0041"' in source
    for table in ("academy_course_packages", "academy_lesson_progress"):
        assert f'"{table}"' in source
    assert "uq_academy_course_package_org_idempotency" in source
    assert "uq_academy_lesson_progress_lesson" in source
    assert "def downgrade()" in source


def test_academy_api_exposes_factory_review_delivery_progress_and_analytics() -> None:
    source = ACADEMY.read_text(encoding="utf-8")
    for token in (
        '@router.post("/courses/{course_id}/packages"',
        '@router.get("/courses/{course_id}/packages")',
        '@router.post("/packages/{package_id}/review")',
        '@router.get("/packages/{package_id}/download")',
        '@router.get("/packages/{package_id}/site/{asset_path:path}")',
        '@router.get("/packages/{package_id}/teacher/answer-key")',
        "lessons/{lesson_key}/progress",
        '@router.get("/courses/{course_id}/analytics")',
    ):
        assert token in source
    assert "resolve_package_path" in source
    assert "sha256_file" in source


def test_course_worker_is_local_ffmpeg_provider_free_and_profile_gated() -> None:
    worker = WORKER.read_text(encoding="utf-8")
    factory = FACTORY.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "LocalFFmpegCourseVideoRenderer" in worker
    assert 'ACADEMY_COURSE_WORKER_ENABLED", "false"' in worker
    for forbidden in ("openai", "anthropic", "requests.post", "httpx.AsyncClient"):
        assert forbidden not in factory.lower()
    start = compose.index("  academy-course-worker:")
    end = compose.index("\n  media-worker:", start)
    block = compose[start:end]
    assert 'profiles: ["academy-execution"]' in block
    assert 'user: "0:0"' in block
    assert 'ACADEMY_COURSE_ENTRYPOINT_BOOTSTRAP_ONLY: "true"' in block
    assert 'cap_drop: ["ALL"]' in block
    assert 'cap_add: ["CHOWN", "FOWNER", "SETGID", "SETUID"]' in block
    assert (
        'su-exec", "aionex", "python", "-m", "app.services.academy_course_worker"'
        in block
    )
    assert "no-new-privileges:true" in block
    assert "course_package_data:/var/lib/aionex/course-packages:rw" in block
    assert "ports:" not in block


def test_backend_can_read_course_packages_but_not_write_worker_volume() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    backend = compose[compose.index("  backend:") : compose.index("\n  backup-worker:")]
    assert "course_package_data:/var/lib/aionex/course-packages:ro" in backend


def test_teacher_answer_key_is_not_in_learner_package_or_public_site_contract() -> None:
    factory = FACTORY.read_text(encoding="utf-8")
    academy = ACADEMY.read_text(encoding="utf-8")
    assert 'root / "_private" / "teacher" / "answer-key.json"' in factory
    assert 'if "_private" in rel_path.parts' in factory
    assert 'asset_path.strip().lstrip("/").startswith("_private/")' in academy
    assert (
        'require_permissions("academy:assess")'
        in academy[
            academy.index("teacher_answer_key") : academy.index("teacher_answer_key")
            + 500
        ]
    )


def test_course_worker_entrypoint_normalizes_private_volume_then_drops_privileges() -> (
    None
):
    entrypoint = (
        ROOT / "web-dashboard/backend/scripts/docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert "ACADEMY_COURSE_ENTRYPOINT_BOOTSTRAP_ONLY" in entrypoint
    assert 'course_package_meta="$(stat -c' in entrypoint
    assert 'course_package_meta" != "700:1000:1000"' in entrypoint
    assert 'exec su-exec aionex "$@"' in entrypoint
