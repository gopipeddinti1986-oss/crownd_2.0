"""Add recipient notifications, preferences, and encrypted email outbox.

The migration is additive. The outbox stores authenticated ciphertext so one-use
account action links are never persisted as plaintext. Downgrade intentionally
retains notification history and queued messages.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009_notifications"
down_revision = "0008_platform_admin"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def upgrade():
    tables = _tables()
    if "notification_preferences" not in tables:
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("category_settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_key", sa.String(160), nullable=False),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("body", sa.String(1000), nullable=False),
            sa.Column("action_path", sa.String(240), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("recipient_id", "event_key", name="uq_notification_recipient_event"),
        )
    if "email_deliveries" not in tables:
        op.create_table(
            "email_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_key", sa.String(160), nullable=False),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("essential", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("encrypted_message", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("recipient_id", "event_key", name="uq_email_delivery_recipient_event"),
            sa.CheckConstraint("status IN ('pending','sending','sent','suppressed','failed')", name="ck_email_delivery_status"),
            sa.CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempt_count"),
        )
    for table, column in (
        ("notification_preferences", "user_id"),
        ("notifications", "recipient_id"), ("notifications", "category"), ("notifications", "created_at"),
        ("email_deliveries", "recipient_id"), ("email_deliveries", "category"), ("email_deliveries", "status"),
        ("email_deliveries", "next_attempt_at"), ("email_deliveries", "created_at"),
    ):
        name = f"ix_{table}_{column}"
        if not any(index["name"] == name for index in inspect(op.get_bind()).get_indexes(table)):
            op.create_index(name, table, [column])


def downgrade():
    # Never drop notification history or queued, possibly credential-bearing mail.
    pass
