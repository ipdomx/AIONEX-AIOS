"""Complete communications, notifications, meetings, and governance persistence.

Revision ID: 20260806_0009
Revises: 20260806_0008
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260806_0009"
down_revision = "20260806_0008"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in _inspector().get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def _create(name: str, *columns: sa.Column, constraints: tuple = ()) -> None:
    if name in _tables():
        return
    op.create_table(name, *columns, *constraints)


def _create_index(
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if table not in _tables():
        return
    existing = {item["name"] for item in _inspector().get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _create_unique(name: str, table: str, columns: list[str]) -> None:
    if table not in _tables():
        return
    existing = {item.get("name") for item in _inspector().get_unique_constraints(table)}
    if name not in existing:
        op.create_unique_constraint(name, table, columns)


def upgrade() -> None:
    # Enrich the existing user notification record without breaking retained rows.
    for column in (
        sa.Column("category", sa.String(80), nullable=False, server_default="system"),
        sa.Column(
            "event_key",
            sa.String(160),
            nullable=False,
            server_default="notification.created",
        ),
        sa.Column("audience", sa.String(40), nullable=False, server_default="user"),
        sa.Column("source_type", sa.String(80)),
        sa.Column("source_id", sa.String(160)),
        sa.Column("correlation_id", sa.String(160)),
        sa.Column("dedupe_key", sa.String(200)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    ):
        _add_column("notifications", column)
    _create_index(
        "ix_notifications_org_event_created",
        "notifications",
        ["organization_id", "event_key", "created_at"],
    )
    _create_index("ix_notifications_category", "notifications", ["category"])
    _create_index("ix_notifications_event_key", "notifications", ["event_key"])
    _create_index("ix_notifications_correlation_id", "notifications", ["correlation_id"])
    _create_unique(
        "uq_notifications_org_dedupe", "notifications", ["organization_id", "dedupe_key"]
    )

    # Complete the retained meetings table with lifecycle and minutes metadata.
    for column in (
        sa.Column("meeting_type", sa.String(40), nullable=False, server_default="standard"),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("agenda", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ):
        _add_column("meetings", column)

    for column in (
        sa.Column("assigned_to_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("acknowledged_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_escalated_at", sa.DateTime(timezone=True)),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    ):
        _add_column("alerts", column)
    _create_index("ix_alerts_assigned_to_id", "alerts", ["assigned_to_id"])

    _create(
        "communication_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("address_ciphertext", sa.Text(), nullable=False),
        sa.Column("address_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default="Primary"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "endpoint_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "user_id", "channel", "address_hash", name="uq_communication_endpoint"
            ),
        ),
    )
    _create_index(
        "ix_communication_endpoints_organization_id",
        "communication_endpoints",
        ["organization_id"],
    )
    _create_index(
        "ix_communication_endpoints_user_id", "communication_endpoints", ["user_id"]
    )
    _create_index(
        "ix_communication_endpoints_channel", "communication_endpoints", ["channel"]
    )
    _create_index(
        "ix_communication_endpoints_status", "communication_endpoints", ["status"]
    )
    _create_index(
        "ix_communication_endpoints_user_channel",
        "communication_endpoints",
        ["user_id", "channel", "status"],
    )

    _create(
        "notification_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(80), nullable=False, server_default="*"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "channels", sa.JSON(), nullable=False, server_default=sa.text("'[\"in_app\"]'")
        ),
        sa.Column("minimum_severity", sa.String(32), nullable=False, server_default="info"),
        sa.Column("quiet_hours_start", sa.String(5)),
        sa.Column("quiet_hours_end", sa.String(5)),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("digest_mode", sa.String(32), nullable=False, server_default="immediate"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "user_id", "category", name="uq_notification_preference_user_category"
            ),
        ),
    )
    _create_index(
        "ix_notification_preferences_organization_id",
        "notification_preferences",
        ["organization_id"],
    )
    _create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])
    _create_index(
        "ix_notification_preferences_user",
        "notification_preferences",
        ["user_id", "enabled"],
    )

    _create(
        "escalation_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "severity_threshold", sa.String(32), nullable=False, server_default="warning"
        ),
        sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(sa.UniqueConstraint("code", name="uq_escalation_policies_code"),),
    )
    _create_index(
        "ix_escalation_policies_organization_id", "escalation_policies", ["organization_id"]
    )
    _create_index(
        "ix_escalation_policies_enabled",
        "escalation_policies",
        ["enabled", "severity_threshold"],
    )

    _create(
        "notification_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "escalation_policy_id",
            sa.String(36),
            sa.ForeignKey("escalation_policies.id", ondelete="SET NULL"),
        ),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("event_pattern", sa.String(160), nullable=False),
        sa.Column("audience", sa.String(40), nullable=False, server_default="user"),
        sa.Column(
            "channels", sa.JSON(), nullable=False, server_default=sa.text("'[\"in_app\"]'")
        ),
        sa.Column("severity", sa.String(32), nullable=False, server_default="info"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("title_template", sa.String(240)),
        sa.Column("message_template", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(sa.UniqueConstraint("code", name="uq_notification_rules_code"),),
    )
    _create_index("ix_notification_rules_organization_id", "notification_rules", ["organization_id"])
    _create_index(
        "ix_notification_rules_escalation_policy_id",
        "notification_rules",
        ["escalation_policy_id"],
    )
    _create_index(
        "ix_notification_rules_event_enabled",
        "notification_rules",
        ["event_pattern", "enabled"],
    )

    _create(
        "notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "notification_id",
            sa.String(36),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            sa.String(36),
            sa.ForeignKey("communication_endpoints.id", ondelete="SET NULL"),
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "delivery_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "idempotency_key", name="uq_notification_delivery_idempotency"
            ),
        ),
    )
    for index, columns in {
        "ix_notification_deliveries_organization_id": ["organization_id"],
        "ix_notification_deliveries_notification_id": ["notification_id"],
        "ix_notification_deliveries_endpoint_id": ["endpoint_id"],
        "ix_notification_deliveries_channel": ["channel"],
        "ix_notification_deliveries_status": ["status"],
        "ix_notification_deliveries_next_attempt_at": ["next_attempt_at"],
        "ix_notification_delivery_due": ["status", "next_attempt_at"],
        "ix_notification_delivery_notification": ["notification_id", "channel"],
    }.items():
        _create_index(index, "notification_deliveries", columns)

    _create(
        "notification_delivery_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "delivery_id",
            sa.String(36),
            sa.ForeignKey("notification_deliveries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("error_code", sa.String(120)),
        sa.Column(
            "response_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        constraints=(
            sa.UniqueConstraint(
                "delivery_id", "attempt_number", name="uq_notification_delivery_attempt"
            ),
        ),
    )
    _create_index(
        "ix_notification_delivery_attempts_delivery_id",
        "notification_delivery_attempts",
        ["delivery_id"],
    )
    _create_index(
        "ix_notification_delivery_attempts_delivery",
        "notification_delivery_attempts",
        ["delivery_id", "started_at"],
    )

    _create(
        "support_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_to_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("subject", sa.String(240), nullable=False),
        sa.Column("category", sa.String(80), nullable=False, server_default="general"),
        sa.Column("priority", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "request_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for index, columns in {
        "ix_support_requests_organization_id": ["organization_id"],
        "ix_support_requests_requester_id": ["requester_id"],
        "ix_support_requests_assigned_to_id": ["assigned_to_id"],
        "ix_support_requests_status": ["status"],
        "ix_support_requests_org_status": ["organization_id", "status", "updated_at"],
        "ix_support_requests_requester": ["requester_id", "created_at"],
    }.items():
        _create_index(index, "support_requests", columns)

    _create(
        "support_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "support_request_id",
            sa.String(36),
            sa.ForeignKey("support_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="requester"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_support_messages_sender_id", "support_messages", ["sender_id"])
    _create_index(
        "ix_support_messages_request_created",
        "support_messages",
        ["support_request_id", "created_at"],
    )

    _create(
        "approval_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("risk", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("required_role", sa.String(120), nullable=False, server_default="Owner"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "approval_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for index, columns in {
        "ix_approval_requests_organization_id": ["organization_id"],
        "ix_approval_requests_requester_id": ["requester_id"],
        "ix_approval_requests_status": ["status"],
        "ix_approval_requests_org_status": ["organization_id", "status", "created_at"],
        "ix_approval_requests_target": ["target_type", "target_id"],
    }.items():
        _create_index(index, "approval_requests", columns)

    _create(
        "approval_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "approval_request_id",
            sa.String(36),
            sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "decision_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_approval_decisions_actor_id", "approval_decisions", ["actor_id"])
    _create_index(
        "ix_approval_decisions_request_created",
        "approval_decisions",
        ["approval_request_id", "created_at"],
    )

    _create(
        "governance_bodies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("governance_bodies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("charter", sa.Text()),
        sa.Column("jurisdiction", sa.String(240)),
        sa.Column("quorum", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "organization_id", "slug", name="uq_governance_body_org_slug"
            ),
        ),
    )
    for index, columns in {
        "ix_governance_bodies_organization_id": ["organization_id"],
        "ix_governance_bodies_parent_id": ["parent_id"],
        "ix_governance_bodies_owner_user_id": ["owner_user_id"],
        "ix_governance_bodies_status": ["status"],
        "ix_governance_bodies_org_kind": ["organization_id", "kind", "status"],
    }.items():
        _create_index(index, "governance_bodies", columns)

    _create(
        "governance_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "body_id",
            sa.String(36),
            sa.ForeignKey("governance_bodies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(80), nullable=False, server_default="member"),
        sa.Column("voting_weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("body_id", "user_id", name="uq_governance_membership"),
        ),
    )
    _create_index("ix_governance_memberships_user_id", "governance_memberships", ["user_id"])
    _create_index(
        "ix_governance_memberships_body_status",
        "governance_memberships",
        ["body_id", "status"],
    )

    _create(
        "governance_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "body_id",
            sa.String(36),
            sa.ForeignKey("governance_bodies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "approved_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("scope", sa.String(120), nullable=False, server_default="organization"),
        sa.Column("enforcement", sa.String(32), nullable=False, server_default="mandatory"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "organization_id", "code", name="uq_governance_policy_org_code"
            ),
        ),
    )
    for index, columns in {
        "ix_governance_policies_organization_id": ["organization_id"],
        "ix_governance_policies_body_id": ["body_id"],
        "ix_governance_policies_status": ["status"],
        "ix_governance_policies_org_status": ["organization_id", "status"],
    }.items():
        _create_index(index, "governance_policies", columns)

    _create(
        "governance_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "body_id",
            sa.String(36),
            sa.ForeignKey("governance_bodies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "policy_id",
            sa.String(36),
            sa.ForeignKey("governance_policies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "requested_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decided_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("decision", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for index, columns in {
        "ix_governance_decisions_organization_id": ["organization_id"],
        "ix_governance_decisions_body_id": ["body_id"],
        "ix_governance_decisions_policy_id": ["policy_id"],
        "ix_governance_decisions_meeting_id": ["meeting_id"],
        "ix_governance_decisions_status": ["status"],
        "ix_governance_decisions_org_status": ["organization_id", "status", "created_at"],
    }.items():
        _create_index(index, "governance_decisions", columns)

    _create(
        "governance_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "decision_id",
            sa.String(36),
            sa.ForeignKey("governance_decisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("vote", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("decision_id", "voter_id", name="uq_governance_vote"),
        ),
    )
    _create_index("ix_governance_votes_voter_id", "governance_votes", ["voter_id"])
    _create_index(
        "ix_governance_votes_decision", "governance_votes", ["decision_id", "vote"]
    )

    _create(
        "meeting_attendance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_status", sa.String(32), nullable=False, server_default="invited"),
        sa.Column("response_note", sa.Text()),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("attended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_attendance"),
        ),
    )
    _create_index("ix_meeting_attendance_user_id", "meeting_attendance", ["user_id"])
    _create_index(
        "ix_meeting_attendance_meeting_status",
        "meeting_attendance",
        ["meeting_id", "response_status"],
    )

    _create(
        "meeting_minutes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "published_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("summary", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("decisions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("action_items", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("meeting_id", name="uq_meeting_minutes_meeting"),
        ),
    )
    _create_index("ix_meeting_minutes_meeting_id", "meeting_minutes", ["meeting_id"], unique=True)


def downgrade() -> None:
    # This migration is intentionally reversible for disposable test databases.
    for table in (
        "meeting_minutes",
        "meeting_attendance",
        "governance_votes",
        "governance_decisions",
        "governance_policies",
        "governance_memberships",
        "governance_bodies",
        "approval_decisions",
        "approval_requests",
        "support_messages",
        "support_requests",
        "notification_delivery_attempts",
        "notification_deliveries",
        "notification_rules",
        "escalation_policies",
        "notification_preferences",
        "communication_endpoints",
    ):
        if table in _tables():
            op.drop_table(table)

    for table, columns in {
        "alerts": (
            "details",
            "last_escalated_at",
            "escalation_level",
            "resolved_by_id",
            "acknowledged_by_id",
            "assigned_to_id",
        ),
        "meetings": (
            "version",
            "completed_at",
            "cancel_reason",
            "agenda",
            "timezone",
            "meeting_type",
        ),
        "notifications": (
            "expires_at",
            "archived_at",
            "dedupe_key",
            "correlation_id",
            "source_id",
            "source_type",
            "audience",
            "event_key",
            "category",
        ),
    }.items():
        for column in columns:
            if column in _columns(table):
                op.drop_column(table, column)
