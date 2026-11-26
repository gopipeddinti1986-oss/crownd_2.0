"""Durable referral attribution and order conversion lifecycle.

Revision ID: 0005_referral_attribution
Revises: 0004_payment_options
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_referral_attribution"
down_revision = "0004_payment_options"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _has_fk(table, column, referred_table):
    return any(fk.get("constrained_columns") == [column] and fk.get("referred_table") == referred_table for fk in inspect(op.get_bind()).get_foreign_keys(table))


def _index(name, table, column, *, unique=False):
    if name not in _indexes(table):
        op.create_index(name, table, [column], unique=unique)


def _create_tables():
    if "campaign_products" not in _tables():
        op.create_table(
            "campaign_products",
            sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "visitor_attributions" not in _tables():
        op.create_table(
            "visitor_attributions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("visitor_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("first_referral_id", sa.Integer(), sa.ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("last_referral_id", sa.Integer(), sa.ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("first_touch_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_touch_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "referral_activities" not in _tables():
        op.create_table(
            "referral_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("referral_id", sa.Integer(), sa.ForeignKey("referrals.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("visitor_hash", sa.String(64), nullable=False),
            sa.Column("event_type", sa.String(24), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("event_type IN ('product_view','cart_add')", name="ck_referral_activity_type"),
        )
    if "conversions" not in _tables():
        op.create_table(
            "conversions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, unique=True),
            sa.Column("referral_id", sa.Integer(), sa.ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("creator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
            sa.Column("visitor_hash", sa.String(64), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("attributed_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reason", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('pending','confirmed','cancelled','reversed','ineligible')", name="ck_conversion_status"),
        )
    if "conversion_events" not in _tables():
        op.create_table(
            "conversion_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conversion_id", sa.Integer(), sa.ForeignKey("conversions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("event_key", sa.String(120), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("from_status", sa.String(20), nullable=True),
            sa.Column("to_status", sa.String(20), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reason", sa.String(120), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("conversion_id", "event_key", name="uq_conversion_event_key"),
        )
    if "referral_risk_flags" not in _tables():
        op.create_table(
            "referral_risk_flags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("risk_code", sa.String(40), nullable=False),
            sa.Column("referral_id", sa.Integer(), sa.ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True),
            sa.Column("conversion_id", sa.Integer(), sa.ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("visitor_hash", sa.String(64), nullable=True),
            sa.Column("details", sa.String(240), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('open','reviewed','dismissed')", name="ck_referral_risk_status"),
        )


def upgrade():
    _create_tables()
    if "product_id" not in _columns("referrals"):
        op.add_column("referrals", sa.Column("product_id", sa.Integer(), nullable=True))
    if not _has_fk("referrals", "product_id", "products"):
        with op.batch_alter_table("referrals") as batch:
            batch.create_foreign_key("fk_referrals_product_id_products", "products", ["product_id"], ["id"], ondelete="RESTRICT")
    _index("ix_referrals_product_id", "referrals", "product_id")

    for name, column, sql_type, nullable, default in (
        ("destination", "destination", sa.String(300), False, "/shop"),
        ("referrer_origin", "referrer_origin", sa.String(255), True, None),
        ("device_category", "device_category", sa.String(20), False, "unknown"),
        ("status", "status", sa.String(20), False, "valid"),
    ):
        if column not in _columns("referral_clicks"):
            op.add_column("referral_clicks", sa.Column(column, sql_type, nullable=nullable, server_default=default))
    _index("ix_referral_clicks_clicked_at", "referral_clicks", "clicked_at")
    _index("ix_referral_clicks_session_hash", "referral_clicks", "session_hash")

    for name, table, column, unique in (
        ("ix_visitor_attributions_visitor_hash", "visitor_attributions", "visitor_hash", True),
        ("ix_visitor_attributions_first_referral_id", "visitor_attributions", "first_referral_id", False),
        ("ix_visitor_attributions_last_referral_id", "visitor_attributions", "last_referral_id", False),
        ("ix_visitor_attributions_customer_id", "visitor_attributions", "customer_id", False),
        ("ix_visitor_attributions_last_touch_at", "visitor_attributions", "last_touch_at", False),
        ("ix_visitor_attributions_expires_at", "visitor_attributions", "expires_at", False),
    ):
        _index(name, table, column, unique=unique)
    for name, column in (("ix_referral_activities_referral_id", "referral_id"), ("ix_referral_activities_visitor_hash", "visitor_hash"), ("ix_referral_activities_event_type", "event_type"), ("ix_referral_activities_product_id", "product_id"), ("ix_referral_activities_created_at", "created_at")):
        _index(name, "referral_activities", column)
    for name, column, unique in (("ix_conversions_order_id", "order_id", True), ("ix_conversions_referral_id", "referral_id", False), ("ix_conversions_creator_id", "creator_id", False), ("ix_conversions_campaign_id", "campaign_id", False), ("ix_conversions_visitor_hash", "visitor_hash", False), ("ix_conversions_status", "status", False), ("ix_conversions_created_at", "created_at", False)):
        _index(name, "conversions", column, unique=unique)
    _index("ix_conversion_events_conversion_id", "conversion_events", "conversion_id")
    for name, column in (("ix_referral_risk_flags_risk_code", "risk_code"), ("ix_referral_risk_flags_referral_id", "referral_id"), ("ix_referral_risk_flags_conversion_id", "conversion_id"), ("ix_referral_risk_flags_customer_id", "customer_id"), ("ix_referral_risk_flags_visitor_hash", "visitor_hash"), ("ix_referral_risk_flags_status", "status"), ("ix_referral_risk_flags_created_at", "created_at")):
        _index(name, "referral_risk_flags", column)

    if "referral_id" not in _columns("order_items"):
        op.add_column("order_items", sa.Column("referral_id", sa.Integer(), nullable=True))
    if not _has_fk("order_items", "referral_id", "referrals"):
        with op.batch_alter_table("order_items") as batch:
            batch.create_foreign_key("fk_order_items_referral_id_referrals", "referrals", ["referral_id"], ["id"], ondelete="SET NULL")
    _index("ix_order_items_referral_id", "order_items", "referral_id")

    op.execute(sa.text("""
        INSERT INTO conversions (order_id, referral_id, creator_id, campaign_id, visitor_hash, status,
            attributed_amount, currency, is_demo, reason, created_at, confirmed_at, updated_at)
        SELECT o.id, r.id, r.creator_id, r.campaign_id, NULL, 'ineligible', 0, COALESCE(o.currency, 'INR'),
            CASE WHEN o.payment_method = 'demo' THEN TRUE ELSE FALSE END,
            'historical_not_revalidated', CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
        FROM orders o JOIN referrals r ON r.id = o.referral_id
        WHERE NOT EXISTS (SELECT 1 FROM conversions c WHERE c.order_id = o.id)
    """))


def downgrade():
    # Current Base.metadata is imported by the historical initial revision, so
    # all objects may already exist. Remove Phase 4 objects idempotently.
    tables = _tables()
    for table in ("referral_risk_flags", "conversion_events", "conversions", "referral_activities", "visitor_attributions"):
        if table in _tables(): op.drop_table(table)
    if "referral_id" in _columns("order_items"):
        with op.batch_alter_table("order_items") as batch:
            if "ix_order_items_referral_id" in _indexes("order_items"): batch.drop_index("ix_order_items_referral_id")
            fk=next((x for x in inspect(op.get_bind()).get_foreign_keys("order_items") if x.get("constrained_columns")==["referral_id"] and x.get("referred_table")=="referrals"),None)
            if fk and fk.get("name"): batch.drop_constraint(fk["name"], type_="foreignkey")
            batch.drop_column("referral_id")
    click_columns=_columns("referral_clicks")
    click_indexes=_indexes("referral_clicks")
    if any(name in click_columns for name in ("status","device_category","referrer_origin","destination")):
        with op.batch_alter_table("referral_clicks") as batch:
            for name in ("ix_referral_clicks_session_hash","ix_referral_clicks_clicked_at"):
                if name in click_indexes: batch.drop_index(name)
            for column in ("status","device_category","referrer_origin","destination"):
                if column in click_columns: batch.drop_column(column)
    if "product_id" in _columns("referrals"):
        indexes=_indexes("referrals")
        with op.batch_alter_table("referrals") as batch:
            if "ix_referrals_product_id" in indexes: batch.drop_index("ix_referrals_product_id")
            if _has_fk("referrals","product_id","products"):
                fk=next((x for x in inspect(op.get_bind()).get_foreign_keys("referrals") if x.get("constrained_columns")==["product_id"] and x.get("referred_table")=="products"),None)
                if fk and fk.get("name"): batch.drop_constraint(fk["name"],type_="foreignkey")
            batch.drop_column("product_id")
    if "campaign_products" in _tables(): op.drop_table("campaign_products")
