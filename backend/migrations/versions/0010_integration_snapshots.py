"""Freeze checkout reward terms and track dispute reward holds.

These additive fields preserve the reward terms and the review state that were
valid when an attributed order was placed. Existing rows remain NULL/false and
continue through the legacy compatibility path.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010_integration_snapshots"
down_revision = "0009_notifications"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    order_item_columns = _columns("order_items")
    if "reward_snapshot" not in order_item_columns:
        op.add_column("order_items", sa.Column("reward_snapshot", sa.JSON(), nullable=True))
    reward_columns = _columns("rewards")
    if "dispute_hold" not in reward_columns:
        op.add_column("rewards", sa.Column("dispute_hold", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "dispute_prior_status" not in reward_columns:
        op.add_column("rewards", sa.Column("dispute_prior_status", sa.String(24), nullable=True))
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE OR REPLACE FUNCTION crownd_reject_order_item_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Order item snapshots are immutable; preserve history and append corrections'; END; $$ LANGUAGE plpgsql")
        op.execute("DROP TRIGGER IF EXISTS order_items_append_only ON order_items")
        op.execute("CREATE TRIGGER order_items_append_only BEFORE UPDATE OR DELETE ON order_items FOR EACH ROW EXECUTE FUNCTION crownd_reject_order_item_mutation()")
    elif dialect == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER IF NOT EXISTS order_items_no_{action.lower()} BEFORE {action} ON order_items BEGIN SELECT RAISE(ABORT, 'Order item snapshots are immutable'); END")


def downgrade() -> None:
    # Preserve historical checkout and dispute context on downgrade. The columns
    # are additive and safe for older application code to ignore.
    pass
