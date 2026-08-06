"""Complete billing, licensing, payments, and entitlement persistence.

Revision ID: 20260806_0008
Revises: 20260806_0007
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260806_0008"
down_revision = "20260806_0007"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _create(name: str, *columns: sa.Column, constraints: tuple = ()) -> None:
    if name in _tables(op.get_bind()):
        return
    op.create_table(name, *columns, *constraints)


def _create_index(
    name: str,
    table: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    bind = op.get_bind()
    if table not in _tables(bind):
        return
    existing = {item["name"] for item in sa.inspect(bind).get_indexes(table)}
    if name in existing:
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _create(
        "billing_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="inactive"),
        sa.Column(
            "default_currency", sa.String(3), nullable=False, server_default="USD"
        ),
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "entitlements", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "metering", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(sa.UniqueConstraint("code", name="uq_billing_plans_code"),),
    )
    _create_index("ix_billing_plans_code", "billing_plans", ["code"], unique=True)
    _create_index("ix_billing_plans_status", "billing_plans", ["status"])

    _create(
        "billing_prices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("billing_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_code", sa.String(80), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("amount_minor", sa.BigInteger()),
        sa.Column("compare_at_minor", sa.BigInteger()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider", sa.String(40), nullable=False, server_default="none"),
        sa.Column("provider_reference", sa.String(255)),
        sa.Column(
            "price_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "plan_id",
                "period_code",
                "currency",
                name="uq_billing_price_plan_period_currency",
            ),
        ),
    )
    _create_index("ix_billing_prices_plan_id", "billing_prices", ["plan_id"])
    _create_index(
        "ix_billing_prices_plan_enabled", "billing_prices", ["plan_id", "enabled"]
    )

    _create(
        "billing_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("billing_plans.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("licensed_seats", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "provider_customers",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "entitlements", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("suspended_at", sa.DateTime(timezone=True)),
        sa.Column("suspension_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "organization_id", name="uq_billing_accounts_organization"
            ),
        ),
    )
    _create_index(
        "ix_billing_accounts_organization_id",
        "billing_accounts",
        ["organization_id"],
        unique=True,
    )
    _create_index("ix_billing_accounts_plan_id", "billing_accounts", ["plan_id"])
    _create_index("ix_billing_accounts_status", "billing_accounts", ["status"])

    _create(
        "billing_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("billing_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            sa.String(36),
            sa.ForeignKey("billing_prices.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_reference", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("trial_end", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "subscription_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_subscription_provider_external",
            ),
        ),
    )
    for index, cols in {
        "ix_billing_subscriptions_organization_id": ["organization_id"],
        "ix_billing_subscriptions_plan_id": ["plan_id"],
        "ix_billing_subscriptions_price_id": ["price_id"],
        "ix_billing_subscriptions_status": ["status"],
        "ix_billing_subscriptions_org_status": ["organization_id", "status"],
    }.items():
        _create_index(index, "billing_subscriptions", cols)

    _create(
        "billing_checkout_sessions",
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
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("billing_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            sa.String(36),
            sa.ForeignKey("billing_prices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_reference", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("coupon_code", sa.String(80)),
        sa.Column("billing_country", sa.String(2)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "session_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "idempotency_key", name="uq_billing_checkout_idempotency"
            ),
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_checkout_provider_external",
            ),
        ),
    )
    for index, cols in {
        "ix_billing_checkout_sessions_organization_id": ["organization_id"],
        "ix_billing_checkout_sessions_user_id": ["user_id"],
        "ix_billing_checkout_sessions_plan_id": ["plan_id"],
        "ix_billing_checkout_sessions_price_id": ["price_id"],
        "ix_billing_checkout_sessions_status": ["status"],
        "ix_billing_checkout_org_created": ["organization_id", "created_at"],
    }.items():
        _create_index(index, "billing_checkout_sessions", cols)

    _create(
        "billing_invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.String(36),
            sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False, server_default="internal"),
        sa.Column("external_reference", sa.String(255)),
        sa.Column("number", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "subtotal_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "discount_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "amount_paid_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "amount_refunded_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "line_items", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column(
            "invoice_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_invoice_provider_external",
            ),
            sa.UniqueConstraint("number", name="uq_billing_invoices_number"),
        ),
    )
    for index, cols in {
        "ix_billing_invoices_organization_id": ["organization_id"],
        "ix_billing_invoices_subscription_id": ["subscription_id"],
        "ix_billing_invoices_number": ["number"],
        "ix_billing_invoices_status": ["status"],
        "ix_billing_invoices_org_status": ["organization_id", "status"],
    }.items():
        _create_index(index, "billing_invoices", cols)

    _create(
        "billing_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "invoice_id",
            sa.String(36),
            sa.ForeignKey("billing_invoices.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_reference", sa.String(255)),
        sa.Column(
            "transaction_type", sa.String(40), nullable=False, server_default="payment"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column(
            "transaction_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_transaction_provider_external",
            ),
            sa.UniqueConstraint(
                "idempotency_key", name="uq_billing_transaction_idempotency"
            ),
        ),
    )
    for index, cols in {
        "ix_billing_transactions_organization_id": ["organization_id"],
        "ix_billing_transactions_user_id": ["user_id"],
        "ix_billing_transactions_invoice_id": ["invoice_id"],
        "ix_billing_transactions_status": ["status"],
        "ix_billing_transactions_org_created": ["organization_id", "created_at"],
    }.items():
        _create_index(index, "billing_transactions", cols)

    _create(
        "billing_payment_methods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=False),
        sa.Column("method_type", sa.String(40), nullable=False),
        sa.Column("brand", sa.String(40)),
        sa.Column("last4", sa.String(4)),
        sa.Column("expiry_month", sa.Integer()),
        sa.Column("expiry_year", sa.Integer()),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_payment_method_external",
            ),
        ),
    )
    _create_index(
        "ix_billing_payment_methods_organization_id",
        "billing_payment_methods",
        ["organization_id"],
    )
    _create_index(
        "ix_billing_payment_methods_org_status",
        "billing_payment_methods",
        ["organization_id", "status"],
    )

    _create(
        "billing_refunds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(36),
            sa.ForeignKey("billing_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            sa.String(36),
            sa.ForeignKey("billing_invoices.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_reference", sa.String(255)),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "refund_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "idempotency_key", name="uq_billing_refund_idempotency"
            ),
            sa.UniqueConstraint(
                "provider",
                "external_reference",
                name="uq_billing_refund_provider_external",
            ),
        ),
    )
    for index, cols in {
        "ix_billing_refunds_organization_id": ["organization_id"],
        "ix_billing_refunds_transaction_id": ["transaction_id"],
        "ix_billing_refunds_invoice_id": ["invoice_id"],
        "ix_billing_refunds_status": ["status"],
    }.items():
        _create_index(index, "billing_refunds", cols)

    _create(
        "billing_webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "event_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("error", sa.Text()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "provider",
                "external_event_id",
                name="uq_billing_webhook_provider_event",
            ),
        ),
    )
    _create_index(
        "ix_billing_webhooks_status_received",
        "billing_webhook_events",
        ["status", "created_at"],
    )

    _create(
        "billing_coupons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("percent_off_basis_points", sa.Integer()),
        sa.Column("amount_off_minor", sa.BigInteger()),
        sa.Column("currency", sa.String(3)),
        sa.Column("max_redemptions", sa.Integer()),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "coupon_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(sa.UniqueConstraint("code", name="uq_billing_coupons_code"),),
    )
    _create_index("ix_billing_coupons_code", "billing_coupons", ["code"], unique=True)

    _create(
        "billing_coupon_redemptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "coupon_id",
            sa.String(36),
            sa.ForeignKey("billing_coupons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "checkout_session_id",
            sa.String(36),
            sa.ForeignKey("billing_checkout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "coupon_id", "checkout_session_id", name="uq_billing_coupon_checkout"
            ),
        ),
    )
    _create_index(
        "ix_billing_coupon_redemptions_coupon_id",
        "billing_coupon_redemptions",
        ["coupon_id"],
    )
    _create_index(
        "ix_billing_coupon_redemptions_organization_id",
        "billing_coupon_redemptions",
        ["organization_id"],
    )
    _create_index(
        "ix_billing_coupon_redemptions_checkout_session_id",
        "billing_coupon_redemptions",
        ["checkout_session_id"],
    )

    _create(
        "billing_tax_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("region_code", sa.String(80)),
        sa.Column("percentage_basis_points", sa.Integer(), nullable=False),
        sa.Column("inclusive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "country_code", "region_code", "code", name="uq_billing_tax_scope_code"
            ),
        ),
    )
    _create_index(
        "ix_billing_tax_rates_country_code", "billing_tax_rates", ["country_code"]
    )

    _create(
        "billing_usage_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(120), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("included_quantity", sa.BigInteger()),
        sa.Column(
            "billable_quantity", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("charge_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column(
            "usage_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "organization_id",
                "metric",
                "period_start",
                name="uq_billing_usage_period",
            ),
        ),
    )
    _create_index(
        "ix_billing_usage_records_organization_id",
        "billing_usage_records",
        ["organization_id"],
    )
    _create_index(
        "ix_billing_usage_org_period",
        "billing_usage_records",
        ["organization_id", "period_start", "period_end"],
    )

    _create(
        "billing_wallets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("balance_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "organization_id", name="uq_billing_wallets_organization"
            ),
        ),
    )
    _create_index(
        "ix_billing_wallets_organization_id",
        "billing_wallets",
        ["organization_id"],
        unique=True,
    )

    _create(
        "billing_wallet_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "wallet_id",
            sa.String(36),
            sa.ForeignKey("billing_wallets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("reference_type", sa.String(80)),
        sa.Column("reference_id", sa.String(160)),
        sa.Column("description", sa.Text()),
        sa.Column(
            "entry_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "idempotency_key", name="uq_billing_wallet_entry_idempotency"
            ),
        ),
    )
    _create_index(
        "ix_billing_wallet_entries_wallet_id", "billing_wallet_entries", ["wallet_id"]
    )
    _create_index(
        "ix_billing_wallet_entries_wallet_created",
        "billing_wallet_entries",
        ["wallet_id", "created_at"],
    )

    _create(
        "billing_licenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("billing_plans.id", ondelete="SET NULL"),
        ),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("seats", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "license_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.UniqueConstraint("key_hash", name="uq_billing_license_key_hash"),
        ),
    )
    _create_index(
        "ix_billing_licenses_organization_id", "billing_licenses", ["organization_id"]
    )
    _create_index("ix_billing_licenses_plan_id", "billing_licenses", ["plan_id"])
    _create_index(
        "ix_billing_licenses_org_status",
        "billing_licenses",
        ["organization_id", "status"],
    )

    _create(
        "billing_reconciliation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "requested_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index(
        "ix_billing_reconciliation_runs_status",
        "billing_reconciliation_runs",
        ["status"],
    )
    _create_index(
        "ix_billing_reconciliation_runs_requested_by_id",
        "billing_reconciliation_runs",
        ["requested_by_id"],
    )


def downgrade() -> None:
    for table in (
        "billing_reconciliation_runs",
        "billing_licenses",
        "billing_wallet_entries",
        "billing_wallets",
        "billing_usage_records",
        "billing_tax_rates",
        "billing_coupon_redemptions",
        "billing_coupons",
        "billing_webhook_events",
        "billing_refunds",
        "billing_payment_methods",
        "billing_transactions",
        "billing_invoices",
        "billing_checkout_sessions",
        "billing_subscriptions",
        "billing_accounts",
        "billing_prices",
        "billing_plans",
    ):
        if table in _tables(op.get_bind()):
            op.drop_table(table)
