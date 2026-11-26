"""Add demo/COD payment metadata and auditable payment attempts.

Revision ID: 0004_payment_options
Revises: 0003_customer_commerce
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_payment_options"
down_revision = "0003_customer_commerce"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _checks(table):
    return {constraint.get("name") for constraint in inspect(op.get_bind()).get_check_constraints(table)}


def _add(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name, table, columns, unique=False):
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    _add("orders", sa.Column("payment_method", sa.String(16), nullable=False, server_default="legacy"))
    _add("orders", sa.Column("currency", sa.String(3), nullable=False, server_default="INR"))
    _add("orders", sa.Column("transaction_reference", sa.String(80), nullable=True))
    _add("orders", sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    if "payment_confirmed_by" not in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.add_column(sa.Column("payment_confirmed_by", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_orders_payment_confirmed_by_users", "users", ["payment_confirmed_by"], ["id"], ondelete="SET NULL")
    _add("orders", sa.Column("payment_notes", sa.Text(), nullable=True))
    _create_index("ix_orders_transaction_reference", "orders", ["transaction_reference"])
    _create_index("ix_orders_payment_confirmed_by", "orders", ["payment_confirmed_by"])
    checks = _checks("orders")
    if "ck_orders_payment_method" not in checks:
        with op.batch_alter_table("orders") as batch:
            batch.create_check_constraint("ck_orders_payment_method", "payment_method IN ('demo','cod','online','legacy')")
    if "ck_orders_payment_status" not in _checks("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.create_check_constraint("ck_orders_payment_status", "payment_status IN ('pending','unpaid','paid','failed','refunded','partially_refunded','not_required')")

    if "payment_attempts" not in _tables():
        op.create_table(
            "payment_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("payment_method", sa.String(16), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
            sa.Column("transaction_reference", sa.String(80), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("order_id", "attempt_number", name="uq_payment_attempt_number"),
            sa.UniqueConstraint("order_id", "idempotency_key", name="uq_payment_attempt_key"),
            sa.CheckConstraint("attempt_number > 0", name="ck_payment_attempt_number_positive"),
            sa.CheckConstraint("payment_method IN ('demo','cod','online')", name="ck_payment_attempt_method"),
            sa.CheckConstraint("status IN ('unpaid','pending','paid','failed','refunded','partially_refunded','not_required')", name="ck_payment_attempt_status"),
        )
    _create_index("ix_payment_attempts_order_id", "payment_attempts", ["order_id"])
    _create_index("ix_payment_attempts_transaction_reference", "payment_attempts", ["transaction_reference"])
    _add("rewards", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Pre-Phase-3 simulator provenance cannot be verified. Keep all rewards linked
    # to legacy orders non-payable rather than treating historical simulator rows
    # as genuine collection.
    op.execute(sa.text("UPDATE rewards SET is_demo = TRUE WHERE order_id IN (SELECT id FROM orders WHERE payment_method = 'legacy')"))


def downgrade():
    if "payment_attempts" in _tables():
        op.drop_table("payment_attempts")
    for name in ("ix_orders_transaction_reference", "ix_orders_payment_confirmed_by"):
        if name in _indexes("orders"):
            op.drop_index(name, table_name="orders")
    order_checks = _checks("orders")
    with op.batch_alter_table("orders") as batch:
        for name in ("ck_orders_payment_status", "ck_orders_payment_method"):
            if name in order_checks:
                batch.drop_constraint(name, type_="check")
        columns = _columns("orders")
        for name in ("payment_notes", "payment_confirmed_by", "payment_confirmed_at", "transaction_reference", "currency", "payment_method"):
            if name in columns:
                batch.drop_column(name)
    if "is_demo" in _columns("rewards"):
        op.drop_column("rewards", "is_demo")
