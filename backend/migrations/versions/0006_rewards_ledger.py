"""Creator reward rules, line-level rewards and append-only ledger provenance.

Revision ID: 0006_rewards_ledger
Revises: 0005_referral_attribution
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_rewards_ledger"
down_revision = "0005_referral_attribution"
branch_labels = None
depends_on = None


def _tables(): return set(inspect(op.get_bind()).get_table_names())
def _columns(table): return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}
def _indexes(table): return {i["name"] for i in inspect(op.get_bind()).get_indexes(table)}
def _uniques(table): return inspect(op.get_bind()).get_unique_constraints(table)
def _has_fk(table, column, referred): return any(f.get("constrained_columns")==[column] and f.get("referred_table")==referred for f in inspect(op.get_bind()).get_foreign_keys(table))
def _index(name, table, columns, unique=False):
    if name not in _indexes(table): op.create_index(name, table, columns, unique=unique)


def _unique_exists(table, columns):
    columns=set(columns)
    if any(set(row.get("column_names") or [])==columns for row in _uniques(table)): return True
    return any(index.get("unique") and set(index.get("column_names") or [])==columns for index in inspect(op.get_bind()).get_indexes(table))


def _unique_index(name, table, columns):
    if not _unique_exists(table,columns): _index(name,table,columns,unique=True)


def _install_immutability_triggers():
    dialect=op.get_bind().dialect.name
    if dialect=="postgresql":
        op.execute("CREATE OR REPLACE FUNCTION crownd_reject_financial_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Financial history is append-only'; END; $$ LANGUAGE plpgsql")
        for table in ("ledger_entries","reward_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
            op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION crownd_reject_financial_mutation()")
    elif dialect=="sqlite":
        for table in ("ledger_entries","reward_events"):
            for action in ("UPDATE","DELETE"):
                op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Financial history is append-only'); END")


def _remove_immutability_triggers():
    dialect=op.get_bind().dialect.name
    if dialect=="postgresql":
        for table in ("ledger_entries","reward_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS crownd_reject_financial_mutation()")
    elif dialect=="sqlite":
        for table in ("ledger_entries","reward_events"):
            for action in ("update","delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{action}")


def _create_new_tables():
    if "reward_rules" not in _tables():
        op.create_table("reward_rules",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("campaign_id",sa.Integer(),sa.ForeignKey("campaigns.id",ondelete="CASCADE"),nullable=False),
            sa.Column("product_id",sa.Integer(),sa.ForeignKey("products.id",ondelete="RESTRICT"),nullable=True),
            sa.Column("scope_key",sa.String(80),nullable=False,unique=True),
            sa.Column("reward_type",sa.String(16),nullable=False),
            sa.Column("rate",sa.Numeric(7,3),nullable=True),
            sa.Column("fixed_amount",sa.Numeric(12,2),nullable=True),
            sa.Column("currency",sa.String(3),nullable=False,server_default="INR"),
            sa.Column("minimum_eligible_amount",sa.Numeric(12,2),nullable=False,server_default="0.00"),
            sa.Column("max_reward",sa.Numeric(12,2),nullable=True),
            sa.Column("max_creator_total",sa.Numeric(14,2),nullable=True),
            sa.Column("max_campaign_total",sa.Numeric(14,2),nullable=True),
            sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()),
            sa.Column("valid_from",sa.DateTime(timezone=True),nullable=True),
            sa.Column("valid_until",sa.DateTime(timezone=True),nullable=True),
            sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True),
            sa.Column("updated_by",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True),
            sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
            sa.CheckConstraint("reward_type IN ('percentage','fixed')",name="ck_reward_rule_type"),
            sa.CheckConstraint("currency = 'INR'",name="ck_reward_rule_currency"),
            sa.CheckConstraint("minimum_eligible_amount >= 0",name="ck_reward_rule_minimum"),
            sa.CheckConstraint("rate IS NULL OR (rate >= 0 AND rate <= 100)",name="ck_reward_rule_rate"),
            sa.CheckConstraint("fixed_amount IS NULL OR fixed_amount >= 0",name="ck_reward_rule_fixed"))
    if "reward_events" not in _tables():
        op.create_table("reward_events",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("reward_id",sa.Integer(),sa.ForeignKey("rewards.id",ondelete="RESTRICT"),nullable=False),
            sa.Column("event_key",sa.String(140),nullable=False),sa.Column("event_type",sa.String(32),nullable=False),
            sa.Column("from_status",sa.String(24),nullable=True),sa.Column("to_status",sa.String(24),nullable=False),
            sa.Column("reason",sa.String(240),nullable=True),sa.Column("actor_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True),
            sa.Column("metadata_json",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint("reward_id","event_key",name="uq_reward_event_key"))
    if "simulated_payouts" not in _tables():
        op.create_table("simulated_payouts",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("reward_id",sa.Integer(),sa.ForeignKey("rewards.id",ondelete="RESTRICT"),nullable=False,unique=True),
            sa.Column("creator_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
            sa.Column("amount",sa.Numeric(12,2),nullable=False),sa.Column("currency",sa.String(3),nullable=False,server_default="INR"),
            sa.Column("reference",sa.String(80),nullable=False,unique=True),sa.Column("actor_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
            sa.Column("disclosure",sa.String(120),nullable=False,server_default="Simulation only — no actual money was transferred."),
            sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))


def upgrade():
    _create_new_tables()
    # Add cart-item attribution to make mixed creator/product baskets possible
    # without changing the existing order-level Conversion identity.
    if "referral_id" not in _columns("cart_items"):
        with op.batch_alter_table("cart_items") as batch:
            batch.add_column(sa.Column("referral_id",sa.Integer(),nullable=True))
            batch.create_foreign_key("fk_cart_items_referral_id_referrals","referrals",["referral_id"],["id"],ondelete="SET NULL")
    _index("ix_cart_items_referral_id","cart_items",["referral_id"])

    reward_columns=[
        ("brand_id",sa.Integer(),"users","SET NULL"),("campaign_id",sa.Integer(),"campaigns","SET NULL"),
        ("conversion_id",sa.Integer(),"conversions","SET NULL"),("referral_id",sa.Integer(),"referrals","SET NULL"),("order_item_id",sa.Integer(),"order_items","SET NULL"),
        ("product_id",sa.Integer(),"products","SET NULL"),("reward_rule_id",sa.Integer(),"reward_rules","SET NULL")]
    missing=[(name,typ,table,ondelete) for name,typ,table,ondelete in reward_columns if name not in _columns("rewards")]
    scalar_columns=[
        sa.Column("source_key",sa.String(120),nullable=True),sa.Column("eligible_amount",sa.Numeric(12,2),nullable=False,server_default="0.00"),
        sa.Column("excluded_amount",sa.Numeric(12,2),nullable=False,server_default="0.00"),sa.Column("currency",sa.String(3),nullable=False,server_default="INR"),
        sa.Column("reward_type",sa.String(16),nullable=True),sa.Column("reward_rate",sa.Numeric(7,3),nullable=True),
        sa.Column("fixed_amount",sa.Numeric(12,2),nullable=True),sa.Column("calculation_formula",sa.String(240),nullable=True),
        sa.Column("rounding_rule",sa.String(32),nullable=False,server_default="ROUND_HALF_UP"),sa.Column("calculation_snapshot",sa.JSON(),nullable=True),
        sa.Column("risk_status",sa.String(20),nullable=False,server_default="clear"),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=True)]
    scalar_columns=[c for c in scalar_columns if c.name not in _columns("rewards")]
    reward_unique=any(u.get("column_names")==["order_id"] for u in _uniques("rewards"))
    if missing or scalar_columns or reward_unique:
        convention={"uq":"uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("rewards",recreate="always" if reward_unique else "auto",naming_convention=convention) as batch:
            if reward_unique: batch.drop_constraint("uq_rewards_order_id",type_="unique")
            for name,typ,table,ondelete in missing:
                batch.add_column(sa.Column(name,typ,nullable=True))
                batch.create_foreign_key(f"fk_rewards_{name}_{table}",table,[name],["id"],ondelete=ondelete)
            for column in scalar_columns: batch.add_column(column)

    # Legacy reward rows receive a stable source key and an explicit historical
    # snapshot marker; no amount or eligible basis is inferred or recalculated.
    op.execute(sa.text("UPDATE rewards SET source_key = 'legacy:' || CAST(id AS VARCHAR) WHERE source_key IS NULL"))
    if "referral_id" in _columns("rewards"):
        op.execute(sa.text("UPDATE rewards SET referral_id = (SELECT o.referral_id FROM orders o WHERE o.id = rewards.order_id) WHERE referral_id IS NULL"))
    if "campaign_id" in _columns("rewards"):
        op.execute(sa.text("UPDATE rewards SET campaign_id = (SELECT c.campaign_id FROM conversions c WHERE c.order_id = rewards.order_id) WHERE campaign_id IS NULL"))
        op.execute(sa.text("UPDATE rewards SET campaign_id = (SELECT r.campaign_id FROM orders o JOIN referrals r ON r.id=o.referral_id WHERE o.id=rewards.order_id) WHERE campaign_id IS NULL"))
    if "brand_id" in _columns("rewards"):
        op.execute(sa.text("UPDATE rewards SET brand_id = (SELECT c.brand_id FROM campaigns c WHERE c.id=rewards.campaign_id) WHERE brand_id IS NULL"))
    if "conversion_id" in _columns("rewards"):
        op.execute(sa.text("UPDATE rewards SET conversion_id = (SELECT c.id FROM conversions c WHERE c.order_id=rewards.order_id) WHERE conversion_id IS NULL"))
    op.execute(sa.text("UPDATE rewards SET updated_at = COALESCE(updated_at, created_at) WHERE updated_at IS NULL"))
    snapshot="{\"legacy\":true,\"basis\":\"unverified\"}"
    cast="CAST(:snapshot AS JSON)" if op.get_bind().dialect.name=="postgresql" else ":snapshot"
    op.get_bind().execute(sa.text(f"UPDATE rewards SET calculation_snapshot = {cast} WHERE calculation_snapshot IS NULL AND source_key LIKE 'legacy:%'"), {"snapshot":snapshot})

    ledger_specs=[
        ("direction",sa.String(16),None),("idempotency_key",sa.String(140),None),("reward_id",sa.Integer(),"rewards"),
        ("order_id",sa.Integer(),"orders"),("conversion_id",sa.Integer(),"conversions"),("campaign_id",sa.Integer(),"campaigns"),
        ("reversal_of_id",sa.Integer(),"ledger_entries"),("actor_id",sa.Integer(),"users"),("description",sa.String(240),None)]
    ledger_missing=[s for s in ledger_specs if s[0] not in _columns("ledger_entries")]
    if ledger_missing:
        with op.batch_alter_table("ledger_entries") as batch:
            for name,typ,table in ledger_missing:
                nullable=name!="direction" and name!="description"
                default="credit" if name=="direction" else ("" if name=="description" else None)
                batch.add_column(sa.Column(name,typ,nullable=nullable,server_default=default))
                if table: batch.create_foreign_key(f"fk_ledger_{name}_{table}",table,[name],["id"],ondelete="RESTRICT" if name=="reversal_of_id" else "SET NULL")
    op.execute(sa.text("UPDATE ledger_entries SET direction = CASE WHEN entry_type LIKE 'demo_%' THEN 'memo' ELSE COALESCE(direction,'credit') END WHERE direction IS NULL OR direction='credit'"))
    op.execute(sa.text("UPDATE ledger_entries SET order_id = (SELECT o.id FROM orders o WHERE o.public_id=ledger_entries.reference) WHERE order_id IS NULL"))
    op.execute(sa.text("UPDATE ledger_entries SET reward_id = (SELECT r.id FROM rewards r WHERE r.order_id=ledger_entries.order_id AND r.creator_id=ledger_entries.user_id LIMIT 1) WHERE reward_id IS NULL AND order_id IS NOT NULL"))
    op.execute(sa.text("UPDATE ledger_entries SET conversion_id = (SELECT c.id FROM conversions c WHERE c.order_id=ledger_entries.order_id) WHERE conversion_id IS NULL AND order_id IS NOT NULL"))
    op.execute(sa.text("UPDATE ledger_entries SET campaign_id = (SELECT r.campaign_id FROM rewards r WHERE r.id=ledger_entries.reward_id) WHERE campaign_id IS NULL AND reward_id IS NOT NULL"))
    _unique_index("uq_ledger_entries_idempotency_key","ledger_entries",["idempotency_key"])
    _unique_index("uq_ledger_entries_reversal_of_id","ledger_entries",["reversal_of_id"])
    for name,column in (("ix_rewards_order_id","order_id"),("ix_rewards_brand_id","brand_id"),("ix_rewards_campaign_id","campaign_id"),("ix_rewards_conversion_id","conversion_id"),("ix_rewards_referral_id","referral_id"),("ix_rewards_order_item_id","order_item_id"),("ix_rewards_product_id","product_id"),("ix_rewards_reward_rule_id","reward_rule_id"),("ix_rewards_risk_status","risk_status")):
        _index(name,"rewards",[column])
    for name,column in (("ix_reward_rules_campaign_id","campaign_id"),("ix_reward_rules_product_id","product_id"),("ix_reward_rules_active","active")):
        _index(name,"reward_rules",[column])
    _index("ix_reward_events_reward_id","reward_events",["reward_id"])
    _unique_index("uq_rewards_source_key","rewards",["source_key"])
    _install_immutability_triggers()


def downgrade():
    duplicates=op.get_bind().execute(sa.text("SELECT order_id, COUNT(*) FROM rewards GROUP BY order_id HAVING COUNT(*) > 1 LIMIT 1")).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade rewards migration: multiple reward rows now exist for one order.")
    # A rollback must not silently discard Phase 5 rules, lifecycle events,
    # simulated payout records, item-level reward provenance or ledger keys.
    for table in ("simulated_payouts","reward_events","reward_rules"):
        if table in _tables() and op.get_bind().execute(sa.text(f'SELECT 1 FROM "{table}" LIMIT 1')).first():
            raise RuntimeError(f"Cannot downgrade rewards migration: {table} contains Phase 5 records.")
    if "referral_id" in _columns("cart_items") and op.get_bind().execute(sa.text("SELECT 1 FROM cart_items WHERE referral_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade rewards migration: cart items contain Phase 5 referral attribution.")
    if "source_key" in _columns("rewards") and op.get_bind().execute(sa.text("SELECT 1 FROM rewards WHERE source_key LIKE 'reward:%' LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade rewards migration: Phase 5 generated rewards exist.")
    if "idempotency_key" in _columns("ledger_entries") and op.get_bind().execute(sa.text("SELECT 1 FROM ledger_entries WHERE idempotency_key IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade rewards migration: idempotent Phase 5 ledger entries exist.")
    _remove_immutability_triggers()
    # Remove phase-specific ledger references before dropping their referenced tables.
    # This ordering is important for SQLite batch-table reflection.

    ledger_drop=[n for n in ("direction","idempotency_key","reward_id","order_id","conversion_id","campaign_id","reversal_of_id","actor_id","description") if n in _columns("ledger_entries")]
    if ledger_drop:
        indexes=inspect(op.get_bind()).get_indexes("ledger_entries")
        uniques=inspect(op.get_bind()).get_unique_constraints("ledger_entries")
        convention={"uq":"uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("ledger_entries",recreate="always",naming_convention=convention) as batch:
            for idx in indexes:
                if set(idx.get("column_names") or []).intersection(ledger_drop): batch.drop_index(idx["name"])
            for constraint in uniques:
                if set(constraint.get("column_names") or []).intersection(ledger_drop):
                    name=constraint.get("name") or f"uq_ledger_entries_{constraint['column_names'][0]}"
                    batch.drop_constraint(name,type_="unique")
            for name in ledger_drop: batch.drop_column(name)
    reward_columns={c["name"] for c in inspect(op.get_bind()).get_columns("rewards")}
    reward_drop=[n for n in ("brand_id","campaign_id","conversion_id","referral_id","order_item_id","product_id","reward_rule_id","source_key","eligible_amount","excluded_amount","currency","reward_type","reward_rate","fixed_amount","calculation_formula","rounding_rule","calculation_snapshot","risk_status","updated_at") if n in reward_columns]
    reward_indexes=inspect(op.get_bind()).get_indexes("rewards")
    reward_uniques=inspect(op.get_bind()).get_unique_constraints("rewards")
    if reward_drop:
        convention={"uq":"uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("rewards",recreate="always",naming_convention=convention) as batch:
            for idx in reward_indexes:
                if set(idx.get("column_names") or []).intersection(reward_drop): batch.drop_index(idx["name"])
            for constraint in reward_uniques:
                if set(constraint.get("column_names") or []).intersection(reward_drop):
                    name=constraint.get("name") or f"uq_rewards_{constraint['column_names'][0]}"
                    batch.drop_constraint(name,type_="unique")
            for name in reward_drop: batch.drop_column(name)
            batch.create_unique_constraint("uq_rewards_order_id",["order_id"])
    if "referral_id" in _columns("cart_items"):
        with op.batch_alter_table("cart_items") as batch:
            if "ix_cart_items_referral_id" in _indexes("cart_items"): batch.drop_index("ix_cart_items_referral_id")
            fk=next((f for f in inspect(op.get_bind()).get_foreign_keys("cart_items") if f.get("constrained_columns")==["referral_id"]),None)
            if fk and fk.get("name"): batch.drop_constraint(fk["name"],type_="foreignkey")
            batch.drop_column("referral_id")
    for table in ("simulated_payouts","reward_events","reward_rules"):
        if table in _tables(): op.drop_table(table)
