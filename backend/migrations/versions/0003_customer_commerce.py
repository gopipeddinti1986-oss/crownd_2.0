"""Persistent customer carts, order line snapshots, inventory and checkout metadata.

Revision ID: 0003_customer_commerce
Revises: 0002_auth_security

The initial 0001 revision creates tables from live ORM metadata. Check catalog state
so both fresh installs (where 0001 already made the new schema) and deployed older
installations receive the same additive result.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_customer_commerce"
down_revision = "0002_auth_security"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def _checks(table: str) -> set[str]:
    return {constraint.get("name") for constraint in inspect(op.get_bind()).get_check_constraints(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    _add("products", sa.Column("sale_price", sa.Numeric(12, 2), nullable=True))
    _add("products", sa.Column("image_urls", sa.JSON(), nullable=True))
    _add("products", sa.Column("specifications", sa.JSON(), nullable=True))
    if "ck_product_sale_below_regular" not in _checks("products"):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("products") as batch:
                batch.create_check_constraint("ck_product_sale_below_regular", "sale_price IS NULL OR (sale_price > 0 AND sale_price < price)")
        else:
            op.create_check_constraint("ck_product_sale_below_regular", "products", "sale_price IS NULL OR (sale_price > 0 AND sale_price < price)")
    if "customer_id" not in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_orders_customer_id_users", "users", ["customer_id"], ["id"], ondelete="SET NULL")
    for column in (
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("shipping_name", sa.String(120), nullable=True),
        sa.Column("shipping_phone", sa.String(32), nullable=True),
        sa.Column("shipping_line1", sa.String(200), nullable=True),
        sa.Column("shipping_line2", sa.String(200), nullable=True),
        sa.Column("shipping_city", sa.String(100), nullable=True),
        sa.Column("shipping_state", sa.String(100), nullable=True),
        sa.Column("shipping_postal_code", sa.String(20), nullable=True),
        sa.Column("shipping_country", sa.String(2), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ):
        _add("orders", column)
    _index("ix_orders_customer_id", "orders", ["customer_id"])
    _index("uq_order_customer_idempotency", "orders", ["customer_id", "idempotency_key"], unique=True)

    tables = _tables()
    if "carts" not in tables:
        op.create_table(
            "carts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", name="uq_carts_user_id"),
        )
    _index("ix_carts_user_id", "carts", ["user_id"], unique=True)
    tables = _tables()
    if "cart_items" not in tables:
        op.create_table(
            "cart_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cart_id", sa.Integer(), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),
            sa.CheckConstraint("quantity > 0", name="ck_cart_item_positive_quantity"),
        )
    _index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    _index("ix_cart_items_product_id", "cart_items", ["product_id"])
    tables = _tables()
    if "order_items" not in tables:
        op.create_table(
            "order_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
            sa.Column("product_name", sa.String(160), nullable=False),
            sa.Column("brand_name", sa.String(120), nullable=False),
            sa.Column("image_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
            sa.CheckConstraint("quantity > 0", name="ck_order_item_positive_quantity"),
        )
    _index("ix_order_items_order_id", "order_items", ["order_id"])
    _index("ix_order_items_product_id", "order_items", ["product_id"])


def downgrade():
    tables = _tables()
    if "order_items" in tables:
        op.drop_table("order_items")
    if "cart_items" in tables:
        op.drop_table("cart_items")
    if "carts" in tables:
        op.drop_table("carts")
    indexes = _indexes("orders")
    if "uq_order_customer_idempotency" in indexes:
        op.drop_index("uq_order_customer_idempotency", table_name="orders")
    if "ix_orders_customer_id" in indexes:
        op.drop_index("ix_orders_customer_id", table_name="orders")
    order_columns = _columns("orders")
    with op.batch_alter_table("orders") as batch:
        for column in ("updated_at", "shipping_country", "shipping_postal_code", "shipping_state", "shipping_city", "shipping_line2", "shipping_line1", "shipping_phone", "shipping_name", "idempotency_key", "customer_id"):
            if column in order_columns:
                batch.drop_column(column)
    product_columns = _columns("products")
    product_checks = _checks("products")
    with op.batch_alter_table("products") as batch:
        if "ck_product_sale_below_regular" in product_checks:
            batch.drop_constraint("ck_product_sale_below_regular", type_="check")
        for column in ("specifications", "image_urls", "sale_price"):
            if column in product_columns:
                batch.drop_column(column)
