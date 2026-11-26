"""Add structured campaign objectives, audience, requirements, visibility and goals.

The initial revision creates current ORM metadata, so a brand-new database may
already have these columns before it reaches this revision. Inspect first to
support both fresh installs and upgrades from a historical Phase 5 database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_campaign_intelligence"
down_revision = "0006_rewards_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector=sa.inspect(op.get_bind())
    existing={column["name"] for column in inspector.get_columns("campaigns")}
    additions=(
        sa.Column("objectives",sa.JSON(),nullable=False,server_default=sa.text("'[]'")),
        sa.Column("target_audience",sa.String(length=500),nullable=False,server_default=""),
        sa.Column("creator_requirements",sa.Text(),nullable=False,server_default=""),
        sa.Column("visibility",sa.String(length=16),nullable=False,server_default="public"),
        sa.Column("performance_goals",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
    )
    for column in additions:
        if column.name not in existing:op.add_column("campaigns",column)
    # Normalize nullable values in partially applied/legacy schemas where possible.
    op.execute("UPDATE campaigns SET objectives='[]' WHERE objectives IS NULL")
    op.execute("UPDATE campaigns SET target_audience='' WHERE target_audience IS NULL")
    op.execute("UPDATE campaigns SET creator_requirements='' WHERE creator_requirements IS NULL")
    op.execute("UPDATE campaigns SET visibility='public' WHERE visibility IS NULL")
    op.execute("UPDATE campaigns SET performance_goals='{}' WHERE performance_goals IS NULL")
    constraints={item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("campaigns")}
    if "ck_campaign_visibility" not in constraints:
        with op.batch_alter_table("campaigns") as batch:
            batch.create_check_constraint("ck_campaign_visibility","visibility IN ('public','unlisted')")


def downgrade() -> None:
    # Keep additive configuration columns on downgrade. The 0001 baseline uses
    # current model metadata, which means these columns may predate this revision
    # on a fresh install; dropping them could destroy legitimate campaign setup.
    # Leaving unused columns is safe and allows a later re-upgrade without loss.
    pass
