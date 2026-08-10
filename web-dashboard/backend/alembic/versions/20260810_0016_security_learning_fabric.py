"""Add Autonomous Security & Learning Fabric persistence.

Revision ID: 20260810_0016
Revises: 20260810_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260810_0016"
down_revision = "20260810_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_access_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_security_grant_org_user"),
    )
    op.create_index("ix_security_grants_status_expiry", "security_access_grants", ["status", "expires_at"])
    op.create_index("ix_security_access_grants_organization_id", "security_access_grants", ["organization_id"])
    op.create_index("ix_security_access_grants_user_id", "security_access_grants", ["user_id"])

    op.create_table(
        "security_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verified_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(500), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("authorization_status", sa.String(32), nullable=False),
        sa.Column("verification_method", sa.String(40), nullable=False),
        sa.Column("challenge_hash", sa.String(64)),
        sa.Column("active_scan_allowed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("target_metadata", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "origin", name="uq_security_target_org_origin"),
    )
    op.create_index("ix_security_targets_org_auth", "security_targets", ["organization_id", "authorization_status", "status"])
    for name in ("organization_id", "project_id", "created_by_id", "verified_by_id", "kind", "hostname", "authorization_status", "status"):
        op.create_index(f"ix_security_targets_{name}", "security_targets", [name])

    op.create_table(
        "security_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("security_targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("execution_mode", sa.String(32), nullable=False),
        sa.Column("tool_plan", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_scans_org_status_created", "security_scans", ["organization_id", "status", "created_at"])
    op.create_index("ix_security_scans_target_created", "security_scans", ["target_id", "created_at"])
    for name in ("organization_id", "project_id", "target_id", "requested_by_id", "profile", "status", "lease_token"):
        op.create_index(f"ix_security_scans_{name}", "security_scans", [name])

    op.create_table(
        "security_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("security_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("security_targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("cwe", sa.String(40)),
        sa.Column("owasp", sa.String(80)),
        sa.Column("location", sa.Text()),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("remediation", sa.Text()),
        sa.Column("verified_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scan_id", "fingerprint", name="uq_security_finding_scan_fingerprint"),
    )
    op.create_index("ix_security_findings_org_state_severity", "security_findings", ["organization_id", "state", "severity"])
    op.create_index("ix_security_findings_target_created", "security_findings", ["target_id", "created_at"])
    for name in ("organization_id", "scan_id", "target_id", "source", "category", "severity", "state", "verified_by_id"):
        op.create_index(f"ix_security_findings_{name}", "security_findings", [name])

    op.create_table(
        "security_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("source_finding_id", sa.String(36), sa.ForeignKey("security_findings.id", ondelete="SET NULL")),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("detector", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("validation_passes", sa.Integer(), nullable=False),
        sa.Column("validation_failures", sa.Integer(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "signature", name="uq_security_rule_org_signature"),
    )
    op.create_index("ix_security_rules_status_trust", "security_rules", ["status", "trust_score"])
    for name in ("organization_id", "source_finding_id", "created_by_id", "rule_type", "status"):
        op.create_index(f"ix_security_rules_{name}", "security_rules", [name])

    op.create_table(
        "security_rule_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_id", sa.String(36), sa.ForeignKey("security_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("corpus_id", sa.String(120), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_rule_validations_rule_created", "security_rule_validations", ["rule_id", "created_at"])
    op.create_index("ix_security_rule_validations_rule_id", "security_rule_validations", ["rule_id"])

    op.create_table(
        "security_remediations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("security_findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("worktree_ref", sa.Text()),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("regression_result", sa.JSON(), nullable=False),
        sa.Column("retest_scan_id", sa.String(36), sa.ForeignKey("security_scans.id", ondelete="SET NULL")),
        sa.Column("verified_fixed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_remediations_org_status_created", "security_remediations", ["organization_id", "status", "created_at"])
    for name in ("organization_id", "project_id", "finding_id", "requested_by_id", "status", "retest_scan_id"):
        op.create_index(f"ix_security_remediations_{name}", "security_remediations", [name])

    op.create_table(
        "security_release_gates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("security_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_release_gate_project_created", "security_release_gates", ["project_id", "created_at"])
    for name in ("organization_id", "project_id", "scan_id", "decision", "created_by_id"):
        op.create_index(f"ix_security_release_gates_{name}", "security_release_gates", [name])


def downgrade() -> None:
    for table in (
        "security_release_gates",
        "security_remediations",
        "security_rule_validations",
        "security_rules",
        "security_findings",
        "security_scans",
        "security_targets",
        "security_access_grants",
    ):
        op.drop_table(table)
