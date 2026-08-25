"""Add durable professional evidence and high-stakes human review authority.

Revision ID: 20260825_0043
Revises: 20260825_0042
Create Date: 2026-08-25
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0043"
down_revision: str | None = "20260825_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    required = {"organizations", "workspaces", "audit_events"}
    if not required.issubset(tables):
        raise RuntimeError(
            "Professional evidence migration requires core tenant/audit tables"
        )
    if "professional_evidence_cases" not in tables:
        op.create_table(
            "professional_evidence_cases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_by_id", sa.String(36), nullable=False),
            sa.Column("case_mode", sa.String(40), nullable=False),
            sa.Column("purpose", sa.Text, nullable=False),
            sa.Column("subject_ref_hash", sa.String(64), nullable=False),
            sa.Column("request_summary", sa.Text, nullable=False),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="pending_review"
            ),
            sa.Column("residency_profile", sa.String(120), nullable=False),
            sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "citations",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "assistance",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("evidence_digest", sa.String(64), nullable=False),
            sa.Column(
                "human_review_required",
                sa.Boolean,
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "autonomous_decision_allowed",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("review_version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
                "id", "organization_id", name="uq_professional_case_id_org"
            ),
            sa.CheckConstraint(
                "case_mode IN ('administrative','education','professional_assistance','clinical_high_stakes')",
                name="ck_professional_case_mode",
            ),
            sa.CheckConstraint(
                "status IN ('pending_review','approved','rejected','closed')",
                name="ck_professional_case_status",
            ),
            sa.CheckConstraint(
                "autonomous_decision_allowed = false",
                name="ck_professional_case_no_autonomous_decision",
            ),
            sa.CheckConstraint(
                "review_version >= 1", name="ck_professional_case_review_version"
            ),
        )
        op.create_index(
            "ix_professional_cases_org_status_created",
            "professional_evidence_cases",
            ["organization_id", "status", "created_at"],
        )
        op.create_index(
            "ix_professional_cases_org_mode_retention",
            "professional_evidence_cases",
            ["organization_id", "case_mode", "retention_until"],
        )
        op.create_index(
            "ix_professional_evidence_cases_workspace_id",
            "professional_evidence_cases",
            ["workspace_id"],
        )
        op.create_index(
            "ix_professional_evidence_cases_created_by_id",
            "professional_evidence_cases",
            ["created_by_id"],
        )
        op.create_index(
            "ix_professional_evidence_cases_subject_ref_hash",
            "professional_evidence_cases",
            ["subject_ref_hash"],
        )
    tables = set(sa.inspect(bind).get_table_names())
    if "professional_review_decisions" not in tables:
        op.create_table(
            "professional_review_decisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("case_id", sa.String(36), nullable=False),
            sa.Column("reviewer_id", sa.String(36), nullable=False),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("rationale", sa.Text, nullable=False),
            sa.Column("evidence_digest", sa.String(64), nullable=False),
            sa.Column("review_version", sa.Integer, nullable=False),
            sa.Column(
                "decision_metadata",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["case_id", "organization_id"],
                [
                    "professional_evidence_cases.id",
                    "professional_evidence_cases.organization_id",
                ],
                ondelete="CASCADE",
                name="fk_professional_review_case_org",
            ),
            sa.CheckConstraint(
                "decision IN ('approved','rejected','changes_requested')",
                name="ck_professional_review_decision",
            ),
            sa.CheckConstraint(
                "review_version >= 1", name="ck_professional_review_version"
            ),
            sa.UniqueConstraint(
                "case_id", "review_version", name="uq_professional_review_case_version"
            ),
        )
        op.create_index(
            "ix_professional_review_org_created",
            "professional_review_decisions",
            ["organization_id", "created_at"],
        )
        op.create_index(
            "ix_professional_review_decisions_case_id",
            "professional_review_decisions",
            ["case_id"],
        )
        op.create_index(
            "ix_professional_review_decisions_reviewer_id",
            "professional_review_decisions",
            ["reviewer_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "professional_review_decisions" in tables:
        op.drop_table("professional_review_decisions")
    tables = set(sa.inspect(bind).get_table_names())
    if "professional_evidence_cases" in tables:
        op.drop_table("professional_evidence_cases")
