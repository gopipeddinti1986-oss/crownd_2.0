"""Add manual verification and append-only platform administration records.

The initial migration creates current metadata on fresh databases, so this
revision is defensive and supports both historical 0007 schemas and fresh DBs.
Downgrade intentionally retains these additive structures and records.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008_platform_admin"
down_revision = "0007_campaign_intelligence"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {row["name"] for row in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "verification" not in _columns("creator_profiles"):
        op.add_column("creator_profiles", sa.Column("verification", sa.String(24), nullable=False, server_default="unverified"))
    tables = _tables()
    if "admin_audit_events" not in tables:
        op.create_table("admin_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("entity_type", sa.String(60), nullable=False),
            sa.Column("entity_id", sa.String(80), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "admin_disputes" not in tables:
        op.create_table("admin_disputes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("conversion_id", sa.Integer(), sa.ForeignKey("conversions.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("reward_id", sa.Integer(), sa.ForeignKey("rewards.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("summary", sa.String(500), nullable=False),
            sa.Column("opened_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('open','under_review','resolved')", name="ck_admin_dispute_status"),
        )
    if "admin_dispute_events" not in tables:
        op.create_table("admin_dispute_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dispute_id", sa.Integer(), sa.ForeignKey("admin_disputes.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("from_status", sa.String(20), nullable=True),
            sa.Column("to_status", sa.String(20), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    for table, column in (("admin_audit_events", "actor_id"), ("admin_audit_events", "action"), ("admin_audit_events", "entity_type"), ("admin_audit_events", "entity_id"), ("admin_audit_events", "created_at"), ("admin_disputes", "order_id"), ("admin_disputes", "conversion_id"), ("admin_disputes", "reward_id"), ("admin_disputes", "status"), ("admin_dispute_events", "dispute_id"), ("admin_dispute_events", "created_at")):
        name = f"ix_{table}_{column}"
        if not any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(table)):
            op.create_index(name, table, [column])
    dialect = op.get_bind().dialect.name
    immutable_tables = ("audit_logs", "admin_audit_events", "admin_dispute_events")
    if dialect == "postgresql":
        op.execute("CREATE OR REPLACE FUNCTION crownd_reject_admin_history_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Administrative history is append-only'; END; $$ LANGUAGE plpgsql")
        for table in immutable_tables:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
            op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION crownd_reject_admin_history_mutation()")
    elif dialect == "sqlite":
        for table in immutable_tables:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Administrative history is append-only'); END")


def downgrade():
    # A rollback must never erase administrative/audit/dispute history. The
    # additive structures are harmless to older code and remain for re-upgrade.
    pass
