from app.db import models  # noqa: F401
from app.db.base import Base


def test_expected_tables_are_registered():
    expected = {
        "organizations",
        "roles",
        "permissions",
        "role_permissions",
        "users",
        "refresh_sessions",
        "external_identities",
        "passkey_credentials",
        "password_reset_tokens",
        "user_mfa",
        "workspaces",
        "teams",
        "team_memberships",
        "projects",
        "tasks",
        "workflows",
        "meetings",
        "reports",
        "ai_providers",
        "ai_agents",
        "jobs",
        "billing_plans",
        "billing_prices",
        "billing_accounts",
        "billing_subscriptions",
        "billing_checkout_sessions",
        "billing_invoices",
        "billing_transactions",
        "billing_payment_methods",
        "billing_refunds",
        "billing_webhook_events",
        "billing_coupons",
        "billing_coupon_redemptions",
        "billing_tax_rates",
        "billing_usage_records",
        "billing_wallets",
        "billing_wallet_entries",
        "billing_licenses",
        "billing_reconciliation_runs",
        "notifications",
        "audit_events",
        "metric_samples",
        "alerts",
        "backup_records",
        "disaster_recovery_runs",
        "owner_control_records",
        "owner_command_records",
    }
    assert expected.issubset(set(Base.metadata.tables))


def test_core_unique_constraints_and_indexes_exist():
    users = Base.metadata.tables["users"]
    projects = Base.metadata.tables["projects"]
    workflows = Base.metadata.tables["workflows"]
    meetings = Base.metadata.tables["meetings"]
    roles = Base.metadata.tables["roles"]
    audit_events = Base.metadata.tables["audit_events"]
    owner_controls = Base.metadata.tables["owner_control_records"]
    owner_commands = Base.metadata.tables["owner_command_records"]
    teams = Base.metadata.tables["teams"]
    memberships = Base.metadata.tables["team_memberships"]
    password_resets = Base.metadata.tables["password_reset_tokens"]
    user_mfa = Base.metadata.tables["user_mfa"]

    assert any(column.name == "email" and column.unique for column in users.columns)
    assert any(
        index.name == "ix_projects_org_status_priority" for index in projects.indexes
    )
    assert workflows.c.workspace_id.nullable is True
    assert any(
        foreign_key.target_fullname == "workspaces.id"
        for foreign_key in workflows.c.workspace_id.foreign_keys
    )
    assert any(index.name == "ix_workflows_workspace_id" for index in workflows.indexes)
    assert meetings.c.workspace_id.nullable is True
    assert meetings.c.attendee_ids.nullable is False
    assert any(
        foreign_key.target_fullname == "workspaces.id"
        for foreign_key in meetings.c.workspace_id.foreign_keys
    )
    assert any(index.name == "ix_meetings_workspace_id" for index in meetings.indexes)
    assert roles.c.status.nullable is False
    assert roles.c.status.default is not None
    assert roles.c.status.default.arg == "active"
    assert any(index.name == "ix_roles_status" for index in roles.indexes)
    assert audit_events.c.resource_id.type.length == 160

    assert any(
        constraint.name == "uq_owner_control_domain_resource"
        for constraint in owner_controls.constraints
    )
    assert any(
        index.name == "ix_owner_control_domain_status"
        for index in owner_controls.indexes
    )
    assert owner_controls.c.status.nullable is False
    assert owner_controls.c.enabled.nullable is False
    assert owner_controls.c.version.nullable is False

    actor_foreign_keys = {
        foreign_key.target_fullname
        for foreign_key in owner_commands.c.actor_id.foreign_keys
    }
    assert actor_foreign_keys == {"users.id"}
    assert owner_commands.c.status.default is not None
    assert owner_commands.c.status.default.arg == "accepted"
    assert any(
        index.name == "ix_owner_command_status_created"
        for index in owner_commands.indexes
    )
    assert any(
        index.name == "ix_owner_command_records_created_at"
        for index in owner_commands.indexes
    )
    assert users.c.workspace_id.nullable is True
    assert any(
        foreign_key.target_fullname == "workspaces.id"
        for foreign_key in users.c.workspace_id.foreign_keys
    )
    assert any(index.name == "ix_users_workspace_id" for index in users.indexes)
    assert any(index.name == "ix_users_last_active_at" for index in users.indexes)
    assert any(
        constraint.name == "uq_team_org_slug" for constraint in teams.constraints
    )
    assert any(
        constraint.name == "uq_team_membership"
        for constraint in memberships.constraints
    )
    assert password_resets.c.token_hash.unique is True
    assert user_mfa.c.user_id.primary_key is True
    assert user_mfa.c.enabled.nullable is False
