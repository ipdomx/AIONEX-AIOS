"""Add durable academy course packages and lesson progress.

Revision ID: 20260825_0042
Revises: 20260824_0041
Create Date: 2026-08-25
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0042"
down_revision: str | None = "20260824_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    required = {"organizations", "users", "academy_courses", "academy_enrollments"}
    if not required.issubset(tables):
        raise RuntimeError(
            "Academy course-package migration requires Phase 29F academy tables"
        )
    if "academy_course_packages" not in tables:
        op.create_table(
            "academy_course_packages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "course_id",
                sa.String(36),
                sa.ForeignKey("academy_courses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "requested_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "reviewed_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("lesson_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "request_payload",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "curriculum",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "citations",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "review", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")
            ),
            sa.Column("site_relpath", sa.Text, nullable=True),
            sa.Column("archive_relpath", sa.Text, nullable=True),
            sa.Column("archive_sha256", sa.String(64), nullable=True),
            sa.Column("manifest_sha256", sa.String(64), nullable=True),
            sa.Column(
                "archive_bytes", sa.BigInteger, nullable=False, server_default="0"
            ),
            sa.Column("error_code", sa.String(120), nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_academy_course_package_org_idempotency",
            ),
            sa.UniqueConstraint(
                "course_id", "version", name="uq_academy_course_package_version"
            ),
            sa.CheckConstraint(
                "version >= 1", name="ck_academy_course_package_version"
            ),
            sa.CheckConstraint(
                "lesson_count >= 0 AND lesson_count <= 32",
                name="ck_academy_course_package_lessons",
            ),
            sa.CheckConstraint(
                "archive_bytes >= 0", name="ck_academy_course_package_bytes"
            ),
        )
        op.create_index(
            "ix_academy_course_packages_org_status_created",
            "academy_course_packages",
            ["organization_id", "status", "created_at"],
        )
        op.create_index(
            "ix_academy_course_packages_course_version",
            "academy_course_packages",
            ["course_id", "version"],
        )
    tables = set(sa.inspect(bind).get_table_names())
    if "academy_lesson_progress" not in tables:
        op.create_table(
            "academy_lesson_progress",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "enrollment_id",
                sa.String(36),
                sa.ForeignKey("academy_enrollments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "package_id",
                sa.String(36),
                sa.ForeignKey("academy_course_packages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("lesson_key", sa.String(64), nullable=False),
            sa.Column("locale", sa.String(8), nullable=False, server_default="en"),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="not_started"
            ),
            sa.Column("progress_percent", sa.Float, nullable=False, server_default="0"),
            sa.Column("score", sa.Float, nullable=True),
            sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "position",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "enrollment_id",
                "package_id",
                "lesson_key",
                name="uq_academy_lesson_progress_lesson",
            ),
            sa.CheckConstraint(
                "progress_percent >= 0 AND progress_percent <= 100",
                name="ck_academy_lesson_progress_percent",
            ),
            sa.CheckConstraint(
                "score IS NULL OR (score >= 0 AND score <= 100)",
                name="ck_academy_lesson_progress_score",
            ),
            sa.CheckConstraint(
                "attempts >= 0", name="ck_academy_lesson_progress_attempts"
            ),
        )
        op.create_index(
            "ix_academy_lesson_progress_org_status",
            "academy_lesson_progress",
            ["organization_id", "status"],
        )
        op.create_index(
            "ix_academy_lesson_progress_enrollment",
            "academy_lesson_progress",
            ["enrollment_id", "updated_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "academy_lesson_progress" in tables:
        op.drop_table("academy_lesson_progress")
    if "academy_course_packages" in tables:
        op.drop_table("academy_course_packages")
