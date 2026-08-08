"""Mobile store billing foundation and lifecycle persistence.

Revision ID: 20260809_0012
Revises: 20260807_0011
"""
from alembic import op
import sqlalchemy as sa
revision="20260809_0012"; down_revision="20260807_0011"; branch_labels=None; depends_on=None

def _tables()->set[str]: return set(sa.inspect(op.get_bind()).get_table_names())
def _create(name:str,*columns:sa.Column,constraints:tuple=()):
    if name not in _tables(): op.create_table(name,*columns,*constraints)
def _index(name:str,table:str,columns:list[str]):
    if table not in _tables(): return
    if name not in {x['name'] for x in sa.inspect(op.get_bind()).get_indexes(table)}: op.create_index(name,table,columns)
def _drop_index(name:str,table:str):
    if table in _tables() and name in {x['name'] for x in sa.inspect(op.get_bind()).get_indexes(table)}: op.drop_index(name,table_name=table)

def upgrade()->None:
    _create("mobile_store_products",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("plan_id",sa.String(36),sa.ForeignKey("billing_plans.id",ondelete="CASCADE"),nullable=False),sa.Column("price_id",sa.String(36),sa.ForeignKey("billing_prices.id",ondelete="CASCADE"),nullable=False),sa.Column("store",sa.String(24),nullable=False),sa.Column("product_id",sa.String(255),nullable=False),sa.Column("base_plan_id",sa.String(255)),sa.Column("offer_id",sa.String(255)),sa.Column("status",sa.String(32),nullable=False,server_default="inactive"),sa.Column("store_metadata",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),constraints=(sa.UniqueConstraint("store","product_id","base_plan_id","offer_id",name="uq_mobile_store_product_ref"),))
    _index("ix_mobile_store_products_plan_status","mobile_store_products",["plan_id","status"])
    _create("mobile_store_purchases",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id",ondelete="CASCADE"),nullable=False),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("product_id",sa.String(36),sa.ForeignKey("mobile_store_products.id",ondelete="RESTRICT"),nullable=False),sa.Column("store",sa.String(24),nullable=False),sa.Column("external_transaction_id",sa.String(255)),sa.Column("original_transaction_id",sa.String(255)),sa.Column("purchase_token_hash",sa.String(64)),sa.Column("purchase_token_ciphertext",sa.Text()),sa.Column("status",sa.String(32),nullable=False,server_default="pending_verification"),sa.Column("verified",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("auto_renewing",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("purchased_at",sa.DateTime(timezone=True)),sa.Column("expires_at",sa.DateTime(timezone=True)),sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Column("verification_metadata",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),constraints=(sa.UniqueConstraint("store","external_transaction_id",name="uq_mobile_store_purchase_transaction"),))
    _index("ix_mobile_store_purchases_org_status","mobile_store_purchases",["organization_id","status"]); _index("ix_mobile_store_purchases_user_store","mobile_store_purchases",["user_id","store"]); _index("ix_mobile_store_purchases_original_transaction_id","mobile_store_purchases",["original_transaction_id"]); _index("ix_mobile_store_purchases_purchase_token_hash","mobile_store_purchases",["purchase_token_hash"])
    _create("mobile_store_events",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("store",sa.String(24),nullable=False),sa.Column("external_event_id",sa.String(255),nullable=False),sa.Column("event_type",sa.String(160),nullable=False),sa.Column("payload_hash",sa.String(64),nullable=False),sa.Column("status",sa.String(32),nullable=False,server_default="received"),sa.Column("event_payload",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),sa.Column("error",sa.Text()),sa.Column("processed_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),constraints=(sa.UniqueConstraint("store","external_event_id",name="uq_mobile_store_event_external"),))
    _index("ix_mobile_store_events_status_created","mobile_store_events",["status","created_at"])

def downgrade()->None:
    _drop_index("ix_mobile_store_events_status_created","mobile_store_events")
    if "mobile_store_events" in _tables(): op.drop_table("mobile_store_events")
    for name in ["ix_mobile_store_purchases_purchase_token_hash","ix_mobile_store_purchases_original_transaction_id","ix_mobile_store_purchases_user_store","ix_mobile_store_purchases_org_status"]: _drop_index(name,"mobile_store_purchases")
    if "mobile_store_purchases" in _tables(): op.drop_table("mobile_store_purchases")
    _drop_index("ix_mobile_store_products_plan_status","mobile_store_products")
    if "mobile_store_products" in _tables(): op.drop_table("mobile_store_products")
